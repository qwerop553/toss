"""
토스증권 Open API의 **읽기 전용** 래퍼.

경고 — 이 파일에 주문 관련 함수를 추가하지 마라:
  토스 Open API에는 모의투자 sandbox가 없다. 서버가 실서버 하나뿐이라
  주문을 넣는 엔드포인트를 부르면 그건 실제 돈이 나가는 진짜 주문이다.
  이 사이트의 체결은 전부 paper/broker.py가 시뮬레이션한다.
  실매매가 필요해지면 그건 별도의 결정으로 다뤄야 한다.

숫자는 전부 문자열로 오므로 파싱 시점에 int로 바꾼다.
"""
from datetime import datetime, timedelta, timezone

import requests

from paper.broker import Book, Level, Session
from data.auth import get_access_token

API = "https://openapi.tossinvest.com/api/v1"


class TossError(Exception):
    """kind: 'auth'(토큰) | 'ip'(IP 미등록) | 'other'. 화면에 구분해 띄운다."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def _get(path: str, params: dict) -> dict:
    resp = requests.get(f"{API}/{path}",
                        headers={"Authorization": f"Bearer {get_access_token()}"},
                        params=params, timeout=10)
    if resp.ok:
        return resp.json()

    text = resp.text
    # 401을 '토큰 만료'로 뭉뚱그리면 안 된다. 이 API는 IP 미등록으로 막히는
    # 경우가 더 잦은데, 그때 토큰을 다시 발급받아 봐야 계속 막힌다.
    kind = "other"
    if "IP" in text or "ip-not-allowed" in text:
        kind = "ip"
    elif resp.status_code in (401, 403):
        kind = "auth"
    raise TossError(f"[{resp.status_code}] {text[:200]}", kind)


def parse_prices(body: dict) -> dict[str, int]:
    return {r["symbol"]: int(r["lastPrice"]) for r in body["result"]}


def parse_orderbook(symbol: str, body: dict) -> Book:
    r = body["result"]
    lv = lambda side: [Level(int(x["price"]), int(x["volume"])) for x in r[side]]
    return Book(symbol=symbol, asks=lv("asks"), bids=lv("bids"))


KST = timezone(timedelta(hours=9))


def parse_session(body: dict) -> Session | None:
    """
    오늘의 정규장 구간. 휴장이면 None.

    startTime/endTime에 오프셋이 안 붙어 오면 fromisoformat이 naive datetime을
    돌려주는데, 그러면 나중에 tz-aware한 현재 시각과 비교할 때(Session.is_open)
    naive와 aware를 섞어 TypeError가 난다. 장이 KST로 운영되므로 그 경우
    KST를 붙인다.
    """
    today = body["result"]["today"]
    integrated = today.get("integrated")
    if not integrated:
        return None
    reg = integrated["regularMarket"]
    start = datetime.fromisoformat(reg["startTime"])
    end = datetime.fromisoformat(reg["endTime"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=KST)
    if end.tzinfo is None:
        end = end.replace(tzinfo=KST)
    return Session(start=start, end=end)


def get_prices(symbols: list[str]) -> dict[str, int]:
    """현재가. symbols는 복수형이라 한 번에 여러 종목을 묶을 수 있다."""
    if not symbols:
        return {}
    return parse_prices(_get("prices", {"symbols": ",".join(symbols)}))


def get_orderbook(symbol: str) -> Book:
    """호가 10단. 이 엔드포인트는 단수형이라 종목 하나씩만 된다."""
    return parse_orderbook(symbol, _get("orderbook", {"symbol": symbol}))


def get_stocks(symbols: list[str]) -> list[dict]:
    return _get("stocks", {"symbols": ",".join(symbols)})["result"]


def get_session() -> Session | None:
    return parse_session(_get("market-calendar/KR", {}))
