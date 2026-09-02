"""구독 선언과 이벤트 파싱 검증. 네트워크를 타지 않는다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from paper.feed import MAX_SYMBOLS, build_declaration, parse_event


def test_구독_선언은_id와_두_채널을_담는다():
    d = build_declaration(["005930", "000660"], "req-1")
    assert d[0] == {"id": "req-1"}
    types = {x["type"]: x["codes"] for x in d[1:]}
    assert types["trade:kr"] == ["005930", "000660"]
    assert types["orderbook:kr"] == ["005930", "000660"]


def test_빈_목록은_id만_보낸다():
    # full-replace라 빈 선언이 곧 '전부 구독 해제'다
    assert build_declaration([], "req-9") == [{"id": "req-9"}]


def test_종목_상한은_50이다():
    # 연결당 구독 100건 / 종목당 2건(trade+orderbook) = 50종목
    assert MAX_SYMBOLS == 50


def test_체결_이벤트_파싱():
    raw = ('{"type":"message","topic":"trade:kr:005930",'
           '"data":{"price":"258500","volume":"12","timestamp":"t","currency":"KRW"}}')
    kind, symbol, data = parse_event(raw)
    assert kind == "trade" and symbol == "005930"
    assert data["price"] == 258_500 and data["volume"] == 12


def test_호가_이벤트_파싱():
    raw = ('{"type":"message","topic":"orderbook:kr:005930","data":{'
           '"timestamp":"t","currency":"KRW",'
           '"asks":[{"price":"259000","volume":"100"}],'
           '"bids":[{"price":"258500","volume":"80"}]}}')
    kind, symbol, data = parse_event(raw)
    assert kind == "orderbook" and symbol == "005930"
    assert data["asks"][0].price == 259_000
    assert data["bids"][0].volume == 80


def test_필드가_빠지거나_숫자가_아닌_프레임에도_터지지_않는다():
    # parse_event가 예외를 던지면 run()의 `async for`를 뚫고 나가 연결이
    # 통째로 끊기고, 끊긴 동안 지정가 체결 판정이 멈춘다. 프레임 하나는 버리고
    # 연결은 지켜야 한다.
    assert parse_event('{"type":"message","topic":"trade:kr:005930",'
                       '"data":{"volume":"12"}}') is None            # price 없음
    assert parse_event('{"type":"message","topic":"trade:kr:005930",'
                       '"data":{"price":"abc","volume":"1"}}') is None  # 숫자 아님
    assert parse_event('{"type":"message","topic":"orderbook:kr:005930",'
                       '"data":{"asks":[{"price":"100"}],"bids":[]}}') is None
    assert parse_event('{"type":"message","topic":"trade:kr:005930"}') is None


def test_pong과_알수없는_메시지는_None():
    assert parse_event('{"type":"pong"}') is None
    assert parse_event('{"type":"message","topic":"trade:us:AAPL","data":{}}') is None
    assert parse_event("PONG") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_feed 통과")
