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
