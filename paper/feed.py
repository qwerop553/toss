"""
토스 웹소켓 업스트림. 연결을 하나만 물고 콜백으로 흘려보낸다.

왜 연결이 하나인가:
  계정당 동시 연결이 2개로 제한된다. 브라우저 탭마다 새로 붙이면 탭 3개에서
  막힌다. 그래서 백엔드가 하나를 물고 브라우저에는 자체 /ws로 팬아웃한다.

왜 브라우저가 직접 못 붙나:
  핸드셰이크에 Authorization 헤더가 필요한데 브라우저 WebSocket API는 커스텀
  헤더를 넣을 수 없고, 넣을 수 있더라도 액세스 토큰이 프론트로 새어 나간다.
"""
import asyncio
import json

import websockets

from paper.broker import Level
from scrap import get_access_token

WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"

# 연결당 구독 100건 / 종목당 trade+orderbook 2건 = 50종목
MAX_SYMBOLS = 50

PING_INTERVAL = 60      # 서버는 180초 무수신이면 끊는다
BACKOFF_MAX = 30


def build_declaration(symbols: list[str], req_id: str) -> list[dict]:
    """
    구독 선언. 이 프로토콜은 full-replace라 '추가'가 아니라 '지금 구독 전체'다.
    빈 목록을 보내면 전부 구독 해제된다.
    """
    decl: list[dict] = [{"id": req_id}]
    if symbols:
        decl.append({"type": "trade:kr", "codes": list(symbols)})
        decl.append({"type": "orderbook:kr", "codes": list(symbols)})
    return decl


def parse_event(raw: str):
    """
    수신 프레임 하나를 (kind, symbol, data)로. 관심 없는 프레임은 None.

    숫자는 전부 문자열로 오므로 여기서 int로 바꾼다. 이 경계를 넘어가면
    체결 엔진이 문자열 비교를 하게 되고, '9' > '10'이 참이 되는 식으로
    조용히 틀린다.
    """
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if msg.get("type") != "message":
        return None

    topic = msg.get("topic", "")
    parts = topic.split(":")
    if len(parts) != 3 or parts[1] != "kr":
        return None            # 미국 주식은 이 사이트의 범위 밖이다
    channel, _, symbol = parts
    data = msg.get("data") or {}

    if channel == "trade":
        return "trade", symbol, {"price": int(data["price"]),
                                 "volume": int(data["volume"]),
                                 "timestamp": data.get("timestamp")}
    if channel == "orderbook":
        lv = lambda side: [Level(int(x["price"]), int(x["volume"]))
                           for x in data.get(side, [])]
        return "orderbook", symbol, {"asks": lv("asks"), "bids": lv("bids")}
    return None


class Feed:
    def __init__(self, on_trade, on_orderbook, on_status):
        self.on_trade = on_trade
        self.on_orderbook = on_orderbook
        self.on_status = on_status
        self._symbols: list[str] = []
        self._ws = None
        self._seq = 0

    def set_symbols(self, symbols: list[str]) -> None:
        """관심종목이 바뀌면 전체를 다시 선언한다 (full-replace라 그래야 한다)."""
        if len(symbols) > MAX_SYMBOLS:
            raise ValueError(
                f"구독 가능한 종목은 {MAX_SYMBOLS}개까지입니다 "
                f"(연결당 구독 100건 / 종목당 2건).")
        self._symbols = list(symbols)
        if self._ws is not None:
            asyncio.create_task(self._declare())

    async def _declare(self) -> None:
        if self._ws is None:
            return
        self._seq += 1
        await self._ws.send(json.dumps(
            build_declaration(self._symbols, f"req-{self._seq}")))

    async def _keepalive(self) -> None:
        # 순수 텍스트 'PING'이다. JSON으로 감싸면 서버가 못 알아듣는다.
        while True:
            await asyncio.sleep(PING_INTERVAL)
            if self._ws is not None:
                await self._ws.send("PING")

    async def run(self) -> None:
        """끊기면 지수 백오프로 다시 붙는다. 이 코루틴은 종료되지 않는다."""
        backoff = 1
        while True:
            try:
                async with websockets.connect(
                        WS_URL,
                        additional_headers={
                            "Authorization": f"Bearer {get_access_token()}"},
                ) as ws:
                    self._ws = ws
                    backoff = 1
                    await self._declare()
                    self.on_status("connected", "")
                    ping = asyncio.create_task(self._keepalive())
                    try:
                        async for raw in ws:
                            self._dispatch(raw)
                    finally:
                        ping.cancel()
            except Exception as exc:
                # 끊긴 동안 지정가 체결 판정이 멈춘다. 조용히 두면 사용자는
                # 체결됐어야 할 주문이 왜 안 됐는지 모른다. 반드시 알린다.
                self.on_status("reconnecting", f"{type(exc).__name__}: {exc}")
            finally:
                self._ws = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)

    def _dispatch(self, raw) -> None:
        parsed = parse_event(raw)
        if parsed is None:
            return
        kind, symbol, data = parsed
        if kind == "trade":
            self.on_trade(symbol, data)
        else:
            self.on_orderbook(symbol, data)
