"""
toss.py의 파싱 검증. 네트워크를 타지 않고 응답 JSON 파싱만 본다.

실제 호출은 IP 등록·장 운영시간에 따라 결과가 달라져서 테스트로 못 쓴다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.toss import parse_orderbook, parse_prices, parse_session


def test_현재가_파싱은_문자열을_정수로_바꾼다():
    body = {"result": [{"symbol": "005930", "timestamp": "...",
                        "lastPrice": "258500", "currency": "KRW"}]}
    assert parse_prices(body) == {"005930": 258_500}


def test_호가_파싱이_정렬과_타입을_지킨다():
    body = {"result": {"timestamp": "...", "currency": "KRW",
                       "asks": [{"price": "259000", "volume": "75814"},
                                {"price": "259500", "volume": "79891"}],
                       "bids": [{"price": "258500", "volume": "91468"}]}}
    b = parse_orderbook("005930", body)
    assert b.symbol == "005930"
    assert b.asks[0].price == 259_000 and b.asks[0].volume == 75_814
    assert b.bids[0].price == 258_500
    assert isinstance(b.asks[0].price, int)


def test_장운영시간_파싱():
    body = {"result": {"today": {"date": "2026-08-31", "integrated": {
        "regularMarket": {
            "startTime": "2026-08-31T09:00:00.000+09:00",
            "endTime": "2026-08-31T15:30:00.000+09:00"}}}}}
    s = parse_session(body)
    assert s.start.hour == 9 and s.end.hour == 15 and s.end.minute == 30
    assert s.is_open(datetime(2026, 8, 31, 10, 0, tzinfo=s.start.tzinfo))


def test_휴장일이면_None():
    body = {"result": {"today": {"date": "2026-08-30", "integrated": None}}}
    assert parse_session(body) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_toss 통과")
