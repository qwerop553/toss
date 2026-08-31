"""
체결 엔진 검증. `python paper/test_broker.py`로 돌린다.

broker는 네트워크를 모르므로 가짜 호가·체결 데이터만으로 전부 검증된다.
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.broker import Book, Broker, Level, OrderRejected, Session

# 정규장 09:00~15:30. 테스트는 전부 이 안의 시각을 쓴다.
DAY = datetime(2026, 8, 31, 10, 0, 0)
SESSION = Session(start=datetime(2026, 8, 31, 9, 0), end=datetime(2026, 8, 31, 15, 30))


def new_broker(cash=10_000_000):
    """테스트마다 빈 DB를 새로 만든다. 파일은 임시 디렉터리에 둔다."""
    path = os.path.join(tempfile.mkdtemp(), "paper.db")
    return Broker(path, initial_cash=cash)


def book(symbol="005930", asks=((259_000, 100), (259_500, 50)),
         bids=((258_500, 80), (258_000, 40))):
    return Book(symbol=symbol,
                asks=[Level(p, v) for p, v in asks],
                bids=[Level(p, v) for p, v in bids])


def test_초기_현금은_초기자본이다():
    b = new_broker(5_000_000)
    assert b.cash() == 5_000_000
    assert b.positions() == {}


def test_매수_체결이_현금과_보유에_반영된다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="2026-08-31T10:00:00")
    # 수수료 = 1,000,000 * 0.00015 = 150원
    assert b.cash() == 10_000_000 - 1_000_000 - 150
    pos = b.positions()["005930"]
    assert pos.qty == 10
    # 평균단가는 수수료를 포함한다 (실제 증권앱의 매입단가와 같은 기준)
    assert abs(pos.avg_cost - (1_000_000 + 150) / 10) < 1e-9


def test_매도_체결에_수수료와_거래세가_둘_다_붙는다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="2026-08-31T10:00:00")
    b._record_fill(2, "005930", "sell", qty=10, price=110_000, at="2026-08-31T10:01:00")
    # 매도 대금 1,100,000 / 수수료 165 / 거래세 2,200
    expected = 10_000_000 - 1_000_000 - 150 + 1_100_000 - 165 - 2_200
    assert b.cash() == expected
    assert "005930" not in b.positions()   # 전량 매도하면 보유에서 빠진다


def test_평균단가는_총평균법이고_매도해도_변하지_않는다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="t1")
    b._record_fill(2, "005930", "buy", qty=10, price=120_000, at="t2")
    avg_before = b.positions()["005930"].avg_cost
    # (1,000,000+150 + 1,200,000+180) / 20 = 110,016.5
    assert abs(avg_before - 110_016.5) < 1e-6

    b._record_fill(3, "005930", "sell", qty=5, price=130_000, at="t3")
    pos = b.positions()["005930"]
    assert pos.qty == 15
    assert abs(pos.avg_cost - avg_before) < 1e-6   # 매도는 평균단가를 안 건드린다


def test_시장가_매수가_호가를_다단으로_훑는다():
    b = new_broker(100_000_000)
    # 259,000에 100주, 259,500에 50주 있는 호가에 120주 시장가 매수
    oid = b.place("005930", "buy", "market", 120,
                  book=book(), session=SESSION, now=DAY)
    fills = b.fills_of(oid)
    assert len(fills) == 2
    assert (fills[0]["price"], fills[0]["qty"]) == (259_000, 100)
    assert (fills[1]["price"], fills[1]["qty"]) == (259_500, 20)
    assert b.order(oid)["status"] == "filled"
    assert b.positions()["005930"].qty == 120


def test_호가가_모자라면_채운_만큼만_체결하고_끝낸다():
    b = new_broker(100_000_000)
    # 호가 전체가 150주뿐인데 200주를 시장가로 산다
    oid = b.place("005930", "buy", "market", 200,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["filled_qty"] == 150
    # partial은 종료 상태다. 남은 50주는 대기하지 않는다.
    assert b.order(oid)["status"] == "partial"


def test_시장가_매도는_매수호가를_훑는다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=100, price=250_000, at="t0")
    oid = b.place("005930", "sell", "market", 100,
                  book=book(), session=SESSION, now=DAY)
    fills = b.fills_of(oid)
    assert (fills[0]["price"], fills[0]["qty"]) == (258_500, 80)
    assert (fills[1]["price"], fills[1]["qty"]) == (258_000, 20)
    assert b.order(oid)["status"] == "filled"
    assert "005930" not in b.positions()


def test_시장가는_pending을_거치지_않는다():
    b = new_broker(100_000_000)
    oid = b.place("005930", "buy", "market", 10,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "filled"
    assert b.open_orders() == []


def test_불리한_지정가는_pending으로_남는다():
    b = new_broker()
    # 매도1호가가 259,000인데 250,000에 사겠다고 걸어 둔다
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "pending"
    assert b.order(oid)["filled_qty"] == 0
    assert len(b.open_orders()) == 1


def test_이미_유리한_지정가는_즉시_체결된다():
    b = new_broker(100_000_000)
    # 매도1호가 259,000보다 높은 260,000에 사겠다면 지금 바로 체결된다
    oid = b.place("005930", "buy", "limit", 50, 260_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "filled"
    assert b.fills_of(oid)[0]["price"] == 259_000   # 내 지정가가 아니라 호가에 체결


def test_지정가가_체결_프린트로_채워진다():
    b = new_broker()
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    # 250,000 아래로 체결이 프린트되면 채워진다
    fills = b.on_trade("005930", price=249_500, volume=100, now=DAY)
    assert len(fills) == 1
    assert fills[0].qty == 10
    assert fills[0].price == 249_500      # 프린트 가격에 체결
    assert b.order(oid)["status"] == "filled"
    assert b.open_orders() == []


def test_지정가_부분체결은_pending으로_남는다():
    b = new_broker(100_000_000)
    oid = b.place("005930", "buy", "limit", 100, 250_000,
                  book=book(), session=SESSION, now=DAY)
    b.on_trade("005930", price=250_000, volume=30, now=DAY)
    row = b.order(oid)
    assert row["filled_qty"] == 30
    # 아직 더 체결될 수 있으므로 partial이 아니라 pending이다
    assert row["status"] == "pending"
    b.on_trade("005930", price=249_000, volume=70, now=DAY)
    assert b.order(oid)["status"] == "filled"


def test_불리한_프린트는_지정가를_건드리지_않는다():
    b = new_broker()
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)
    assert b.on_trade("005930", price=251_000, volume=100, now=DAY) == []


def test_매도_지정가는_프린트가_지정가_이상일_때_체결된다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=10, price=250_000, at="t0")
    oid = b.place("005930", "sell", "limit", 10, 270_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "pending"
    assert b.on_trade("005930", price=269_000, volume=100, now=DAY) == []
    fills = b.on_trade("005930", price=271_000, volume=100, now=DAY)
    assert len(fills) == 1 and fills[0].price == 271_000


def test_다른_종목의_프린트는_무시된다():
    b = new_broker()
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)
    assert b.on_trade("000660", price=100, volume=1000, now=DAY) == []


def 거부되는가(fn) -> str:
    """OrderRejected가 나는지 확인하고 메시지를 돌려준다."""
    try:
        fn()
    except OrderRejected as exc:
        return str(exc)
    raise AssertionError("거부됐어야 하는데 통과했다")


def test_현금이_모자라면_거부된다():
    b = new_broker(cash=1_000_000)     # 100만원으로 259,000짜리 10주는 못 산다
    msg = 거부되는가(lambda: b.place("005930", "buy", "market", 10,
                                   book=book(), session=SESSION, now=DAY))
    assert "현금" in msg


def test_미체결_매수의_예약금액이_두번째_주문을_막는다():
    b = new_broker(cash=3_000_000)
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)   # 250만원 예약
    assert b.reserved() == 2_500_000
    assert b.available_cash() == 500_000
    msg = 거부되는가(lambda: b.place("005930", "buy", "limit", 10, 250_000,
                                   book=book(), session=SESSION, now=DAY))
    assert "현금" in msg


def test_취소하면_예약금액이_풀린다():
    b = new_broker(cash=3_000_000)
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    b.cancel(oid, now=DAY)
    assert b.order(oid)["status"] == "cancelled"
    assert b.reserved() == 0
    assert b.available_cash() == 3_000_000


def test_보유하지_않은_종목은_팔_수_없다():
    b = new_broker()
    msg = 거부되는가(lambda: b.place("005930", "sell", "market", 10,
                                   book=book(), session=SESSION, now=DAY))
    assert "보유" in msg


def test_미체결_매도도_보유수량을_묶는다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=10, price=250_000, at="t0")
    b.place("005930", "sell", "limit", 10, 300_000,
            book=book(), session=SESSION, now=DAY)
    # 10주 전부 매도 대기 중이므로 더 팔 수 없다
    msg = 거부되는가(lambda: b.place("005930", "sell", "market", 5,
                                   book=book(), session=SESSION, now=DAY))
    assert "보유" in msg


def test_호가단위에_맞지_않는_지정가는_거부된다():
    b = new_broker()
    msg = 거부되는가(lambda: b.place("005930", "buy", "limit", 1, 258_550,
                                   book=book(), session=SESSION, now=DAY))
    assert "호가단위" in msg


def test_장_시간_밖_주문은_거부된다():
    b = new_broker()
    저녁 = datetime(2026, 8, 31, 16, 0)
    msg = 거부되는가(lambda: b.place("005930", "buy", "market", 1,
                                   book=book(), session=SESSION, now=저녁))
    assert "정규장" in msg


def test_수량이_0_이하면_거부된다():
    b = new_broker()
    assert "수량" in 거부되는가(lambda: b.place("005930", "buy", "market", 0,
                                            book=book(), session=SESSION, now=DAY))


def test_만료가_미체결을_전부_정리한다():
    b = new_broker()
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    마감 = datetime(2026, 8, 31, 15, 30)
    assert b.expire_all(now=마감) == [oid]
    assert b.order(oid)["status"] == "expired"
    assert b.reserved() == 0


def test_리셋이_주문과_체결을_모두_지운다():
    b = new_broker()
    b.place("005930", "buy", "market", 10, book=book(), session=SESSION, now=DAY)
    b.reset()
    assert b.cash() == 10_000_000
    assert b.positions() == {}
    assert b.orders() == []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_broker 통과")
