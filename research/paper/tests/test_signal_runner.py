"""
실시간 시그널 러너 검증. `python paper/tests/test_signal_runner.py`로 돌린다.

네트워크를 타지 않는다:
  - 시세는 가짜 웹소켓 프레임(문자열 리스트)을 handle_message에 직접 먹인다.
  - HTTP는 signal_runner.requests를 가짜로 갈아끼워 가로챈다.
  - 전략은 strategies 패키지를 import하지 않고 여기서 만든 가짜를 쓴다
    (generate_signals 하나만 있으면 러너가 돈다).
"""
import json
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from paper.signal_runner import (KST, MinuteBars, SignalRunner, build_payload,
                                 parse_timestamp, parse_trade, post_signal)
import paper.signal_runner as runner_mod


# ---------------------------------------------------------------- 도구

def trade_msg(code="005930", price=71_500, volume=10, ts="2026-09-11T13:45:00+09:00"):
    """Kotlin /ws가 보내는 체결 메시지. ts=None이면 timestamp 키를 아예 뺀다."""
    msg = {"type": "trade", "stockCode": code, "price": price, "volume": volume}
    if ts is not None:
        msg["timestamp"] = ts
    return json.dumps(msg)


class FakeResponse:
    def __init__(self, status_code=200, text='{"received": true, "id": 1}'):
        self.status_code = status_code
        self.text = text


class FakeRequests:
    """signal_runner.requests 자리에 끼워 넣는 가짜. 보낸 것을 다 기록한다."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or FakeResponse()
        self.error = error

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


def swap_requests(fake):
    """가짜 requests를 끼우고 원본을 돌려준다 (테스트 끝에 되돌리기 위해)."""
    original = runner_mod.requests
    runner_mod.requests = fake
    return original


class 항상매수:
    """마지막 봉에서 항상 매수 신호를 내는 가짜 전략."""
    warmup = 0

    def generate_signals(self, df):
        return pd.Series([0] * (len(df) - 1) + [1], index=df.index)


class 신호없음:
    warmup = 0

    def generate_signals(self, df):
        return pd.Series([0] * len(df), index=df.index)


class 터지는전략:
    warmup = 0

    def generate_signals(self, df):
        raise RuntimeError("지표 계산 중 터졌다")


class 항상장중:
    """정규장 판정을 항상 참으로 만드는 가짜. 대부분의 테스트는 장 시간이
    관심사가 아니므로 이걸 기본으로 쓴다(안 그러면 toss API를 타게 된다)."""
    def is_open(self, now):
        return True


class 항상휴장:
    def is_open(self, now):
        return False


def new_runner(strategy=None, symbols=("005930",), history=None, market_hours=None):
    return SignalRunner(strategy or 항상매수(), list(symbols),
                        api_url="http://localhost:8080/api/signals",
                        history=history,
                        market_hours=market_hours or 항상장중())


def feed(runner, messages):
    for raw in messages:
        runner.handle_message(raw)


# ---------------------------------------------------------------- 틱 -> 분봉

def test_같은_분의_틱은_한_봉에_누적된다():
    bars = MinuteBars()
    t = datetime(2026, 9, 11, 13, 45, 0, tzinfo=KST)
    assert bars.add(100, 5, t) is None
    assert bars.add(120, 3, t.replace(second=20)) is None
    assert bars.add(90, 2, t.replace(second=59)) is None

    bar = bars.current
    assert bar["timestamp"] == t          # 봉의 시각은 '분의 시작'이다
    assert bar["open"] == 100             # 첫 틱
    assert bar["high"] == 120
    assert bar["low"] == 90
    assert bar["close"] == 90             # 마지막 틱
    assert bar["volume"] == 10            # 5 + 3 + 2
    assert bars.closed == []              # 아직 닫히지 않았다


def test_다음_분의_틱이_오면_앞_봉이_닫힌다():
    bars = MinuteBars()
    t = datetime(2026, 9, 11, 13, 45, 0, tzinfo=KST)
    bars.add(100, 5, t)
    closed = bars.add(200, 1, t + timedelta(minutes=1))

    assert closed is not None
    assert closed["timestamp"] == t and closed["close"] == 100
    assert bars.closed == [closed]
    # 새 봉은 다음 분의 첫 틱으로 열린다
    assert bars.current["timestamp"] == t + timedelta(minutes=1)
    assert bars.current["open"] == 200 and bars.current["volume"] == 1


def test_분을_건너뛰어도_직전_봉_하나만_닫는다():
    # 거래가 없는 분에는 빈 봉을 만들지 않는다 (타이머로 닫지 않는 설계의 결과).
    bars = MinuteBars()
    t = datetime(2026, 9, 11, 13, 45, 0, tzinfo=KST)
    bars.add(100, 1, t)
    bars.add(110, 1, t + timedelta(minutes=5))
    assert len(bars.closed) == 1
    assert bars.current["timestamp"] == t + timedelta(minutes=5)


def test_순서가_뒤집힌_늦은_틱은_현재_봉에_합친다():
    bars = MinuteBars()
    t = datetime(2026, 9, 11, 13, 46, 0, tzinfo=KST)
    bars.add(100, 1, t)
    bars.add(130, 2, t - timedelta(minutes=1))   # 한 분 늦게 도착
    assert bars.closed == []                      # 봉을 새로 닫지 않는다
    assert bars.current["high"] == 130 and bars.current["volume"] == 3


# ---------------------------------------------------------------- 메시지 파싱

def test_체결_메시지_파싱():
    t = parse_trade(trade_msg())
    assert t["stockCode"] == "005930"
    assert t["price"] == 71_500 and t["volume"] == 10
    assert t["timestamp"] == datetime(2026, 9, 11, 13, 45, tzinfo=KST)


def test_timestamp가_없으면_수신_시각으로_대체한다():
    before = datetime.now(KST)
    t = parse_trade(trade_msg(ts=None))
    after = datetime.now(KST)
    # 틱을 버리지 않는다. 실시간이라 수신 시각이 체결 시각의 좋은 근사다.
    assert t is not None
    assert before <= t["timestamp"] <= after


def test_모르는_type과_깨진_프레임은_조용히_무시된다():
    # 호가·신호 에코·PONG·깨진 JSON 전부 None. 예외를 던지면 읽기 루프가 끊긴다.
    assert parse_trade('{"type":"orderbook","symbol":"005930","asks":[],"bids":[]}') is None
    assert parse_trade('{"type":"signal","id":1,"stockCode":"005930","side":"BUY"}') is None
    assert parse_trade('{"type":"뭔가새로운거","stockCode":"005930"}') is None
    assert parse_trade("PONG") is None
    assert parse_trade("") is None
    assert parse_trade(None) is None
    assert parse_trade("[1,2,3]") is None


def test_필드가_빠지거나_말이_안_되는_체결은_버린다():
    assert parse_trade('{"type":"trade","price":100}') is None            # 종목코드 없음
    assert parse_trade('{"type":"trade","stockCode":"005930"}') is None   # 가격 없음
    assert parse_trade('{"type":"trade","stockCode":"005930","price":"abc"}') is None
    assert parse_trade('{"type":"trade","stockCode":"005930","price":0}') is None
    # volume은 없어도 된다 (0으로 본다)
    assert parse_trade('{"type":"trade","stockCode":"005930","price":100}')["volume"] == 0


def test_오프셋_없는_timestamp는_KST로_본다():
    assert parse_timestamp("2026-09-11T13:45:00") == datetime(2026, 9, 11, 13, 45, tzinfo=KST)


# ------------------------------------------------- 웹소켓 메시지 -> 분봉 누적

def test_웹소켓_메시지들이_분봉으로_쌓인다():
    r = new_runner(신호없음())
    feed(r, [
        trade_msg(price=100, volume=5, ts="2026-09-11T13:45:10+09:00"),
        '{"type":"orderbook","symbol":"005930","asks":[],"bids":[]}',   # 무시
        trade_msg(price=120, volume=5, ts="2026-09-11T13:45:40+09:00"),
        "깨진 프레임",                                                    # 무시
        trade_msg(price=110, volume=1, ts="2026-09-11T13:46:05+09:00"),
    ])
    bars = r.bars["005930"]
    assert len(bars.closed) == 1
    assert bars.closed[0] == {
        "timestamp": datetime(2026, 9, 11, 13, 45, tzinfo=KST),
        "open": 100, "high": 120, "low": 100, "close": 120, "volume": 10,
    }
    assert bars.current["open"] == 110


def test_timestamp_없는_체결도_봉에_들어간다():
    r = new_runner(신호없음())
    feed(r, [trade_msg(ts=None), trade_msg(price=72_000, ts=None)])
    bar = r.bars["005930"].current
    assert bar["volume"] == 20 and bar["close"] == 72_000


def test_구독하지_않은_종목은_무시한다():
    r = new_runner(신호없음(), symbols=("005930",))
    feed(r, [trade_msg(code="000660")])
    assert "000660" not in r.bars


def test_frame은_과거캔들_뒤에_실시간봉을_붙인다():
    hist = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-09-11 13:43:00+09:00",
                                     "2026-09-11 13:44:00+09:00"]),
        "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
        "close": [1.0, 2.0], "volume": [1.0, 1.0],
    })
    r = new_runner(신호없음(), history={"005930": hist})
    feed(r, [trade_msg(price=100, ts="2026-09-11T13:45:10+09:00"),
             trade_msg(price=110, ts="2026-09-11T13:46:10+09:00")])

    df = r.frame("005930")
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(df) == 3                     # 과거 2봉 + 닫힌 실시간 1봉
    assert df["close"].iloc[-1] == 100
    # 시각이 object dtype으로 뭉개지면 시간 기반 전략이 조용히 깨진다
    assert str(df["timestamp"].dtype).startswith("datetime64")
    assert list(df.index) == [0, 1, 2]       # 전략은 df와 같은 인덱스를 돌려줘야 한다


# ---------------------------------------------------------------- 페이로드 계약

def test_페이로드는_계약대로_만들어진다():
    p = build_payload("005930", "BUY", 71_500, "EmaCrossStrategy",
                      datetime(2026, 9, 11, 13, 45, tzinfo=KST),
                      note="ema9 > ema21 골든크로스")
    assert p == {
        "stockCode": "005930",
        "side": "BUY",
        "price": 71_500,
        "strategy": "EmaCrossStrategy",
        "timestamp": "2026-09-11T13:45:00+09:00",
        "note": "ema9 > ema21 골든크로스",
    }


def test_note가_없으면_키_자체가_빠진다():
    # null로 보내면 서버가 400을 낸다. 키를 빼는 것과 null은 다르다.
    p = build_payload("005930", "SELL", 71_500, "S", datetime(2026, 9, 11, tzinfo=KST))
    assert "note" not in p
    assert build_payload("005930", "SELL", 1, "S", "t", note=None) == {
        "stockCode": "005930", "side": "SELL", "price": 1, "strategy": "S", "timestamp": "t"}


def test_계약에_안_맞는_값은_만들_때_터진다():
    for bad in [lambda: build_payload("005930", "buy", 1, "S", "t"),      # 소문자
                lambda: build_payload("005930", "HOLD", 1, "S", "t"),
                lambda: build_payload("5930", "BUY", 1, "S", "t"),        # 6자리 아님
                lambda: build_payload("00593A", "BUY", 1, "S", "t"),
                lambda: build_payload("005930", "BUY", 0, "S", "t")]:     # 가격 0
        try:
            bad()
            assert False, "ValueError가 나야 한다"
        except ValueError:
            pass


def test_신호가_나면_봉_종가와_봉_시각으로_전송한다():
    fake = FakeRequests()
    original = swap_requests(fake)
    try:
        r = new_runner(항상매수())
        feed(r, [trade_msg(price=71_000, ts="2026-09-11T13:45:10+09:00"),
                 trade_msg(price=71_500, ts="2026-09-11T13:45:50+09:00"),
                 trade_msg(price=99_999, ts="2026-09-11T13:46:10+09:00")])  # 13:45 봉을 닫는다
    finally:
        runner_mod.requests = original

    assert len(fake.calls) == 1              # 닫힌 봉은 하나뿐이다
    call = fake.calls[0]
    assert call["url"] == "http://localhost:8080/api/signals"
    assert call["json"] == {
        "stockCode": "005930",
        "side": "BUY",
        "price": 71_500,                     # 다음 봉의 첫 틱이 아니라 닫힌 봉의 종가
        "strategy": "항상매수",                # 전략 클래스 이름
        "timestamp": "2026-09-11T13:45:00+09:00",
    }


def test_신호가_0이면_아무것도_보내지_않는다():
    fake = FakeRequests()
    original = swap_requests(fake)
    try:
        r = new_runner(신호없음())
        feed(r, [trade_msg(ts="2026-09-11T13:45:10+09:00"),
                 trade_msg(ts="2026-09-11T13:46:10+09:00")])
    finally:
        runner_mod.requests = original
    assert fake.calls == []


# ---------------------------------------------------------------- 장애 내성

def test_서버가_죽어_있어도_러너는_계속_돈다():
    # 연결 거부. post_signal이 예외를 내보내면 웹소켓 읽기 루프까지 죽는다.
    fake = FakeRequests(error=ConnectionError("서버 없음"))
    original = swap_requests(fake)
    try:
        r = new_runner(항상매수())
        feed(r, [trade_msg(price=100, ts="2026-09-11T13:45:00+09:00"),
                 trade_msg(price=200, ts="2026-09-11T13:46:00+09:00"),   # 전송 실패
                 trade_msg(price=300, ts="2026-09-11T13:47:00+09:00")])  # 그래도 계속
    finally:
        runner_mod.requests = original

    assert len(fake.calls) == 2                       # 두 번 다 시도했다
    assert len(r.bars["005930"].closed) == 2          # 봉 누적도 멈추지 않았다


def test_타임아웃과_400도_삼킨다():
    for fake in [FakeRequests(error=TimeoutError("느림")),
                 FakeRequests(response=FakeResponse(400, '{"error":"bad"}'))]:
        original = swap_requests(fake)
        try:
            assert post_signal("http://localhost:8080/api/signals",
                               {"stockCode": "005930", "side": "BUY",
                                "price": 1, "strategy": "S"}) is False
        finally:
            runner_mod.requests = original


def test_전략이_터져도_러너는_계속_돈다():
    r = new_runner(터지는전략())
    feed(r, [trade_msg(price=100, ts="2026-09-11T13:45:00+09:00"),
             trade_msg(price=200, ts="2026-09-11T13:46:00+09:00"),   # 여기서 전략이 터진다
             trade_msg(price=300, ts="2026-09-11T13:47:00+09:00")])
    assert len(r.bars["005930"].closed) == 2


# ---------------------------------------------------------------- 정규장 필터

def test_시간외_체결은_봉에_들어가지_않는다():
    """가장 중요한 케이스. 시간외단일가 체결이 분봉을 오염시키면 안 된다."""
    fake = FakeRequests()
    original = swap_requests(fake)
    try:
        r = new_runner(market_hours=항상휴장())
        feed(r, [trade_msg(price=100, ts="2026-09-11T17:16:00+09:00"),
                 trade_msg(price=200, ts="2026-09-11T17:17:00+09:00")])
        assert r.bars["005930"].closed == [], "시간외 체결이 봉으로 들어갔다"
        assert fake.calls == [], "시간외 체결에서 신호가 나갔다"
    finally:
        runner_mod.requests = original


def test_정규장_체결은_평소대로_들어간다():
    """필터가 정상 구간까지 막아버리면 러너가 통째로 죽은 것과 같다."""
    fake = FakeRequests()
    original = swap_requests(fake)
    try:
        r = new_runner(market_hours=항상장중())
        feed(r, [trade_msg(price=100, ts="2026-09-11T13:45:00+09:00"),
                 trade_msg(price=200, ts="2026-09-11T13:46:00+09:00")])
        assert len(r.bars["005930"].closed) == 1
        assert len(fake.calls) == 1
    finally:
        runner_mod.requests = original


def test_장마감_경계에서_뒤쪽_체결만_버린다():
    """정규장 종료 시각을 지나면 그 뒤 체결만 버리고, 앞 봉은 남는다."""
    class 세시반마감:
        def is_open(self, now):
            return now < datetime(2026, 9, 11, 15, 30, tzinfo=KST)

    fake = FakeRequests()
    original = swap_requests(fake)
    try:
        r = new_runner(market_hours=세시반마감())
        feed(r, [trade_msg(price=100, ts="2026-09-11T15:28:00+09:00"),
                 trade_msg(price=200, ts="2026-09-11T15:29:00+09:00"),   # 15:28봉이 닫힌다
                 trade_msg(price=999, ts="2026-09-11T17:16:00+09:00")])  # 시간외 — 버려짐
        closed = r.bars["005930"].closed
        assert len(closed) == 1 and closed[0]["close"] == 100
        assert all(c["json"]["price"] != 999 for c in fake.calls), \
            "시간외 가격으로 신호가 나갔다"
    finally:
        runner_mod.requests = original


def test_MarketHours는_하루에_한_번만_조회한다():
    """체결마다 네트워크를 타면 API 한 번 실패가 웹소켓 루프를 죽인다."""
    calls = []

    class 가짜세션:
        def is_open(self, now):
            return True

    def fetch():
        calls.append(1)
        return 가짜세션()

    mh = runner_mod.MarketHours(fetch=fetch)
    base = datetime(2026, 9, 11, 13, 45, tzinfo=KST)
    for i in range(50):
        mh.is_open(base + timedelta(seconds=i))
    assert len(calls) == 1, f"조회가 {len(calls)}번 일어났다"

    mh.is_open(base + timedelta(days=1))       # 날짜가 바뀌면 다시 조회
    assert len(calls) == 2


def test_MarketHours는_조회_실패하면_닫힌_것으로_본다():
    """장 구간을 모르는 채 신호를 내보내는 것보다 안 내보내는 쪽이 안전하다."""
    def 터지는fetch():
        raise RuntimeError("토스 API가 죽었다")

    mh = runner_mod.MarketHours(fetch=터지는fetch)
    assert mh.is_open(datetime(2026, 9, 11, 13, 45, tzinfo=KST)) is False


def test_MarketHours는_휴장이면_닫힌_것으로_본다():
    mh = runner_mod.MarketHours(fetch=lambda: None)      # 휴장일엔 get_session이 None
    assert mh.is_open(datetime(2026, 9, 11, 13, 45, tzinfo=KST)) is False


def test_MarketHours_조회_실패해도_매_틱마다_재시도하지_않는다():
    calls = []

    def 터지는fetch():
        calls.append(1)
        raise RuntimeError("죽었다")

    mh = runner_mod.MarketHours(fetch=터지는fetch)
    base = datetime(2026, 9, 11, 13, 45, tzinfo=KST)
    for i in range(30):
        mh.is_open(base + timedelta(seconds=i))
    assert len(calls) == 1, f"실패 후 {len(calls)}번 재시도했다"


def test_워밍업_DB가_없으면_빈_프레임을_준다():
    from paper.signal_runner import load_warmup
    df = load_warmup("005930", 10, db_path=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "없는파일.db"))
    assert df.empty and list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_signal_runner 통과")
