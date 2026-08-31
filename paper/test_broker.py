"""
체결 엔진 검증. `python paper/test_broker.py`로 돌린다.

broker는 네트워크를 모르므로 가짜 호가·체결 데이터만으로 전부 검증된다.
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.broker import Book, Broker, Level, Session

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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_broker 통과")
