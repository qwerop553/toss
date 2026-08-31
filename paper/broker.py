"""
모의투자 체결 엔진과 포트폴리오.

이 파일은 네트워크를 모른다. 입력은 '호가 스냅샷(Book)'과 '체결 프린트'라는
평범한 값이고 출력은 체결 기록이다. 그래서 테스트가 가짜 데이터만으로 된다.

상태를 어떻게 들고 있나:
  보유수량·평균단가·현금을 따로 저장하지 않고 전부 fills에서 파생한다.
  테이블로 들고 있으면 체결이 날 때마다 두 곳을 맞춰야 하고, 어긋나면 잔고가
  조용히 틀린다. 거래 수가 수백 건 수준이라 매번 훑어도 비용이 없다.

  ponytail: 체결이 수만 건으로 늘면 매 조회마다 전량 훑는 게 부담이 된다.
  그때는 날짜별 스냅샷을 캐시한다 (results.py가 같은 방식을 쓴다).
"""
from dataclasses import dataclass
from datetime import datetime
import sqlite3

FEE_RATE = 0.00015    # 수수료. 매수·매도 공통
TAX_RATE = 0.0020     # 거래세. 매도에만 붙는다
DEFAULT_CASH = 10_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    initial_cash INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,
    type        TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    limit_price INTEGER,
    status      TEXT NOT NULL,
    filled_qty  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    symbol   TEXT NOT NULL,
    side     TEXT NOT NULL,
    qty      INTEGER NOT NULL,
    price    INTEGER NOT NULL,
    fee      INTEGER NOT NULL,
    tax      INTEGER NOT NULL,
    at       TEXT NOT NULL
);
"""


class OrderRejected(Exception):
    """주문을 받을 수 없는 이유. 메시지는 그대로 사용자에게 보여준다."""


@dataclass(frozen=True)
class Level:
    price: int
    volume: int


@dataclass(frozen=True)
class Book:
    """호가 스냅샷. asks는 낮은 가격부터, bids는 높은 가격부터 정렬돼 있다."""
    symbol: str
    asks: list[Level]
    bids: list[Level]


@dataclass(frozen=True)
class Session:
    """오늘의 정규장 구간. 네트워크를 모르는 broker에 장 시간을 값으로 넣는다."""
    start: datetime
    end: datetime

    def is_open(self, now: datetime) -> bool:
        return self.start <= now < self.end


@dataclass(frozen=True)
class Fill:
    order_id: int
    symbol: str
    side: str
    qty: int
    price: int
    fee: int
    tax: int
    at: str


@dataclass(frozen=True)
class Position:
    qty: int
    avg_cost: float


class Broker:
    def __init__(self, db_path: str, initial_cash: int = DEFAULT_CASH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO account (id, initial_cash, created_at) "
            "VALUES (1, ?, ?)", (initial_cash, datetime.now().isoformat()))
        self.conn.commit()

    # ---------------------------------------------------------- 파생 상태

    def initial_cash(self) -> int:
        return int(self.conn.execute(
            "SELECT initial_cash FROM account WHERE id = 1").fetchone()[0])

    def _fills(self) -> list[sqlite3.Row]:
        """시간순 체결 기록. 파생 계산은 전부 이걸 한 번 훑어서 한다."""
        return self.conn.execute(
            "SELECT * FROM fills ORDER BY id").fetchall()

    def cash(self) -> int:
        total = self.initial_cash()
        for f in self._fills():
            gross = f["qty"] * f["price"]
            if f["side"] == "buy":
                total -= gross + f["fee"]
            else:
                total += gross - f["fee"] - f["tax"]
        return total

    def positions(self) -> dict[str, Position]:
        """
        종목별 보유수량과 평균단가.

        평균단가는 총평균법이고 수수료를 포함한다 (실제 증권앱의 '매입단가'와
        같은 기준). 매도는 평균단가를 바꾸지 않고 수량만 줄인다.
        """
        qty: dict[str, int] = {}
        cost: dict[str, float] = {}
        for f in self._fills():
            s = f["symbol"]
            if f["side"] == "buy":
                cost[s] = cost.get(s, 0.0) + f["qty"] * f["price"] + f["fee"]
                qty[s] = qty.get(s, 0) + f["qty"]
            else:
                held = qty.get(s, 0)
                avg = cost.get(s, 0.0) / held if held else 0.0
                cost[s] = cost.get(s, 0.0) - avg * f["qty"]
                qty[s] = held - f["qty"]

        out = {}
        for s, q in qty.items():
            if q > 0:
                out[s] = Position(qty=q, avg_cost=cost[s] / q)
        return out

    # ---------------------------------------------------------- 체결 기록

    def _record_fill(self, order_id: int, symbol: str, side: str,
                     qty: int, price: int, at: str) -> Fill:
        """
        체결 한 건을 기록한다. 수수료·세금은 체결 건마다 따로 반올림한다
        (실제 증권사도 체결 단위로 뗀다).
        """
        gross = qty * price
        fee = round(gross * FEE_RATE)
        tax = round(gross * TAX_RATE) if side == "sell" else 0
        cur = self.conn.execute(
            "INSERT INTO fills (order_id, symbol, side, qty, price, fee, tax, at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (order_id, symbol, side, qty, price, fee, tax, at))
        self.conn.execute(
            "UPDATE orders SET filled_qty = filled_qty + ?, updated_at = ? "
            "WHERE id = ?", (qty, at, order_id))
        self.conn.commit()
        return Fill(order_id, symbol, side, qty, price, fee, tax, at)

    # ---------------------------------------------------------- 주문 조회

    def order(self, order_id: int) -> sqlite3.Row:
        return self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def orders(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY id DESC",
                (status,)).fetchall()
        return self.conn.execute(
            "SELECT * FROM orders ORDER BY id DESC").fetchall()

    def open_orders(self) -> list[sqlite3.Row]:
        return self.orders("pending")

    def fills_of(self, order_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM fills WHERE order_id = ? ORDER BY id",
            (order_id,)).fetchall()

    # ---------------------------------------------------------- 주문 접수

    def place(self, symbol: str, side: str, type: str, qty: int,
              limit_price: int | None = None, *,
              book: Book, session: Session, now: datetime) -> int:
        """
        주문을 접수하고 주문 id를 돌려준다.

        시장가는 여기서 호가를 훑어 즉시 체결하고 종료 상태로 끝난다.
        대기하지 않으므로 pending을 거치지 않는다.
        """
        at = now.isoformat()
        cur = self.conn.execute(
            "INSERT INTO orders (symbol, side, type, qty, limit_price, status, "
            "                    filled_qty, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'pending',0,?,?)",
            (symbol, side, type, qty, limit_price, at, at))
        order_id = cur.lastrowid
        self.conn.commit()

        if type == "market":
            self._sweep(order_id, symbol, side, qty, book, at, limit=None)
            self._settle(order_id, at)
        else:
            # 지정가: 지금 이미 유리하면 즉시 체결한다. 실제 거래소도 그렇다.
            # 다 못 채운 잔량은 pending으로 남아 체결 프린트를 기다린다.
            filled = self._sweep(order_id, symbol, side, qty, book, at, limit=limit_price)
            if filled >= qty:
                self._settle(order_id, at)

        return order_id

    def _sweep(self, order_id: int, symbol: str, side: str, qty: int,
               book: Book, at: str, limit: int | None) -> int:
        """
        호가를 위에서부터 훑어 체결한다. 체결된 수량을 돌려준다.

        limit이 주어지면 그 가격보다 불리한 호가에서 멈춘다 (지정가의 즉시체결).
        limit이 None이면 잔량이 다 찰 때까지, 또는 호가가 소진될 때까지 훑는다.
        """
        levels = book.asks if side == "buy" else book.bids
        remaining = qty
        for level in levels:
            if remaining <= 0:
                break
            if limit is not None:
                if side == "buy" and level.price > limit:
                    break
                if side == "sell" and level.price < limit:
                    break
            take = min(remaining, level.volume)
            if take <= 0:
                continue
            self._record_fill(order_id, symbol, side, take, level.price, at)
            remaining -= take
        return qty - remaining

    def _settle(self, order_id: int, at: str) -> None:
        """
        더 이상 체결될 수 없는 주문의 최종 상태를 정한다.

        partial은 종료 상태다. 부분체결된 지정가가 아직 대기 중인 경우는
        pending으로 남고 filled_qty만 0보다 크다 — 이 둘을 같은 status로
        뭉치면 주문장에서 '아직 체결될 수 있는 주문'을 구분할 수 없다.
        """
        row = self.order(order_id)
        status = "filled" if row["filled_qty"] >= row["qty"] else "partial"
        if row["filled_qty"] == 0:
            status = "cancelled"
        self.conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                          (status, at, order_id))
        self.conn.commit()

    # ------------------------------------------------------ 시장 이벤트

    def on_trade(self, symbol: str, price: int, volume: int,
                 now: datetime) -> list[Fill]:
        """
        체결 프린트 하나를 받아 대기 중인 지정가를 판정한다.

        매수는 프린트 가격이 지정가 이하일 때, 매도는 이상일 때 체결된다.
        체결가는 내 지정가가 아니라 실제 프린트된 가격이다 — 유리한 쪽으로
        체결되는 실제 규칙과 맞다.

        ponytail: 큐 포지션을 모델링하지 않는다. 내 앞에 줄 서 있던 물량을
        무시하므로 실제보다 잘 체결된다. 호가 잔량의 변화를 추적하면 개선할
        수 있지만 이 사이트의 목적을 넘는다.
        """
        at = now.isoformat()
        out: list[Fill] = []
        remaining_print = volume

        rows = self.conn.execute(
            "SELECT * FROM orders WHERE status = 'pending' AND symbol = ? "
            "ORDER BY id", (symbol,)).fetchall()

        for row in rows:
            if remaining_print <= 0:
                break
            limit = row["limit_price"]
            if row["side"] == "buy" and price > limit:
                continue
            if row["side"] == "sell" and price < limit:
                continue

            want = row["qty"] - row["filled_qty"]
            take = min(want, remaining_print)
            if take <= 0:
                continue

            out.append(self._record_fill(row["id"], symbol, row["side"],
                                         take, price, at))
            remaining_print -= take

            if row["filled_qty"] + take >= row["qty"]:
                self.conn.execute(
                    "UPDATE orders SET status = 'filled', updated_at = ? WHERE id = ?",
                    (at, row["id"]))
        self.conn.commit()
        return out
