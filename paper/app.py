"""
모의투자 웹서버.

    python -m uvicorn paper.app:app --reload

브라우저 → 이 서버 → 토스. 브라우저가 토스에 직접 붙지 못하는 이유는
paper/feed.py의 docstring에 있다.
"""
import asyncio
import os
import threading
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import scrap
from paper import toss
from paper.broker import Book, Broker, OrderRejected
from paper.feed import MAX_SYMBOLS, Feed

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(os.path.dirname(BASE), "paper.db")
# scrap의 기본값("market_data.db")은 상대경로다. 서버를 다른 작업 디렉터리에서
# 띄우면 기존 DB를 못 찾고 빈 DB를 새로 만들어 버리므로 절대경로로 고정한다.
MARKET_DB_PATH = os.path.join(os.path.dirname(BASE), "market_data.db")

app = FastAPI(title="모의투자")
broker = Broker(DB_PATH)

# ponytail: 브로커 전체를 감싸는 굵은 락 하나. api_place 같은 동기 핸들러는
# 워커 스레드에서 돌고 on_trade는 이벤트 루프에서 도는데, 둘 다 같은 SQLite
# 연결과 같은 주문 행을 만진다. 연산이 밀리초라 단일 사용자 도구에서는
# 충분하다. 종목별 락은 처리량이 문제가 될 때 생각한다.
broker_lock = threading.Lock()

# 최신 호가 스냅샷. 시장가 주문이 훑을 대상이고, REST를 매번 부르지 않으려고
# 웹소켓으로 들어온 값을 여기에 덮어 쓴다.
books: dict[str, Book] = {}
book_fetched_at: dict[str, float] = {}
BOOK_MAX_AGE = 3.0  # 초. REST로 받은 스냅샷을 이보다 오래 캐시하지 않는다.
last_price: dict[str, int] = {}
session_cache: dict = {"date": None, "session": None}
feed_status = {"status": "starting", "message": ""}

clients: set[WebSocket] = set()
loop: asyncio.AbstractEventLoop | None = None
# CPython은 asyncio.Task를 약한 참조로만 들고 있어서, 변수에 안 잡아 두면
# GC가 실행 중인 태스크를 수거해 조용히 멈출 수 있다. 여기 붙잡아 둔다.
background_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """asyncio.create_task + 참조 보관을 한 번에. 태스크를 흘리지 않는다."""
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


# ---------------------------------------------------------------- 브로드캐스트

def broadcast(payload: dict) -> None:
    """
    브라우저 전부에 밀어 넣는다.

    feed 콜백(on_trade 등)은 웹소켓 수신 루프 안, 즉 이벤트 루프 위에서
    불린다 — 거기서는 그냥 스케줄만 하면 된다. 반대로 REST 핸들러(api_place
    등)는 평범한 def라 FastAPI가 스레드풀에서 돌리므로 이벤트 루프 밖이다.
    call_soon_threadsafe는 어느 쪽에서 불러도 안전해서 양쪽 호출자를 하나로
    처리할 수 있다.
    """
    if loop is None:
        return
    loop.call_soon_threadsafe(spawn, _fanout(payload))


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
    with broker_lock:
        fills = broker.on_trade(symbol, data["price"], data["volume"], tz_now())
    for f in fills:
        broadcast({"type": "fill", "order_id": f.order_id, "symbol": f.symbol,
                   "side": f.side, "qty": f.qty, "price": f.price})
    if fills:
        broadcast(portfolio_payload())


def on_orderbook(symbol: str, data: dict) -> None:
    books[symbol] = Book(symbol=symbol, asks=data["asks"], bids=data["bids"])
    book_fetched_at[symbol] = time.monotonic()
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
    지금 시각. 항상 tz-aware다.

    여기서 절대 네트워크를 타면 안 된다. 이 함수는 체결 프린트마다 불리는
    자리이고, 그 호출이 실패하면 예외가 웹소켓 루프를 뚫고 나가 연결이
    끊긴 뒤 재접속할 때마다 같은 자리에서 다시 죽는다. 로컬 타임존
    오프셋이면 충분하다 — 어차피 장운영 타임존과 같은 KST다.
    """
    return datetime.now().astimezone()


def book_of(symbol: str) -> Book:
    """
    시장가가 훑을 호가. 웹소켓 스냅샷이 있으면 그걸 쓰고, 없거나 오래됐으면
    REST로 새로 받는다.

    구독 직후에는 스냅샷이 오지 않으므로(다음 갱신부터 푸시된다) 이 fallback이
    없으면 종목을 막 추가한 직후의 시장가 주문이 빈 호가를 훑게 된다. 반대로
    한 번 받은 뒤 영원히 캐시하면(웹소켓이 끊기는 등으로 갱신이 멈춘 경우)
    시장가 주문이 오래된 호가를 훑어 가격을 지어내게 된다 — BOOK_MAX_AGE보다
    오래된 스냅샷은 버리고 다시 받는다.
    """
    fetched = book_fetched_at.get(symbol)
    if symbol not in books or fetched is None or time.monotonic() - fetched > BOOK_MAX_AGE:
        books[symbol] = toss.get_orderbook(symbol)
        book_fetched_at[symbol] = time.monotonic()
    return books[symbol]


def portfolio_payload() -> dict:
    positions = []
    for symbol, pos in broker.positions().items():
        price = last_price.get(symbol)
        # 가격을 아직 모르는 것과 가격이 0원인 것은 다르다. or 0으로 뭉치면
        # 관심종목에서 빠졌거나 startup에서 get_prices가 실패한 종목이
        # pnl_pct: -100.0(전액 손실)으로 찍힌다 — 실제로는 '모름'이다.
        if price is None:
            positions.append({
                "symbol": symbol, "qty": pos.qty, "avg_cost": round(pos.avg_cost),
                "price": None, "value": None, "pnl": None, "pnl_pct": None,
            })
            continue
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
    spawn(feed.run())
    spawn(expire_at_close())


async def expire_at_close() -> None:
    """
    장 마감에 미체결 주문을 만료시킨다.

    실제 주문은 당일 만료다. 이걸 안 하면 어제 걸어 둔 지정가가 오늘 시세에
    체결되는데, 그건 실제로는 일어나지 않는 일이라 잔고가 거짓이 된다.

    ponytail: 1분마다 시각만 확인하는 폴링이다. 정확한 시각에 깨우려면 타이머를
    장 구간에 맞춰 재설정해야 하는데, 서버가 며칠씩 떠 있는 물건이 아니라서
    그만한 정밀도가 필요 없다.

    루프 본문 전체를 try/except로 감싼다. current_session()이 하루에 한 번
    toss.get_session()을 다시 부르는데(날짜가 바뀌면), 그때 TossError가 나면
    가드 없이는 예외가 이 무한루프를 뚫고 나가 태스크가 조용히 죽는다 — 참조를
    안 잡고 있었으면 "Task exception was never retrieved"만 로그에 남고,
    그 뒤로 이 프로세스가 떠 있는 동안 미체결 주문이 다시는 만료되지 않는다.
    """
    while True:
        await asyncio.sleep(60)
        try:
            session = current_session()
            if session is None:
                continue
            now = tz_now()
            if now >= session.end:
                with broker_lock:
                    expired = broker.expire_all(now=now)
                if expired:
                    broadcast({"type": "expired", "order_ids": expired})
                    broadcast(portfolio_payload())
        except Exception as exc:
            on_status("error", f"주문 만료 확인 실패: {exc}")
            continue


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
def api_candles(symbol: str, interval: str = "1m", response: Response = None):
    """차트용 분봉. market_data.db를 최신까지 당긴 뒤 읽는다(증분이라 안전하다)."""
    try:
        scrap.update_candles(symbol, interval, db_path=MARKET_DB_PATH)
    except Exception as exc:
        # on_status를 부르면 안 된다 — 그건 실시간 시세 웹소켓의 상태고, 캔들
        # 수집은 별개의 REST 호출이다. 여기서 feed 상태를 error로 덮으면 화면은
        # 실시간 피드가 끊긴 것처럼 보이는데 실제로는 멀쩡하고, 진짜 feed
        # 전환이 올 때까지 그 거짓 상태가 남는다. 실패는 응답 헤더에만 담고
        # 본문은 그대로 배열을 돌려준다 — Task 9 프론트가 이 배열을 바로
        # candles.map()으로 소비하므로 형태를 바꾸면 거기가 깨진다.
        # 헤더 값은 latin-1로만 인코딩되므로 한글을 못 넣는다. 상세 메시지는
        # 서버 콘솔에만 남긴다.
        print(f"[api_candles] 캔들 수집 실패 ({symbol}/{interval}): {exc}")
        if response is not None:
            response.headers["X-Candles-Error"] = "fetch-failed"
    df = scrap.load_candles(symbol, interval, db_path=MARKET_DB_PATH)
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
    # book_of()는 캐시가 오래됐으면 REST를 부를 수 있다 — 락 밖에서 먼저
    # 받아 둔다. 락 안에서 네트워크를 타면 그동안 웹소켓 쪽의 on_trade가
    # 통째로 막힌다.
    book = book_of(body.symbol)
    try:
        with broker_lock:
            oid = broker.place(body.symbol, body.side, body.type, body.qty,
                               body.limit_price, book=book,
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
        with broker_lock:
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
    with broker_lock:
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
