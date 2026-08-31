"""
모의투자 웹서버.

    python -m uvicorn paper.app:app --reload

브라우저 → 이 서버 → 토스. 브라우저가 토스에 직접 붙지 못하는 이유는
paper/feed.py의 docstring에 있다.
"""
import asyncio
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import scrap
from paper import toss
from paper.broker import Book, Broker, Level, OrderRejected
from paper.feed import MAX_SYMBOLS, Feed

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE), "paper.db")

app = FastAPI(title="모의투자")
broker = Broker(DB_PATH)

# 최신 호가 스냅샷. 시장가 주문이 훑을 대상이고, REST를 매번 부르지 않으려고
# 웹소켓으로 들어온 값을 여기에 덮어 쓴다.
books: dict[str, Book] = {}
last_price: dict[str, int] = {}
session_cache: dict = {"date": None, "session": None}
feed_status = {"status": "starting", "message": ""}

clients: set[WebSocket] = set()
loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------- 브로드캐스트

def broadcast(payload: dict) -> None:
    """
    브라우저 전부에 밀어 넣는다. feed 콜백은 이벤트 루프 밖에서 불릴 수 있어
    call_soon_threadsafe로 넘긴다.
    """
    if loop is None:
        return
    loop.call_soon_threadsafe(asyncio.create_task, _fanout(payload))


async def _fanout(payload: dict) -> None:
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


# ---------------------------------------------------------------- feed 콜백

def on_trade(symbol: str, data: dict) -> None:
    last_price[symbol] = data["price"]
    broadcast({"type": "trade", "symbol": symbol,
               "price": data["price"], "volume": data["volume"]})

    # 체결 프린트로 대기 중인 지정가를 판정한다. 여기가 지정가가 채워지는
    # 유일한 경로라, 업스트림이 끊기면 이 판정이 통째로 멈춘다.
    fills = broker.on_trade(symbol, data["price"], data["volume"], tz_now())
    for f in fills:
        broadcast({"type": "fill", "order_id": f.order_id, "symbol": f.symbol,
                   "side": f.side, "qty": f.qty, "price": f.price})
    if fills:
        broadcast(portfolio_payload())


def on_orderbook(symbol: str, data: dict) -> None:
    books[symbol] = Book(symbol=symbol, asks=data["asks"], bids=data["bids"])
    broadcast({"type": "orderbook", "symbol": symbol,
               "asks": [[l.price, l.volume] for l in data["asks"]],
               "bids": [[l.price, l.volume] for l in data["bids"]]})


def on_status(status: str, message: str) -> None:
    feed_status.update(status=status, message=message)
    broadcast({"type": "feed", "status": status, "message": message})


feed = Feed(on_trade=on_trade, on_orderbook=on_orderbook, on_status=on_status)


# ---------------------------------------------------------------- 공통 헬퍼

def watchlist() -> list[str]:
    return [r["symbol"] for r in broker.conn.execute(
        "SELECT symbol FROM watchlist ORDER BY added_at").fetchall()]


def current_session():
    """오늘의 정규장 구간. 하루 한 번만 API를 부른다."""
    today = datetime.now().date().isoformat()
    if session_cache["date"] != today:
        session_cache.update(date=today, session=toss.get_session())
    return session_cache["session"]


def tz_now() -> datetime:
    """
    타임존이 있는 현재 시각. fills.at / orders.updated_at에 기록되는 시각은
    전부 이 함수를 거친다 — 정규장 세션의 tzinfo를 쓰고, 세션을 아직 못 받아온
    경우(예: 서버가 막 뜬 직후 feed 콜백이 먼저 들어오는 경우)에만 로컬
    타임존을 쓴다. naive datetime과 tz-aware datetime이 같은 컬럼에 섞여
    들어가면 나중에 시각을 정렬·비교할 때 조용히 틀린다.
    """
    session = current_session()
    return datetime.now(session.start.tzinfo) if session else datetime.now().astimezone()


def book_of(symbol: str) -> Book:
    """
    시장가가 훑을 호가. 웹소켓 스냅샷이 있으면 그걸 쓰고, 없으면 REST로 받는다.

    구독 직후에는 스냅샷이 오지 않으므로(다음 갱신부터 푸시된다) 이 fallback이
    없으면 종목을 막 추가한 직후의 시장가 주문이 빈 호가를 훑게 된다.
    """
    if symbol not in books:
        books[symbol] = toss.get_orderbook(symbol)
    return books[symbol]


def portfolio_payload() -> dict:
    positions = []
    for symbol, pos in broker.positions().items():
        price = last_price.get(symbol) or 0
        value = price * pos.qty
        cost = pos.avg_cost * pos.qty
        positions.append({
            "symbol": symbol, "qty": pos.qty, "avg_cost": round(pos.avg_cost),
            "price": price, "value": value, "pnl": round(value - cost),
            "pnl_pct": round((value - cost) / cost * 100, 2) if cost else 0.0,
        })
    return {"type": "portfolio", "cash": broker.cash(),
            "available": broker.available_cash(),
            "reserved": broker.reserved(), "positions": positions}


# ---------------------------------------------------------------- 수명주기

@app.on_event("startup")
async def startup() -> None:
    global loop
    loop = asyncio.get_running_loop()
    syms = watchlist()
    if syms:
        feed.set_symbols(syms)
        try:
            last_price.update(toss.get_prices(syms))
        except toss.TossError as exc:
            on_status("error", str(exc))
    asyncio.create_task(feed.run())
    asyncio.create_task(expire_at_close())


async def expire_at_close() -> None:
    """
    장 마감에 미체결 주문을 만료시킨다.

    실제 주문은 당일 만료다. 이걸 안 하면 어제 걸어 둔 지정가가 오늘 시세에
    체결되는데, 그건 실제로는 일어나지 않는 일이라 잔고가 거짓이 된다.

    ponytail: 1분마다 시각만 확인하는 폴링이다. 정확한 시각에 깨우려면 타이머를
    장 구간에 맞춰 재설정해야 하는데, 서버가 며칠씩 떠 있는 물건이 아니라서
    그만한 정밀도가 필요 없다.
    """
    while True:
        await asyncio.sleep(60)
        session = current_session()
        if session is None:
            continue
        now = tz_now()
        if now >= session.end:
            expired = broker.expire_all(now=now)
            if expired:
                broadcast({"type": "expired", "order_ids": expired})
                broadcast(portfolio_payload())


# ---------------------------------------------------------------- REST

class OrderIn(BaseModel):
    symbol: str
    side: str
    type: str
    qty: int
    limit_price: int | None = None


class WatchIn(BaseModel):
    symbol: str
    action: str      # 'add' | 'remove'


@app.get("/api/watchlist")
def api_watchlist():
    syms = watchlist()
    names: dict[str, str] = {}
    try:
        prices = toss.get_prices(syms)
        last_price.update(prices)
        # get_stocks(종목명 조회)도 같은 try 안에 둔다. get_prices가 성공해도
        # get_stocks만 따로 실패할 수 있는데(예: IP 미등록), 이름 하나 못 가져온
        # 것 때문에 화면 전체가 500으로 죽으면 안 된다 — 실패하면 이름 대신
        # 종목코드를 그대로 보여준다.
        names = {s["symbol"]: s["name"] for s in toss.get_stocks(syms)} if syms else {}
    except toss.TossError as exc:
        prices = dict(last_price)
        on_status("error", str(exc))
    return [{"symbol": s, "name": names.get(s, s), "price": prices.get(s)}
            for s in syms]


@app.post("/api/watchlist")
async def api_watch(body: WatchIn):
    # async def여야 한다: feed.set_symbols()가 내부에서 asyncio.create_task를
    # 직접 부르는데, 그건 '지금 실행 중인 이벤트 루프'가 있어야 한다. 이 함수가
    # 평범한 def였다면 FastAPI가 스레드풀에서 돌리므로 그 스레드에는 루프가
    # 없어 RuntimeError로 죽는다 (관심종목 추가는 DB에는 기록되지만 feed 구독
    # 갱신은 조용히 실패해, 새로 추가한 종목에 실시간 시세가 안 들어온다).
    if body.action == "add":
        if len(watchlist()) >= MAX_SYMBOLS:
            raise HTTPException(400, f"관심종목은 {MAX_SYMBOLS}개까지입니다.")
        broker.conn.execute(
            "INSERT OR IGNORE INTO watchlist (symbol, added_at) VALUES (?, ?)",
            (body.symbol, datetime.now().isoformat()))
    else:
        broker.conn.execute("DELETE FROM watchlist WHERE symbol = ?", (body.symbol,))
    broker.conn.commit()
    feed.set_symbols(watchlist())
    return {"ok": True, "watchlist": watchlist()}


@app.get("/api/quote")
def api_quote(symbol: str):
    b = book_of(symbol)
    return {"symbol": symbol, "price": last_price.get(symbol),
            "asks": [[l.price, l.volume] for l in b.asks],
            "bids": [[l.price, l.volume] for l in b.bids]}


@app.get("/api/candles")
def api_candles(symbol: str, interval: str = "1m"):
    """차트용 분봉. market_data.db를 최신까지 당긴 뒤 읽는다(증분이라 안전하다)."""
    try:
        scrap.update_candles(symbol, interval)
    except Exception as exc:
        on_status("error", f"캔들 수집 실패: {exc}")
    df = scrap.load_candles(symbol, interval)
    if df.empty:
        return []
    df = df.tail(500)
    return [{"time": t.isoformat(), "open": o, "high": h, "low": l, "close": c}
            for t, o, h, l, c in zip(df["timestamp"], df["open"], df["high"],
                                     df["low"], df["close"])]


@app.post("/api/orders")
def api_place(body: OrderIn):
    session = current_session()
    if session is None:
        raise HTTPException(400, "오늘은 휴장일입니다.")
    try:
        oid = broker.place(body.symbol, body.side, body.type, body.qty,
                           body.limit_price, book=book_of(body.symbol),
                           session=session, now=tz_now())
    except OrderRejected as exc:
        raise HTTPException(400, str(exc))
    broadcast(portfolio_payload())
    return {"order_id": oid, "order": dict(broker.order(oid))}


@app.get("/api/orders")
def api_orders(status: str | None = None):
    return [dict(r) for r in broker.orders(status)]


@app.delete("/api/orders/{order_id}")
def api_cancel(order_id: int):
    try:
        broker.cancel(order_id, now=tz_now())
    except OrderRejected as exc:
        raise HTTPException(400, str(exc))
    broadcast(portfolio_payload())
    return {"ok": True}


@app.get("/api/portfolio")
def api_portfolio():
    return portfolio_payload()


@app.post("/api/reset")
def api_reset():
    broker.reset()
    broadcast(portfolio_payload())
    return {"ok": True}


@app.get("/api/status")
def api_status():
    return dict(feed_status)


# ---------------------------------------------------------------- WS · 정적

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "feed", **feed_status})
    await ws.send_json(portfolio_payload())
    try:
        while True:
            await ws.receive_text()      # 브라우저는 아무것도 안 보낸다
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")),
          name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))
