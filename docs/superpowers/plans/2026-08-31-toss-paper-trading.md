# 토스 연동 모의투자 웹사이트 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 토스증권 Open API의 실시간 시세를 받아 브라우저에서 손으로 주문을 넣고, 체결·잔고·손익을 가짜 돈으로 추적하는 로컬 웹사이트를 만든다.

**Architecture:** FastAPI 단일 프로세스가 토스 웹소켓에 업스트림 연결 **하나**를 물고 브라우저에 팬아웃한다. 체결 엔진(`broker.py`)은 네트워크를 전혀 모르는 순수 로직이라 가짜 데이터만으로 전부 테스트된다. 상태는 `paper.db`(SQLite)의 `fills`에서 파생한다.

**Tech Stack:** Python 3.14, FastAPI, uvicorn, websockets, SQLite, 바닐라 JS (빌드 없음)

**Spec:** `docs/superpowers/specs/2026-08-31-toss-paper-trading-design.md`

## Global Constraints

- **주문 API를 절대 호출하지 않는다.** 코드 어디에도 `/api/v1/orders`, `/api/v1/accounts` 문자열이 등장하면 안 된다. 토스에는 모의투자 sandbox가 없어서 그 경로는 실제 돈이 나간다.
- 주석·docstring·커밋 메시지는 **한국어**로 쓴다. 기존 리포 관례다.
- 토스 API의 모든 숫자 필드는 **문자열**로 온다. 파싱 시점에 `int`로 바꾼다. 가격·수량·수수료·세금은 전부 원 단위 `int`이고, 부동소수로 다루지 않는다. 평균단가만 `float`이다.
- 수수료 `FEE_RATE = 0.00015`(매수·매도 공통), 거래세 `TAX_RATE = 0.0020`(매도만). 반올림은 체결 건마다 따로 한다.
- 정규장은 09:00–15:30. 그 밖의 시간에는 주문을 거부한다.
- 웹소켓 한도: 동시 연결 2개/계정, 연결당 구독 100건, 선언 5회/초. `trade:kr`+`orderbook:kr`이 종목당 2건이므로 관심종목 상한은 **50종목**이다.
- 새 의존성은 `fastapi`, `uvicorn`, `websockets` 셋뿐이다. 프론트엔드 빌드 파이프라인을 만들지 않는다.
- 리포에 테스트 프레임워크가 없다. 테스트는 `assert` 기반이고 `python paper/test_*.py`로 직접 돌린다.

## File Structure

| 파일 | 책임 |
|---|---|
| `paper/__init__.py` | 빈 파일 (패키지 선언) |
| `paper/ticks.py` | KRX 가격대별 호가단위 표. 순수 함수, 의존성 없음 |
| `paper/broker.py` | 체결 엔진 + 포트폴리오 파생 + `paper.db`. 네트워크 없음 |
| `paper/test_broker.py` | 체결 엔진 검증 |
| `paper/toss.py` | 읽기 전용 REST 래퍼 |
| `paper/feed.py` | 업스트림 WS: 구독 선언, keepalive, 재접속 |
| `paper/test_feed.py` | 구독 페이로드 생성·이벤트 파싱 검증 (네트워크 없음) |
| `paper/app.py` | FastAPI 라우트 + `/ws` 팬아웃 + 배선 |
| `paper/static/index.html` | 화면 한 장 |
| `scrap.py` | `_get_access_token` → `get_access_token` 승격 |

---

### Task 1: 호가단위 표 (`paper/ticks.py`)

가장 아래 계층이다. 다른 아무것도 필요로 하지 않고, `broker.py`가 이걸 쓴다.

**Files:**
- Create: `paper/__init__.py`, `paper/ticks.py`
- Test: `paper/test_ticks.py`

**Interfaces:**
- Consumes: 없음
- Produces: `tick_size(price: int) -> int`, `is_valid_price(price: int) -> bool`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_ticks.py`:

```python
"""호가단위 표 검증. `python paper/test_ticks.py`로 돌린다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.ticks import is_valid_price, tick_size


def test_구간별_호가단위():
    # KRX 국내주식 호가단위 (2023-01-25 개정 기준)
    assert tick_size(1_500) == 1
    assert tick_size(4_999) == 1
    assert tick_size(5_000) == 5
    assert tick_size(19_999) == 5
    assert tick_size(20_000) == 10
    assert tick_size(49_999) == 10
    assert tick_size(50_000) == 50
    assert tick_size(199_999) == 50
    assert tick_size(200_000) == 100
    assert tick_size(499_999) == 100
    assert tick_size(500_000) == 500
    assert tick_size(1_000_000) == 500


def test_경계값이_아래_구간이_아니라_위_구간에_속한다():
    # 5,000원 정확히는 1원 단위가 아니라 5원 단위다. 경계를 반대로 잡으면
    # 4,999원짜리 주문이 통과하고 5,000원짜리가 막히는 식으로 뒤집힌다.
    assert tick_size(4_999) == 1
    assert tick_size(5_000) == 5


def test_유효_지정가_판정():
    assert is_valid_price(258_500)        # 20만원대 -> 100원 단위
    assert not is_valid_price(258_550)
    assert not is_valid_price(258_501)
    assert is_valid_price(4_999)          # 5천원 미만 -> 1원 단위
    assert is_valid_price(7_005)          # 5천~2만 -> 5원 단위
    assert not is_valid_price(7_003)


def test_0원_이하는_유효하지_않다():
    assert not is_valid_price(0)
    assert not is_valid_price(-100)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_ticks 통과")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_ticks.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper.ticks'`

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/__init__.py`는 빈 파일로 만든다.

`paper/ticks.py`:

```python
"""
KRX 국내주식 호가단위.

왜 필요한가:
  258,500원짜리 종목의 호가단위는 100원이라 258,550원 같은 지정가는 실제로
  낼 수 없다. 막지 않으면 현실에 존재하지 않는 주문이 주문장에 들어가고,
  그 주문이 체결되는 순간 모의투자 전체가 거짓말이 된다.

표는 2023-01-25 개정된 현행 기준이다. 개정되면 아래 표만 고치면 된다.
"""

# (하한가, 호가단위). 가격이 하한가 '이상'이면 그 구간이다. 큰 값부터 훑는다.
_TIERS = [
    (500_000, 500),
    (200_000, 100),
    (50_000, 50),
    (20_000, 10),
    (5_000, 5),
    (0, 1),
]


def tick_size(price: int) -> int:
    """price가 속한 구간의 호가단위를 돌려준다."""
    for floor, tick in _TIERS:
        if price >= floor:
            return tick
    return 1  # 도달하지 않는다. _TIERS의 마지막이 0이라서.


def is_valid_price(price: int) -> bool:
    """실제로 낼 수 있는 지정가인지."""
    if price <= 0:
        return False
    return price % tick_size(price) == 0
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_ticks.py`
Expected: PASS — `test_ticks 통과`

- [ ] **Step 5: 커밋**

```bash
git add paper/__init__.py paper/ticks.py paper/test_ticks.py
git commit -m "feat(paper): KRX 호가단위 표"
```

---

### Task 2: 포트폴리오 파생 (`paper/broker.py` 1/4)

`fills`에서 현금·보유·평균단가를 파생하는 부분만 먼저 만든다. 체결 로직은 아직 없다. 이 단계가 끝나면 "손으로 넣은 체결 기록으로 잔고가 맞게 나오는가"가 검증된다.

**Files:**
- Create: `paper/broker.py`
- Test: `paper/test_broker.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `FEE_RATE = 0.00015`, `TAX_RATE = 0.0020`, `DEFAULT_CASH = 10_000_000`
  - `Level(price: int, volume: int)`, `Book(symbol: str, asks: list[Level], bids: list[Level])`, `Session(start: datetime, end: datetime)` — 전부 frozen dataclass
  - `OrderRejected(Exception)`
  - `Broker(db_path: str, initial_cash: int = DEFAULT_CASH)`
  - `Broker.cash() -> int`
  - `Broker.positions() -> dict[str, Position]` where `Position(qty: int, avg_cost: float)`
  - `Broker._record_fill(order_id, symbol, side, qty, price, at) -> Fill` (내부용, 테스트가 직접 부른다)
  - `Fill(order_id, symbol, side, qty, price, fee, tax, at)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_broker.py`:

```python
"""
체결 엔진 검증. `python paper/test_broker.py`로 돌린다.

broker는 네트워크를 모르므로 가짜 호가·체결 데이터만으로 전부 검증된다.
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.broker import Book, Broker, Level, Session

# 정규장 09:00~15:30. 테스트는 전부 이 안의 시각을 쓴다.
DAY = datetime(2026, 8, 31, 10, 0, 0)
SESSION = Session(start=datetime(2026, 8, 31, 9, 0), end=datetime(2026, 8, 31, 15, 30))


def new_broker(cash=10_000_000):
    """테스트마다 빈 DB를 새로 만든다. 파일은 임시 디렉터리에 둔다."""
    path = os.path.join(tempfile.mkdtemp(), "paper.db")
    return Broker(path, initial_cash=cash)


def book(symbol="005930", asks=((259_000, 100), (259_500, 50)),
         bids=((258_500, 80), (258_000, 40))):
    return Book(symbol=symbol,
                asks=[Level(p, v) for p, v in asks],
                bids=[Level(p, v) for p, v in bids])


def test_초기_현금은_초기자본이다():
    b = new_broker(5_000_000)
    assert b.cash() == 5_000_000
    assert b.positions() == {}


def test_매수_체결이_현금과_보유에_반영된다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="2026-08-31T10:00:00")
    # 수수료 = 1,000,000 * 0.00015 = 150원
    assert b.cash() == 10_000_000 - 1_000_000 - 150
    pos = b.positions()["005930"]
    assert pos.qty == 10
    # 평균단가는 수수료를 포함한다 (실제 증권앱의 매입단가와 같은 기준)
    assert abs(pos.avg_cost - (1_000_000 + 150) / 10) < 1e-9


def test_매도_체결에_수수료와_거래세가_둘_다_붙는다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="2026-08-31T10:00:00")
    b._record_fill(2, "005930", "sell", qty=10, price=110_000, at="2026-08-31T10:01:00")
    # 매도 대금 1,100,000 / 수수료 165 / 거래세 2,200
    expected = 10_000_000 - 1_000_000 - 150 + 1_100_000 - 165 - 2_200
    assert b.cash() == expected
    assert "005930" not in b.positions()   # 전량 매도하면 보유에서 빠진다


def test_평균단가는_총평균법이고_매도해도_변하지_않는다():
    b = new_broker()
    b._record_fill(1, "005930", "buy", qty=10, price=100_000, at="t1")
    b._record_fill(2, "005930", "buy", qty=10, price=120_000, at="t2")
    avg_before = b.positions()["005930"].avg_cost
    # (1,000,000+150 + 1,200,000+180) / 20 = 110,016.5
    assert abs(avg_before - 110_016.5) < 1e-6

    b._record_fill(3, "005930", "sell", qty=5, price=130_000, at="t3")
    pos = b.positions()["005930"]
    assert pos.qty == 15
    assert abs(pos.avg_cost - avg_before) < 1e-6   # 매도는 평균단가를 안 건드린다


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_broker 통과")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_broker.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper.broker'`

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/broker.py`:

```python
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
```

`.gitignore`에 한 줄 추가한다:

```
paper.db
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_broker.py`
Expected: PASS — 4개 테스트 통과 후 `test_broker 통과`

`_record_fill`이 `orders` 테이블을 UPDATE하는데 테스트에는 주문 행이 없다. SQLite는 없는 행을 UPDATE해도 에러를 내지 않으므로 그대로 통과한다.

- [ ] **Step 5: 커밋**

```bash
git add paper/broker.py paper/test_broker.py .gitignore
git commit -m "feat(paper): fills에서 현금·보유·평균단가를 파생"
```

---

### Task 3: 시장가 체결 (`paper/broker.py` 2/4)

**Files:**
- Modify: `paper/broker.py`
- Modify: `paper/test_broker.py`

**Interfaces:**
- Consumes: Task 2의 `Broker`, `Book`, `Level`, `Session`, `Fill`
- Produces:
  - `Broker.place(symbol, side, type, qty, limit_price=None, *, book: Book, session: Session, now: datetime) -> int` (주문 id)
  - `Broker.order(order_id) -> sqlite3.Row`
  - `Broker.fills_of(order_id) -> list[sqlite3.Row]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_broker.py`의 `if __name__` 블록 **위에** 아래를 추가한다:

```python
def test_시장가_매수가_호가를_다단으로_훑는다():
    b = new_broker()
    # 259,000에 100주, 259,500에 50주 있는 호가에 120주 시장가 매수
    oid = b.place("005930", "buy", "market", 120,
                  book=book(), session=SESSION, now=DAY)
    fills = b.fills_of(oid)
    assert len(fills) == 2
    assert (fills[0]["price"], fills[0]["qty"]) == (259_000, 100)
    assert (fills[1]["price"], fills[1]["qty"]) == (259_500, 20)
    assert b.order(oid)["status"] == "filled"
    assert b.positions()["005930"].qty == 120


def test_호가가_모자라면_채운_만큼만_체결하고_끝낸다():
    b = new_broker()
    # 호가 전체가 150주뿐인데 200주를 시장가로 산다
    oid = b.place("005930", "buy", "market", 200,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["filled_qty"] == 150
    # partial은 종료 상태다. 남은 50주는 대기하지 않는다.
    assert b.order(oid)["status"] == "partial"


def test_시장가_매도는_매수호가를_훑는다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=100, price=250_000, at="t0")
    oid = b.place("005930", "sell", "market", 100,
                  book=book(), session=SESSION, now=DAY)
    fills = b.fills_of(oid)
    assert (fills[0]["price"], fills[0]["qty"]) == (258_500, 80)
    assert (fills[1]["price"], fills[1]["qty"]) == (258_000, 20)
    assert b.order(oid)["status"] == "filled"
    assert "005930" not in b.positions()


def test_시장가는_pending을_거치지_않는다():
    b = new_broker()
    oid = b.place("005930", "buy", "market", 10,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "filled"
    assert b.open_orders() == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_broker.py`
Expected: FAIL — `AttributeError: 'Broker' object has no attribute 'place'`

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/broker.py`의 `Broker` 클래스에 아래를 추가한다:

```python
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
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_broker.py`
Expected: PASS — 8개 테스트 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add paper/broker.py paper/test_broker.py
git commit -m "feat(paper): 시장가 다단 체결"
```

---

### Task 4: 지정가 (`paper/broker.py` 3/4)

**Files:**
- Modify: `paper/broker.py`
- Modify: `paper/test_broker.py`

**Interfaces:**
- Consumes: Task 3의 `Broker.place`, `Broker._sweep`, `Broker._settle`
- Produces: `Broker.on_trade(symbol: str, price: int, volume: int, now: datetime) -> list[Fill]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_broker.py`의 `if __name__` 블록 위에 추가한다:

```python
def test_불리한_지정가는_pending으로_남는다():
    b = new_broker()
    # 매도1호가가 259,000인데 250,000에 사겠다고 걸어 둔다
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "pending"
    assert b.order(oid)["filled_qty"] == 0
    assert len(b.open_orders()) == 1


def test_이미_유리한_지정가는_즉시_체결된다():
    b = new_broker()
    # 매도1호가 259,000보다 높은 260,000에 사겠다면 지금 바로 체결된다
    oid = b.place("005930", "buy", "limit", 50, 260_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "filled"
    assert b.fills_of(oid)[0]["price"] == 259_000   # 내 지정가가 아니라 호가에 체결


def test_지정가가_체결_프린트로_채워진다():
    b = new_broker()
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    # 250,000 아래로 체결이 프린트되면 채워진다
    fills = b.on_trade("005930", price=249_500, volume=100, now=DAY)
    assert len(fills) == 1
    assert fills[0].qty == 10
    assert fills[0].price == 249_500      # 프린트 가격에 체결
    assert b.order(oid)["status"] == "filled"
    assert b.open_orders() == []


def test_지정가_부분체결은_pending으로_남는다():
    b = new_broker()
    oid = b.place("005930", "buy", "limit", 100, 250_000,
                  book=book(), session=SESSION, now=DAY)
    b.on_trade("005930", price=250_000, volume=30, now=DAY)
    row = b.order(oid)
    assert row["filled_qty"] == 30
    # 아직 더 체결될 수 있으므로 partial이 아니라 pending이다
    assert row["status"] == "pending"
    b.on_trade("005930", price=249_000, volume=70, now=DAY)
    assert b.order(oid)["status"] == "filled"


def test_불리한_프린트는_지정가를_건드리지_않는다():
    b = new_broker()
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)
    assert b.on_trade("005930", price=251_000, volume=100, now=DAY) == []


def test_매도_지정가는_프린트가_지정가_이상일_때_체결된다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=10, price=250_000, at="t0")
    oid = b.place("005930", "sell", "limit", 10, 270_000,
                  book=book(), session=SESSION, now=DAY)
    assert b.order(oid)["status"] == "pending"
    assert b.on_trade("005930", price=269_000, volume=100, now=DAY) == []
    fills = b.on_trade("005930", price=271_000, volume=100, now=DAY)
    assert len(fills) == 1 and fills[0].price == 271_000


def test_다른_종목의_프린트는_무시된다():
    b = new_broker()
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)
    assert b.on_trade("000660", price=100, volume=1000, now=DAY) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_broker.py`
Expected: FAIL — `test_이미_유리한_지정가는_즉시_체결된다`가 실패한다. `place`가 `type == "market"`만 처리하고 있어서 지정가가 체결되지 않는다.

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/broker.py`의 `place`에서 `if type == "market":` 블록을 아래로 바꾼다:

```python
        if type == "market":
            self._sweep(order_id, symbol, side, qty, book, at, limit=None)
            self._settle(order_id, at)
        else:
            # 지정가: 지금 이미 유리하면 즉시 체결한다. 실제 거래소도 그렇다.
            # 다 못 채운 잔량은 pending으로 남아 체결 프린트를 기다린다.
            filled = self._sweep(order_id, symbol, side, qty, book, at, limit=limit_price)
            if filled >= qty:
                self._settle(order_id, at)
```

같은 클래스에 아래를 추가한다:

```python
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
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_broker.py`
Expected: PASS — 15개 테스트 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add paper/broker.py paper/test_broker.py
git commit -m "feat(paper): 지정가 대기와 체결 프린트 판정"
```

---

### Task 5: 주문 검증·취소·만료 (`paper/broker.py` 4/4)

**Files:**
- Modify: `paper/broker.py`
- Modify: `paper/test_broker.py`

**Interfaces:**
- Consumes: Task 4의 전부, Task 1의 `is_valid_price`
- Produces:
  - `Broker.reserved() -> int`, `Broker.available_cash() -> int`
  - `Broker.cancel(order_id: int, now: datetime) -> None`
  - `Broker.expire_all(now: datetime) -> list[int]`
  - `Broker.reset(initial_cash: int | None = None) -> None`
  - `place()`가 위반 시 `OrderRejected`를 던진다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_broker.py` 상단 import에 `OrderRejected`를 추가한다:

```python
from paper.broker import Book, Broker, Level, OrderRejected, Session
```

`if __name__` 블록 위에 추가한다:

```python
def 거부되는가(fn) -> str:
    """OrderRejected가 나는지 확인하고 메시지를 돌려준다."""
    try:
        fn()
    except OrderRejected as exc:
        return str(exc)
    raise AssertionError("거부됐어야 하는데 통과했다")


def test_현금이_모자라면_거부된다():
    b = new_broker(cash=1_000_000)     # 100만원으로 259,000짜리 10주는 못 산다
    msg = 거부되는가(lambda: b.place("005930", "buy", "market", 10,
                                   book=book(), session=SESSION, now=DAY))
    assert "현금" in msg


def test_미체결_매수의_예약금액이_두번째_주문을_막는다():
    b = new_broker(cash=3_000_000)
    b.place("005930", "buy", "limit", 10, 250_000,
            book=book(), session=SESSION, now=DAY)   # 250만원 예약
    assert b.reserved() == 2_500_000
    assert b.available_cash() == 500_000
    msg = 거부되는가(lambda: b.place("005930", "buy", "limit", 10, 250_000,
                                   book=book(), session=SESSION, now=DAY))
    assert "현금" in msg


def test_취소하면_예약금액이_풀린다():
    b = new_broker(cash=3_000_000)
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    b.cancel(oid, now=DAY)
    assert b.order(oid)["status"] == "cancelled"
    assert b.reserved() == 0
    assert b.available_cash() == 3_000_000


def test_보유하지_않은_종목은_팔_수_없다():
    b = new_broker()
    msg = 거부되는가(lambda: b.place("005930", "sell", "market", 10,
                                   book=book(), session=SESSION, now=DAY))
    assert "보유" in msg


def test_미체결_매도도_보유수량을_묶는다():
    b = new_broker()
    b._record_fill(0, "005930", "buy", qty=10, price=250_000, at="t0")
    b.place("005930", "sell", "limit", 10, 300_000,
            book=book(), session=SESSION, now=DAY)
    # 10주 전부 매도 대기 중이므로 더 팔 수 없다
    msg = 거부되는가(lambda: b.place("005930", "sell", "market", 5,
                                   book=book(), session=SESSION, now=DAY))
    assert "보유" in msg


def test_호가단위에_맞지_않는_지정가는_거부된다():
    b = new_broker()
    msg = 거부되는가(lambda: b.place("005930", "buy", "limit", 1, 258_550,
                                   book=book(), session=SESSION, now=DAY))
    assert "호가단위" in msg


def test_장_시간_밖_주문은_거부된다():
    b = new_broker()
    저녁 = datetime(2026, 8, 31, 16, 0)
    msg = 거부되는가(lambda: b.place("005930", "buy", "market", 1,
                                   book=book(), session=SESSION, now=저녁))
    assert "정규장" in msg


def test_수량이_0_이하면_거부된다():
    b = new_broker()
    assert "수량" in 거부되는가(lambda: b.place("005930", "buy", "market", 0,
                                            book=book(), session=SESSION, now=DAY))


def test_만료가_미체결을_전부_정리한다():
    b = new_broker()
    oid = b.place("005930", "buy", "limit", 10, 250_000,
                  book=book(), session=SESSION, now=DAY)
    마감 = datetime(2026, 8, 31, 15, 30)
    assert b.expire_all(now=마감) == [oid]
    assert b.order(oid)["status"] == "expired"
    assert b.reserved() == 0


def test_리셋이_주문과_체결을_모두_지운다():
    b = new_broker()
    b.place("005930", "buy", "market", 10, book=book(), session=SESSION, now=DAY)
    b.reset()
    assert b.cash() == 10_000_000
    assert b.positions() == {}
    assert b.orders() == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_broker.py`
Expected: FAIL — `AssertionError: 거부됐어야 하는데 통과했다` (검증이 아직 없다)

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/broker.py` 상단 import에 추가한다:

```python
from paper.ticks import is_valid_price
```

`Broker`에 아래를 추가한다:

```python
    # ------------------------------------------------------ 묶인 자금·수량

    def reserved(self) -> int:
        """미체결 매수 지정가가 묶어 둔 금액. 없으면 같은 돈으로 여러 번 주문된다."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(limit_price * (qty - filled_qty)), 0) FROM orders "
            "WHERE status = 'pending' AND side = 'buy' AND limit_price IS NOT NULL"
        ).fetchone()
        return int(row[0])

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
```

`place`의 맨 앞(INSERT 전)에 검증을 넣는다:

```python
        self._validate(symbol, side, type, qty, limit_price, book, session, now)
```

그리고 `_validate`를 추가한다:

```python
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
            # 시장가는 지정가가 없으므로 호가를 훑어 실제로 들 돈을 계산한다.
            need = (limit_price * qty if type == "limit"
                    else self._sweep_cost(book, qty))
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
        """시장가 매수가 호가를 훑을 때 실제로 나갈 금액(수수료 포함)."""
        remaining, cost = qty, 0
        for level in book.asks:
            if remaining <= 0:
                break
            take = min(remaining, level.volume)
            cost += take * level.price
            remaining -= take
        return cost + round(cost * FEE_RATE)

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
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_broker.py`
Expected: PASS — 25개 테스트 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add paper/broker.py paper/test_broker.py
git commit -m "feat(paper): 주문 검증·취소·만료·리셋"
```

---

### Task 6: 읽기 전용 REST 래퍼 (`paper/toss.py`)

**Files:**
- Create: `paper/toss.py`
- Modify: `scrap.py:160` (`_get_access_token` → `get_access_token`), `scrap.py:33`, `scrap.py:112`

**Interfaces:**
- Consumes: Task 2의 `Book`, `Level`, `Session`
- Produces:
  - `get_prices(symbols: list[str]) -> dict[str, int]`
  - `get_orderbook(symbol: str) -> Book`
  - `get_stocks(symbols: list[str]) -> list[dict]`
  - `get_session() -> Session | None` (휴장이면 `None`)
  - `TossError(Exception)` — `.kind`가 `"auth"` | `"ip"` | `"other"`

- [ ] **Step 1: `scrap.py`의 토큰 함수를 public으로 승격한다**

`scrap.py`에서 세 곳을 고친다. 새 토큰 로직을 짜지 않는다 — 만료 60초 전 갱신이 이미 들어 있다.

```bash
python - <<'EOF'
import io
s = io.open('scrap.py', encoding='utf-8').read()
s = s.replace('def _get_access_token() -> str:', 'def get_access_token() -> str:')
s = s.replace('access_token = _get_access_token()', 'access_token = get_access_token()')
s = s.replace('token = _get_access_token()', 'token = get_access_token()')
assert '_get_access_token' not in s, '남은 호출부가 있다'
io.open('scrap.py', 'w', encoding='utf-8').write(s)
EOF
python -c "import scrap; print(scrap.get_access_token()[:12], '...')"
```

Expected: 토큰 앞 12자가 출력된다. 실패하면 `.env`나 IP 등록 문제다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`paper/test_toss.py`:

```python
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
```

- [ ] **Step 3: 실패를 확인한다**

Run: `python paper/test_toss.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper.toss'`

- [ ] **Step 4: 최소 구현을 쓴다**

`paper/toss.py`:

```python
"""
토스증권 Open API의 **읽기 전용** 래퍼.

경고 — 이 파일에 주문 관련 함수를 추가하지 마라:
  토스 Open API에는 모의투자 sandbox가 없다. 서버가 실서버 하나뿐이라
  POST /api/v1/orders를 부르면 그건 실제 돈이 나가는 진짜 주문이다.
  이 사이트의 체결은 전부 paper/broker.py가 시뮬레이션한다.
  실매매가 필요해지면 그건 별도의 결정으로 다뤄야 한다.

숫자는 전부 문자열로 오므로 파싱 시점에 int로 바꾼다.
"""
from datetime import datetime

import requests

from paper.broker import Book, Level, Session
from scrap import get_access_token

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


def parse_session(body: dict) -> Session | None:
    """오늘의 정규장 구간. 휴장이면 None."""
    today = body["result"]["today"]
    integrated = today.get("integrated")
    if not integrated:
        return None
    reg = integrated["regularMarket"]
    return Session(start=datetime.fromisoformat(reg["startTime"]),
                   end=datetime.fromisoformat(reg["endTime"]))


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
```

- [ ] **Step 5: 통과를 확인한다**

```bash
python paper/test_toss.py
grep -rn "api/v1/orders\|api/v1/accounts" paper/ && echo "주문 경로가 들어갔다 — 제거하라" || echo "주문 경로 없음 확인"
```

Expected: `test_toss 통과` 그리고 `주문 경로 없음 확인`

- [ ] **Step 6: 실제 호출로 한 번만 확인한다**

```bash
python -c "
from paper.toss import get_prices, get_orderbook, get_session
print(get_prices(['005930']))
b = get_orderbook('005930'); print(b.asks[0], b.bids[0])
print(get_session())
"
```

Expected: 현재가·호가·장 구간이 출력된다. `TossError`가 나면 `.kind`를 보고 IP 등록인지 토큰인지 판단한다.

- [ ] **Step 7: 커밋**

```bash
git add paper/toss.py paper/test_toss.py scrap.py
git commit -m "feat(paper): 읽기 전용 토스 REST 래퍼"
```

---

### Task 7: 업스트림 웹소켓 (`paper/feed.py`)

**Files:**
- Create: `paper/feed.py`, `paper/test_feed.py`

**Interfaces:**
- Consumes: `scrap.get_access_token`
- Produces:
  - `build_declaration(symbols: list[str], req_id: str) -> list[dict]`
  - `parse_event(raw: str) -> tuple[str, str, dict] | None` → `(kind, symbol, data)`, `kind`는 `"trade"` | `"orderbook"`
  - `MAX_SYMBOLS = 50`
  - `Feed(on_trade, on_orderbook, on_status)` — 콜백 셋을 받는다
  - `Feed.set_symbols(symbols: list[str]) -> None`
  - `await Feed.run()` — 재접속 루프. 종료되지 않는다

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`paper/test_feed.py`:

```python
"""구독 선언과 이벤트 파싱 검증. 네트워크를 타지 않는다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python paper/test_feed.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'paper.feed'`

- [ ] **Step 3: 최소 구현을 쓴다**

`paper/feed.py`:

```python
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
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python paper/test_feed.py`
Expected: PASS — 6개 테스트 통과

- [ ] **Step 5: 실제 연결을 30초만 확인한다**

```bash
python -c "
import asyncio
from paper.feed import Feed
f = Feed(on_trade=lambda s,d: print('체결', s, d['price'], d['volume']),
         on_orderbook=lambda s,d: print('호가', s, d['asks'][0].price),
         on_status=lambda st,m: print('상태', st, m))
f.set_symbols(['005930'])
async def main():
    try: await asyncio.wait_for(f.run(), timeout=30)
    except asyncio.TimeoutError: print('30초 종료')
asyncio.run(main())
"
```

Expected: `상태 connected`가 뜬다. 장중이면 체결·호가가 흐르고, 장 마감 후면 조용하다 — 둘 다 정상이다. `상태 reconnecting`이 반복되면 IP 등록이나 토큰 문제다.

- [ ] **Step 6: 커밋**

```bash
git add paper/feed.py paper/test_feed.py
git commit -m "feat(paper): 토스 웹소켓 업스트림과 재접속"
```

---

### Task 8: FastAPI 서버 (`paper/app.py`)

**Files:**
- Create: `paper/app.py`

**Interfaces:**
- Consumes: Task 5의 `Broker`/`OrderRejected`, Task 6의 `toss.*`, Task 7의 `Feed`
- Produces: `app` (FastAPI 인스턴스), `python -m uvicorn paper.app:app`으로 뜬다

- [ ] **Step 1: 의존성을 설치한다**

```bash
pip install fastapi uvicorn websockets
python -c "import fastapi, uvicorn, websockets; print('ok')"
```

- [ ] **Step 2: 구현을 쓴다**

`paper/app.py`:

```python
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
    fills = broker.on_trade(symbol, data["price"], data["volume"], datetime.now())
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
        now = datetime.now(session.end.tzinfo)
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
    try:
        prices = toss.get_prices(syms)
        last_price.update(prices)
    except toss.TossError as exc:
        prices = dict(last_price)
        on_status("error", str(exc))
    names = {s["symbol"]: s["name"] for s in toss.get_stocks(syms)} if syms else {}
    return [{"symbol": s, "name": names.get(s, s), "price": prices.get(s)}
            for s in syms]


@app.post("/api/watchlist")
def api_watch(body: WatchIn):
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
                           session=session, now=datetime.now(session.start.tzinfo))
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
        broker.cancel(order_id, now=datetime.now())
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
```

- [ ] **Step 3: 서버가 뜨고 라우트가 응답하는지 확인한다**

터미널 하나에서:

```bash
python -m uvicorn paper.app:app --port 8000
```

다른 터미널에서:

```bash
curl -s localhost:8000/api/status
curl -s -X POST localhost:8000/api/watchlist -H 'Content-Type: application/json' -d '{"symbol":"005930","action":"add"}'
curl -s localhost:8000/api/watchlist
curl -s localhost:8000/api/portfolio
curl -s "localhost:8000/api/quote?symbol=005930"
```

Expected: `/api/status`가 `connected` 또는 `starting`, 관심종목 추가 후 목록에 `005930`이 뜨고, 포트폴리오 현금이 10,000,000, 호가가 10단 나온다.

- [ ] **Step 4: 장 시간 밖 주문이 거부되는지 확인한다**

```bash
curl -s -X POST localhost:8000/api/orders -H 'Content-Type: application/json' \
  -d '{"symbol":"005930","side":"buy","type":"market","qty":1}'
```

Expected: 정규장이면 주문이 접수되고, 장 시간 밖이면 `"정규장(09:00~15:30)에만 주문할 수 있습니다"`가 400으로 돌아온다.

- [ ] **Step 5: 커밋**

```bash
git add paper/app.py
git commit -m "feat(paper): FastAPI 라우트와 웹소켓 팬아웃"
```

---

### Task 9: 화면 (`paper/static/index.html`)

**Files:**
- Create: `paper/static/index.html`

**Interfaces:**
- Consumes: Task 8의 REST 라우트와 `/ws` 메시지 형식

- [ ] **Step 1: 구현을 쓴다**

`paper/static/index.html`:

```html
<!doctype html>
<meta charset="utf-8">
<title>모의투자</title>
<style>
  :root { --up:#d24; --down:#25c; --line:#e3e3e6; --muted:#777; }
  * { box-sizing: border-box; }
  body { margin:0; font:13px/1.5 "Malgun Gothic", system-ui, sans-serif; color:#111; }
  #banner { display:none; padding:8px 12px; background:#c0392b; color:#fff; font-weight:600; }
  #banner.on { display:block; }
  #grid { display:grid; grid-template-columns:220px 1fr 320px; height:calc(100vh - 0px); }
  .pane { border-right:1px solid var(--line); overflow:auto; padding:10px; }
  .pane:last-child { border-right:0; }
  h2 { font-size:12px; color:var(--muted); margin:14px 0 6px; letter-spacing:.04em; }
  table { width:100%; border-collapse:collapse; }
  td, th { padding:3px 4px; text-align:right; white-space:nowrap; }
  th { color:var(--muted); font-weight:500; font-size:11px; }
  td:first-child, th:first-child { text-align:left; }
  tr.sel { background:#eef4ff; }
  .ask { color:var(--down); } .bid { color:var(--up); }
  .book td { cursor:pointer; }
  .book .vol { color:var(--muted); }
  input, select, button { font:inherit; padding:4px 6px; }
  input { width:100%; }
  button { cursor:pointer; }
  .buy { background:var(--up); color:#fff; border:0; padding:8px; width:100%; }
  .sell { background:var(--down); color:#fff; border:0; padding:8px; width:100%; }
  .row { display:flex; gap:6px; margin:4px 0; align-items:center; }
  .row label { width:56px; color:var(--muted); }
  #chart { height:260px; border:1px solid var(--line); }
  .pos { color:var(--up); } .neg { color:var(--down); }
  .err { color:#c0392b; min-height:18px; margin-top:6px; }
</style>

<div id="banner"></div>
<div id="grid">
  <div class="pane">
    <div class="row"><input id="add" placeholder="종목코드 추가 (예 005930)"></div>
    <h2>관심종목</h2>
    <table><tbody id="watch"></tbody></table>
  </div>

  <div class="pane">
    <h2 id="title">종목을 고르세요</h2>
    <div id="chart"></div>
    <h2>호가</h2>
    <table class="book"><tbody id="book"></tbody></table>
  </div>

  <div class="pane">
    <h2>주문</h2>
    <div class="row"><label>유형</label>
      <select id="otype"><option value="limit">지정가</option><option value="market">시장가</option></select>
    </div>
    <div class="row"><label>가격</label><input id="oprice" type="number" step="1"></div>
    <div class="row"><label>수량</label><input id="oqty" type="number" min="1" value="1"></div>
    <div class="row">
      <button class="buy" onclick="order('buy')">매수</button>
      <button class="sell" onclick="order('sell')">매도</button>
    </div>
    <div class="err" id="err"></div>

    <h2>미체결</h2>
    <table><tbody id="open"></tbody></table>

    <h2>보유</h2>
    <table>
      <tr><th>종목</th><th>수량</th><th>평단</th><th>손익</th></tr>
      <tbody id="pos"></tbody>
    </table>
    <h2>현금</h2>
    <div id="cash"></div>
  </div>
</div>

<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
        onerror="window.__nochart=1"></script>
<script>
const won = n => (n ?? 0).toLocaleString("ko-KR");
let symbol = null, series = null;

// ---- 연결 상태 배너. 끊긴 동안 지정가 체결 판정이 멈추므로 반드시 보인다.
function banner(status, message) {
  const el = document.getElementById("banner");
  if (status === "connected") { el.className = ""; return; }
  el.className = "on";
  el.textContent = status === "reconnecting"
    ? "실시간 연결 끊김 — 지정가 체결이 중단됩니다. 재접속 중… " + (message || "")
    : "연결 오류: " + (message || status);
}

// ---- 차트. CDN이 막히면 차트만 빠지고 매매는 계속 된다.
function initChart() {
  if (window.__nochart || !window.LightweightCharts) {
    document.getElementById("chart").textContent = "차트를 불러오지 못했습니다 (매매는 정상)";
    return null;
  }
  const c = LightweightCharts.createChart(document.getElementById("chart"),
    { height: 260, layout: { attributionLogo: false } });
  return c.addCandlestickSeries();
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

async function loadWatch() {
  const rows = await api("/api/watchlist");
  document.getElementById("watch").innerHTML = rows.map(r => `
    <tr class="${r.symbol === symbol ? "sel" : ""}" onclick="select('${r.symbol}')">
      <td>${r.name}</td><td>${won(r.price)}</td>
      <td><button onclick="event.stopPropagation();remove('${r.symbol}')">×</button></td>
    </tr>`).join("");
}

async function select(s) {
  symbol = s;
  document.getElementById("title").textContent = s;
  await loadWatch();
  await loadBook();
  if (series) {
    const candles = await api("/api/candles?symbol=" + s);
    series.setData(candles.map(c => ({
      time: Math.floor(new Date(c.time).getTime() / 1000),
      open: c.open, high: c.high, low: c.low, close: c.close })));
  }
}

async function loadBook() {
  if (!symbol) return;
  drawBook(await api("/api/quote?symbol=" + symbol));
}

function drawBook(q) {
  const ask = [...q.asks].reverse().map(([p, v]) =>
    `<tr><td class="vol"></td><td class="ask" onclick="pick(${p})">${won(p)}</td><td class="vol">${won(v)}</td></tr>`);
  const bid = q.bids.map(([p, v]) =>
    `<tr><td class="vol">${won(v)}</td><td class="bid" onclick="pick(${p})">${won(p)}</td><td class="vol"></td></tr>`);
  document.getElementById("book").innerHTML = ask.join("") + bid.join("");
}

const pick = p => document.getElementById("oprice").value = p;

async function order(side) {
  const err = document.getElementById("err");
  err.textContent = "";
  if (!symbol) { err.textContent = "종목을 먼저 고르세요."; return; }
  const type = document.getElementById("otype").value;
  const body = { symbol, side, type, qty: +document.getElementById("oqty").value };
  if (type === "limit") body.limit_price = +document.getElementById("oprice").value;
  try {
    await api("/api/orders", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    await loadOpen();
  } catch (e) { err.textContent = e.message; }
}

async function loadOpen() {
  const rows = await api("/api/orders?status=pending");
  document.getElementById("open").innerHTML = rows.map(o => `
    <tr><td>${o.symbol}</td>
        <td class="${o.side === "buy" ? "pos" : "neg"}">${o.side === "buy" ? "매수" : "매도"}</td>
        <td>${won(o.limit_price)}</td>
        <td>${o.filled_qty}/${o.qty}</td>
        <td><button onclick="cancel(${o.id})">취소</button></td></tr>`).join("");
}

async function cancel(id) {
  await api("/api/orders/" + id, { method: "DELETE" });
  await loadOpen();
}

async function remove(s) {
  await api("/api/watchlist", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: s, action: "remove" }) });
  if (symbol === s) symbol = null;
  await loadWatch();
}

document.getElementById("add").addEventListener("keydown", async e => {
  if (e.key !== "Enter") return;
  const s = e.target.value.trim();
  if (!s) return;
  try {
    await api("/api/watchlist", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: s, action: "add" }) });
    e.target.value = "";
    await loadWatch();
  } catch (err) { document.getElementById("err").textContent = err.message; }
});

function drawPortfolio(p) {
  document.getElementById("pos").innerHTML = p.positions.map(x => `
    <tr><td>${x.symbol}</td><td>${x.qty}</td><td>${won(x.avg_cost)}</td>
        <td class="${x.pnl >= 0 ? "pos" : "neg"}">${won(x.pnl)} (${x.pnl_pct}%)</td></tr>`).join("");
  document.getElementById("cash").innerHTML =
    `보유현금 ${won(p.cash)}원<br>주문가능 ${won(p.available)}원<br>주문묶임 ${won(p.reserved)}원`;
}

// ---- 서버 푸시
const ws = new WebSocket(`ws://${location.host}/ws`);
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.type === "feed") banner(m.status, m.message);
  else if (m.type === "portfolio") drawPortfolio(m);
  else if (m.type === "orderbook" && m.symbol === symbol) drawBook(m);
  else if (m.type === "trade") { if (m.symbol === symbol) loadWatchThrottled(); }
  else if (m.type === "fill") { loadOpen(); }
  else if (m.type === "expired") { loadOpen(); }
};
ws.onclose = () => banner("reconnecting", "브라우저 연결이 끊겼습니다. 새로고침하세요.");

let watchTimer = null;
function loadWatchThrottled() {
  if (watchTimer) return;
  watchTimer = setTimeout(() => { watchTimer = null; loadWatch(); }, 2000);
}

series = initChart();
loadWatch();
loadOpen();
</script>
```

- [ ] **Step 2: 브라우저에서 확인한다**

```bash
python -m uvicorn paper.app:app --port 8000
```

`http://localhost:8000`을 열고 확인한다:

1. 관심종목 칸에 `005930`을 넣고 Enter → 목록에 삼성전자가 뜬다
2. 클릭하면 호가 10단과 분봉 차트가 그려진다
3. 호가의 가격을 클릭하면 주문 가격 칸에 들어간다
4. 장 시간 밖이면 매수 버튼이 `"정규장(09:00~15:30)에만…"` 에러를 빨간 글씨로 띄운다
5. 서버를 끄면 상단에 빨간 배너가 뜬다

- [ ] **Step 3: 커밋**

```bash
git add paper/static/index.html
git commit -m "feat(paper): 매매 화면"
```

---

### Task 10: 문서화와 전체 점검

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 테스트를 전부 돌린다**

```bash
for f in paper/test_ticks.py paper/test_broker.py paper/test_toss.py paper/test_feed.py; do
  echo "=== $f"; python "$f" || exit 1
done
```

Expected: 넷 다 통과

- [ ] **Step 2: 주문 API가 코드에 없는지 확인한다**

```bash
grep -rn "api/v1/orders\|api/v1/accounts" paper/ scrap.py && echo "제거하라" || echo "확인: 주문 경로 없음"
```

Expected: `확인: 주문 경로 없음`

- [ ] **Step 3: `CLAUDE.md`에 절을 추가한다**

`## 데이터` 절 **앞에** 아래를 넣는다:

```markdown
## 모의투자 웹사이트 (`paper/`)

    pip install fastapi uvicorn websockets     # 최초 1회
    python -m uvicorn paper.app:app --reload   # http://localhost:8000

토스 실시간 시세를 받아 브라우저에서 손으로 주문을 넣고, 체결·잔고·손익을 가짜 돈으로 추적한다. 백테스팅 하네스와는 별개 경로다 — `strategies/`, `run.py`, `results.py`를 건드리지 않는다.

**토스에는 모의투자 sandbox가 없다.** 서버가 실서버 하나뿐이라 `POST /api/v1/orders`를 부르면 실제 돈이 나간다. 그래서 `paper/toss.py`는 읽기 전용 함수만 노출하고, 코드 어디에도 주문·계좌 경로가 등장하지 않는다. 실매매가 필요해지면 별도 결정으로 다뤄라.

**브라우저는 토스 웹소켓에 직접 못 붙는다.** 핸드셰이크에 `Authorization` 헤더가 필요한데 브라우저 WebSocket API는 커스텀 헤더를 못 넣고, 넣을 수 있어도 토큰이 프론트로 샌다. 그래서 백엔드가 업스트림 연결 **하나**(계정당 2개 제한)를 물고 팬아웃한다.

**상태는 `paper.db`의 `fills`에서 파생한다.** 현금·보유수량·평균단가를 따로 저장하지 않는다. 두 곳을 맞추다 어긋나면 잔고가 조용히 틀린다.

**체결 규칙**: 시장가는 호가를 다단으로 훑고 소진되면 부분체결로 끝난다(대기하지 않음). 지정가는 `pending`으로 남았다가 `trade:kr` 프린트가 지정가를 지나갈 때 채워지며, 체결가는 내 지정가가 아니라 프린트된 가격이다. 큐 포지션은 모델링하지 않아 실제보다 잘 체결된다.

**`partial`은 종료 상태다.** 부분체결된 채 아직 대기 중인 지정가는 `pending` + `filled_qty > 0`이다. 이 둘을 뭉치면 주문장에서 아직 체결될 수 있는 주문을 못 가린다.

**정규장(09:00~15:30)에서만 체결한다.** 시간외단일가는 체결 규칙이 달라 별도 엔진이 필요하므로 주문을 거부한다.

**업스트림이 끊기면 지정가 체결 판정이 멈춘다.** 조용히 두면 체결됐어야 할 주문이 왜 안 됐는지 알 수 없어서, 화면 상단에 빨간 배너를 띄운다. 이게 이 설계에서 가장 위험한 조용한 실패다.

테스트: `python paper/test_broker.py` (체결 엔진), `test_ticks.py`, `test_toss.py`, `test_feed.py`. 프레임워크 없이 assert 기반이다.
```

`## Commands`의 코드블록에도 한 줄 추가한다:

```bash
python -m uvicorn paper.app:app --reload            # 모의투자 웹사이트
```

`프레임워크 없음. 빌드/린트 파이프라인도 없고 `requirements.txt`도 없다` 문장의 괄호 안 목록에 `fastapi, uvicorn, websockets`를 추가한다.

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: 모의투자 웹사이트 사용법과 설계 제약 기록"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 요구 | 구현 태스크 |
|---|---|
| 안전 경계 (주문 API 금지) | T6 Step 5, T10 Step 2 |
| 읽기 전용 REST 래퍼 | T6 |
| 웹소켓 구독·keepalive·재접속 | T7 |
| 백엔드 팬아웃 | T8 |
| `paper.db` 4개 테이블 | T2 (SCHEMA에 전부 들어 있다) |
| fills에서 파생 | T2 |
| 예약금액·예약수량 | T5 |
| 시장가 다단 체결 | T3 |
| 지정가 대기·프린트 판정 | T4 |
| 호가단위 검증 | T1 + T5 |
| 정규장 판정 | T5 (`Session.is_open`), T6 (`get_session`) |
| 15:30 만료 | T5 (`expire_all`) |
| 비용 분리 기록 | T2 (`_record_fill`) |
| API 표면 9개 라우트 | T8 |
| 차트 | T8 `/api/candles` + T9 |
| 연결 끊김 배너 | T7 `on_status` → T8 `broadcast` → T9 `banner()` |
| 테스트 12항목 | T1~T5 (25개로 확장) |

| 15:30 자동 만료 | T8 `expire_at_close()` |

초안에는 `expire_all`을 부르는 주체가 없어 스펙 요구가 붕 떠 있었다. 실행자에게 결정을 떠넘기지 않으려고 T8의 startup에 1분 폴링 태스크로 확정해 넣었다. 없으면 어제 걸어 둔 지정가가 오늘 시세에 체결되어 잔고가 거짓이 된다.

**2. 플레이스홀더 스캔**: TBD/TODO 없음. 모든 코드 스텝에 실제 코드가 들어 있다.

**3. 타입 일관성 확인**
- `Broker.place(..., book=, session=, now=)` — T3에서 정의, T4·T5·T8에서 같은 시그니처로 호출됨 ✓
- `Broker.on_trade(symbol, price, volume, now)` — T4 정의, T8 호출 ✓
- `Book(symbol, asks, bids)` / `Level(price, volume)` — T2 정의, T6·T7·T8에서 동일 ✓
- `Session(start, end)` + `.is_open(now)` — T2 정의, T5·T6·T8 사용 ✓
- `parse_event` 반환 `(kind, symbol, data)` — T7 정의, `Feed._dispatch`와 T8 콜백이 같은 모양 ✓
- `scrap.get_access_token` — T6 Step 1에서 승격, T6·T7이 사용 ✓
