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

from paper.ticks import is_valid_price

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

    # ------------------------------------------------------ 묶인 자금·수량

    def reserved(self) -> int:
        """
        미체결 매수 지정가가 묶어 둔 금액. 없으면 같은 돈으로 여러 번 주문된다.

        수수료까지 묶어야 한다. 대금만 묶으면 잔고를 정확히 소진하는 주문이
        검증을 통과한 뒤 체결 시점에 수수료만큼 마이너스로 떨어진다.
        """
        rows = self.conn.execute(
            "SELECT limit_price * (qty - filled_qty) AS gross FROM orders "
            "WHERE status = 'pending' AND side = 'buy' AND limit_price IS NOT NULL"
        ).fetchall()
        return sum(int(r["gross"]) + round(int(r["gross"]) * FEE_RATE) for r in rows)

    def available_cash(self) -> int:
        return self.cash() - self.reserved()

    def reserved_qty(self, symbol: str) -> int:
        """미체결 매도가 묶어 둔 수량. 같은 주식을 두 번 팔지 못하게 한다."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(qty - filled_qty), 0) FROM orders "
            "WHERE status = 'pending' AND side = 'sell' AND symbol = ?",
            (symbol,)).fetchone()
        return int(row[0])

    def available_qty(self, symbol: str) -> int:
        held = self.positions().get(symbol)
        return (held.qty if held else 0) - self.reserved_qty(symbol)

    # ---------------------------------------------------------- 주문 접수

    def place(self, symbol: str, side: str, type: str, qty: int,
              limit_price: int | None = None, *,
              book: Book, session: Session, now: datetime) -> int:
        """
        주문을 접수하고 주문 id를 돌려준다.

        시장가는 여기서 호가를 훑어 즉시 체결하고 종료 상태로 끝난다.
        대기하지 않으므로 pending을 거치지 않는다.
        """
        self._validate(symbol, side, type, qty, limit_price, book, session, now)

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

    def _validate(self, symbol, side, type, qty, limit_price,
                  book: Book, session: Session, now: datetime) -> None:
        """
        받을 수 없는 주문을 여기서 전부 거른다. 메시지는 그대로 화면에 뜬다.

        검증을 place 안에 흩어 두지 않고 한곳에 모으는 이유는, 주문이 DB에
        들어간 뒤에 거부되면 주문번호만 남고 아무 일도 일어나지 않은 유령
        주문이 주문장에 쌓이기 때문이다.
        """
        if qty <= 0:
            raise OrderRejected("수량은 1주 이상이어야 합니다.")
        if side not in ("buy", "sell"):
            raise OrderRejected(f"알 수 없는 주문 방향입니다: {side}")
        if type not in ("market", "limit"):
            raise OrderRejected(f"알 수 없는 주문 유형입니다: {type}")

        if not session.is_open(now):
            raise OrderRejected(
                "정규장(09:00~15:30)에만 주문할 수 있습니다. "
                "시간외단일가는 지원하지 않습니다.")

        if type == "limit":
            if limit_price is None:
                raise OrderRejected("지정가 주문에는 가격이 필요합니다.")
            if not is_valid_price(limit_price):
                raise OrderRejected(
                    f"{limit_price:,}원은 호가단위에 맞지 않습니다.")

        if side == "buy":
            # 어느 쪽이든 수수료를 포함해야 체결 뒤 잔고가 음수로 떨어지지 않는다.
            # 시장가는 지정가가 없으므로 호가를 훑어 실제로 들 돈을 계산한다.
            if type == "limit":
                gross = limit_price * qty
                need = gross + round(gross * FEE_RATE)
            else:
                need = self._sweep_cost(book, qty)
            if need > self.available_cash():
                raise OrderRejected(
                    f"주문가능현금이 부족합니다. "
                    f"필요 {need:,}원 / 가능 {self.available_cash():,}원")
        else:
            if qty > self.available_qty(symbol):
                raise OrderRejected(
                    f"보유수량이 부족합니다. "
                    f"주문 {qty}주 / 가능 {self.available_qty(symbol)}주")

    def _sweep_cost(self, book: Book, qty: int) -> int:
        """
        시장가 매수가 호가를 훑을 때 실제로 나갈 금액(수수료 포함).

        수수료를 호가 단마다 반올림한다. `_record_fill`이 체결 건마다 따로
        반올림하므로, 여기서 총액에 한 번만 걸면 '반올림들의 합'과 '합의
        반올림'이 달라져 검증이 통과시킨 주문이 잔고를 1원씩 넘어선다.
        """
        remaining, cost = qty, 0
        for level in book.asks:
            if remaining <= 0:
                break
            take = min(remaining, level.volume)
            gross = take * level.price
            cost += gross + round(gross * FEE_RATE)
            remaining -= take
        return cost

    # ------------------------------------------------------ 취소·만료·리셋

    def cancel(self, order_id: int, now: datetime) -> None:
        row = self.order(order_id)
        if row is None:
            raise OrderRejected(f"없는 주문입니다: {order_id}")
        if row["status"] != "pending":
            raise OrderRejected(
                f"이미 종료된 주문은 취소할 수 없습니다 (상태: {row['status']}).")
        self.conn.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (now.isoformat(), order_id))
        self.conn.commit()

    def expire_all(self, now: datetime) -> list[int]:
        """장 마감 시 미체결 주문을 전부 만료시킨다. 만료된 주문 id 목록을 돌려준다."""
        ids = [r["id"] for r in self.open_orders()]
        if ids:
            self.conn.executemany(
                "UPDATE orders SET status = 'expired', updated_at = ? WHERE id = ?",
                [(now.isoformat(), i) for i in ids])
            self.conn.commit()
        return ids

    def reset(self, initial_cash: int | None = None) -> None:
        """주문·체결을 전부 지우고 초기자본으로 되돌린다. 관심종목은 남긴다."""
        cash = initial_cash if initial_cash is not None else self.initial_cash()
        self.conn.execute("DELETE FROM fills")
        self.conn.execute("DELETE FROM orders")
        self.conn.execute("UPDATE account SET initial_cash = ? WHERE id = 1", (cash,))
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
