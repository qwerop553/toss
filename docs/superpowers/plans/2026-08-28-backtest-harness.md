# 백테스팅 하네스 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 전략 작성에서 상태머신 보일러플레이트를 제거하고, 실행·최적화·비교를 CLI 한 줄로 통합하며, 일별 손익과 거래별 승률·평균·분산을 리포트에 추가한다.

**Architecture:** `Strategy`에 선언적 경로(`entries`/`exits`)를 덧붙이고 상태머신을 `to_signals()` 한 곳에만 구현한다. 엔진은 체결가(`fill_price`)를 기록하고, `metrics.trade_stats()`가 FIFO로 왕복 거래를 짝지어 통계를 낸다. `run.py`가 실행·자동 최적화·비교를 모두 담당하고 파라미터 범위는 `grids.py`에 모은다.

**Tech Stack:** Python 3.14, pandas, numpy, matplotlib, sqlite3(표준 라이브러리). 새 의존성 없음. 테스트 프레임워크 없음 — `test_harness.py`의 `assert` 기반 자체 검사.

**Spec:** `docs/superpowers/specs/2026-08-28-backtest-harness-design.md`

## Global Constraints

- Python 3.14 (`print_summary.py`가 PEP 649 지연 annotation에 의존 중 — Task 3에서 명시적 import로 정리)
- 새 서드파티 의존성 추가 금지. pandas / numpy / matplotlib / 표준 라이브러리만 사용
- 테스트 프레임워크 도입 금지. 검사는 `python test_harness.py` 하나로 실행되는 `assert` 문
- 주석과 docstring은 **한국어**. 비자명한 계산(슬리피지 복원, FIFO 짝짓기, 상태머신 분기)은 의도와 근거를 함께 적는다. 기존 코드의 설명형 톤을 따른다
- 기존 백테스트 수치를 바꾸지 않는다. 마이그레이션한 전략은 이전과 **완전히 동일한 신호**를 내야 한다 (Task 4·5의 골든 스냅샷으로 강제)
- 슬리피지 기본값 고정: 매수 `0.00015`, 매도 `0.00215` (매도에 거래세 포함)
- 데이터는 `market_data.db`의 실데이터를 쓴다. 종목 `005930`, `000660`, `035420` / `interval="1m"`

---

### Task 1: 상태머신 `to_signals()` + `Strategy` 베이스 확장

**Files:**
- Modify: `strategies/base.py` (전체 재작성, 현재 18줄)
- Create: `test_harness.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `strategies.base.to_signals(entries: pd.Series, exits: pd.Series, warmup: int = 0) -> pd.Series` — 값은 `{-1, 0, 1}`, 인덱스는 `entries`와 동일
  - `strategies.base.Strategy` — 클래스 속성 `warmup: int = 0`, 메서드 `entries(df)`, `exits(df)`, `generate_signals(df)`

- [ ] **Step 1: `test_harness.py`에 실패하는 테스트를 작성한다**

```python
"""
하네스 자체 검사. 프레임워크 없이 `python test_harness.py`로 실행한다.
전략의 수익성을 검증하는 게 아니라, 하네스 배관(상태머신·FIFO 짝짓기)이
깨졌는지를 잡는 것이 목적이다.
"""
import pandas as pd

from strategies.base import to_signals


def _s(values):
    """불리언 리스트를 Series로. 인덱스는 0부터의 정수."""
    return pd.Series(values, dtype=bool)


def test_to_signals_기본_왕복():
    # 진입 신호가 두 번 연속 떠도 이미 보유 중이면 두 번째는 무시되어야 한다.
    entries = _s([True, True, False, False])
    exits = _s([False, False, True, False])
    assert list(to_signals(entries, exits)) == [1, 0, -1, 0]


def test_to_signals_중복_진입_차단():
    # 진입 조건이 계속 참이어도 청산 전까지는 추가 매수가 나가면 안 된다.
    # (이 규칙이 깨지면 포지션이 무한히 쌓인다 — 구 엔진의 대표적 함정)
    entries = _s([True] * 5)
    exits = _s([False] * 5)
    assert list(to_signals(entries, exits)) == [1, 0, 0, 0, 0]


def test_to_signals_미보유_청산_무시():
    # 보유하지 않은 상태의 청산 조건은 아무 일도 일으키지 않는다.
    entries = _s([False] * 3)
    exits = _s([True] * 3)
    assert list(to_signals(entries, exits)) == [0, 0, 0]


def test_to_signals_워밍업_구간은_전부_0():
    # 지표가 아직 신뢰할 수 없는 구간은 통째로 0이어야 한다.
    entries = _s([True] * 5)
    exits = _s([False] * 5)
    assert list(to_signals(entries, exits, warmup=3)) == [0, 0, 0, 1, 0]


def test_to_signals_동시신호_결정1():
    # 설계 결정 1: 미보유면 진입이 이기고, 보유 중이면 청산이 이긴다.
    entries = _s([True, True])
    exits = _s([True, True])
    #  i=0: 미보유 + 둘 다 참 -> 진입
    #  i=1: 보유   + 둘 다 참 -> 청산
    assert list(to_signals(entries, exits)) == [1, -1]


def test_to_signals_NaN은_False로_취급():
    # 지표 워밍업 구간에서 NaN이 나오는 건 정상. 신호로 새면 안 된다.
    entries = pd.Series([None, True, None], dtype=object)
    exits = pd.Series([None, None, True], dtype=object)
    assert list(to_signals(entries, exits)) == [0, 1, -1]


def test_to_signals_인덱스_보존():
    # 반환 Series는 입력 인덱스를 그대로 유지해야 한다
    # (엔진이 df와 나란히 쓰기 때문).
    idx = pd.date_range("2026-01-01", periods=3, freq="min")
    entries = pd.Series([True, False, False], index=idx)
    exits = pd.Series([False, False, True], index=idx)
    assert to_signals(entries, exits).index.equals(idx)


def test_to_signals_인덱스_불일치는_에러():
    entries = pd.Series([True], index=[0])
    exits = pd.Series([False], index=[1])
    try:
        to_signals(entries, exits)
    except ValueError:
        pass
    else:
        raise AssertionError("인덱스가 다른데 ValueError가 나지 않았다")


def _run_all():
    """이 모듈의 test_로 시작하는 함수를 전부 실행한다."""
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        fn()
        print(f"  PASS  {name}")
    print(f"\n{len(tests)}개 통과")


if __name__ == "__main__":
    _run_all()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_harness.py`
Expected: FAIL — `ImportError: cannot import name 'to_signals' from 'strategies.base'`

- [ ] **Step 3: `strategies/base.py`를 재작성한다**

```python
# ABC : Abstract Base Class, 상속해서 사용하지 않으면 오류를 낸다.
# abstractmethod를 붙이면 이 메서드를 구현하지 않은 자식 클래스는 아예 인스턴스를 만들지 못한다.
from abc import ABC
import numpy as np
import pandas as pd


def to_signals(entries: pd.Series, exits: pd.Series, warmup: int = 0) -> pd.Series:
    """
    진입/청산 조건(불리언 Series)을 엔진이 먹는 신호 {-1, 0, 1}로 바꾼다.

    왜 이 함수가 따로 있나:
      엔진(run_backtest)은 신호를 '상태'가 아니라 '이벤트'로 읽는다. 1이 나올 때마다
      조건 없이 1주를 더 산다. 그래서 예전에는 전략마다 holding 불리언을 들고 도는
      for 루프를 복붙해야 했다. 그 루프를 여기 한 번만 구현하고, 전략은 조건식만
      쓰게 하는 것이 목적이다.

    규칙:
      - warmup 미만 구간은 무조건 0 (지표가 아직 신뢰할 수 없는 구간)
      - 미보유 + entries -> 1 (보유로 전환)
      - 보유   + exits   -> -1 (미보유로 전환)
      - 최대 1주. 중복 진입이 원천적으로 불가능하다.

    동시 신호(설계 결정 1):
      한 봉에서 진입·청산이 모두 참이면, 미보유 상태에서는 진입이 이기고 보유
      상태에서는 청산이 이긴다. 아래 if/elif 순서에서 자연히 따라온다. 평균회귀
      전략은 두 조건이 동시에 참일 수 없고, 가능한 전략이라도 다음 봉에서 반대
      신호가 다시 뜨므로 손실될 정보가 없다.
    """
    if not entries.index.equals(exits.index):
        raise ValueError("entries와 exits의 인덱스가 다릅니다. 같은 df에서 파생되어야 합니다.")

    # NaN을 False로 눌러 둔다. 지표 워밍업 구간에서 NaN이 나오는 건 정상이고,
    # 그게 신호로 새 나가면 안 된다. object dtype으로 들어오는 경우까지 감안해
    # fillna 후 bool로 캐스팅한다.
    entry_flags = entries.fillna(False).to_numpy(dtype=bool)
    exit_flags = exits.fillna(False).to_numpy(dtype=bool)

    # ponytail: 순수 파이썬 루프. 보유 상태가 이전 봉에 의존하는 순차 로직이라
    # 벡터화가 자명하지 않다. 10만 봉에 약 50ms 수준이고 지금도 전략마다 같은
    # 루프를 돌고 있어 손해가 없다. 그리드 조합이 수천 개로 커져 그리드서치가
    # 체감상 느려지면 그때 numpy 누적 트릭이나 numba로 올린다.
    out = np.zeros(len(entry_flags), dtype=np.int8)
    holding = False

    for i in range(warmup, len(entry_flags)):
        if not holding and entry_flags[i]:
            out[i] = 1
            holding = True
        elif holding and exit_flags[i]:
            out[i] = -1
            holding = False

    return pd.Series(out, index=entries.index)


class Strategy(ABC):
    """
    모든 전략의 베이스 클래스.

    전략을 쓰는 방법은 두 가지다.

    1) 선언형 (권장) — entries()와 exits()에 조건식만 쓴다.
       보유 상태 관리, 중복 진입 차단, 워밍업 절단은 베이스가 알아서 한다.

           class MyStrategy(Strategy):
               def __init__(self, period=20):
                   self.period = period
                   self.warmup = period          # 지표가 익을 때까지 신호 없음
               def entries(self, df):
                   return df["close"] < df["close"].rolling(self.period).mean()
               def exits(self, df):
                   return df["close"] > df["close"].rolling(self.period).mean()

    2) 직접 구현 — generate_signals()를 오버라이드한다.
       쿨다운, 트레일링 스톱처럼 진짜 순차 상태가 필요할 때만 쓴다.
       (예: EmaCrossStrategyWithATR)
    """

    # 서브클래스가 __init__에서 self.warmup = self.slow 처럼 덮어쓴다.
    # 인스턴스 속성이 클래스 속성을 가리므로 둘 다 동작한다.
    warmup: int = 0

    def entries(self, df: pd.DataFrame) -> pd.Series:
        """매수 조건. df와 같은 인덱스를 가진 불리언 Series를 반환한다."""
        raise NotImplementedError(
            f"{type(self).__name__}는 entries()/exits()를 구현하거나 "
            "generate_signals()를 직접 오버라이드해야 합니다."
        )

    def exits(self, df: pd.DataFrame) -> pd.Series:
        """매도 조건. df와 같은 인덱스를 가진 불리언 Series를 반환한다."""
        raise NotImplementedError(
            f"{type(self).__name__}는 entries()/exits()를 구현하거나 "
            "generate_signals()를 직접 오버라이드해야 합니다."
        )

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        df: scrap.load_candles()가 반환하는 OHLCV 데이터프레임
        반환값: index가 df와 같고 값이 {-1, 0, 1}(매도, 유지, 매수)인 Series

        엔진은 이 인터페이스만 본다. 기본 구현은 entries/exits를 상태머신에
        태우는 것이고, 필요하면 서브클래스가 통째로 오버라이드해도 된다.
        """
        entries = self.entries(df)
        exits = self.exits(df)

        # 인덱스가 어긋나면 엔진이 .iloc으로 접근하는 탓에 조용히 엉뚱한 봉과
        # 짝지어진다. 여기서 미리 끊는 편이 디버깅이 훨씬 쉽다.
        if not entries.index.equals(df.index):
            raise ValueError(
                f"{type(self).__name__}.entries()의 인덱스가 df와 다릅니다. "
                "df의 인덱스를 그대로 쓰세요."
            )

        return to_signals(entries, exits, self.warmup)
```

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `python test_harness.py`
Expected: PASS — 8개 통과

- [ ] **Step 5: 커밋**

```bash
git add strategies/base.py test_harness.py
git commit -m "feat: 신호 상태머신을 to_signals()로 통합"
```

---

### Task 2: 체결가 기록 + 트레이드 통계

**Files:**
- Modify: `backtest_engine.py:44-53` (trades 행에 `fill_price` 추가)
- Modify: `metrics.py` (파일 끝에 `trade_stats` 추가)
- Modify: `test_harness.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `to_signals`
- Produces:
  - `run_backtest()`가 반환하는 `result.trades`에 `fill_price: float` 컬럼 추가 (매수 `price + step_cost`, 매도 `price - step_cost`)
  - `metrics.trade_stats(trades: pd.DataFrame) -> dict` — 키: `round_trips`, `win_rate`, `avg_return`, `std_return`, `var_return`, `avg_win`, `avg_loss`, `profit_factor`, `avg_holding_bars`, `open_position`

- [ ] **Step 1: `test_harness.py`에 실패하는 테스트를 추가한다**

`import pandas as pd` 아래에 임포트를 추가한다:

```python
from backtest_engine import run_backtest
from metrics import trade_stats
```

그리고 `_run_all` 정의 위에 아래 테스트들을 추가한다:

```python
def _candles(closes):
    """종가만 지정해서 최소한의 OHLCV df를 만든다. 고가/저가는 종가와 동일."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01 09:00", periods=len(closes), freq="min"),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * len(closes),
    })


def test_engine_fill_price_슬리피지_반영():
    # 매수 체결가는 원가격보다 비싸고, 매도 체결가는 원가격보다 싸야 한다.
    df = _candles([100.0, 110.0])
    signal = pd.Series([1, -1], index=df.index)
    result = run_backtest(df, signal, buy_slippage=0.01, sell_slippage=0.02)

    buy = result.trades[result.trades["side"] == "buy"].iloc[0]
    sell = result.trades[result.trades["side"] == "sell"].iloc[0]
    assert buy["fill_price"] == 101.0   # 100 + 100*0.01
    assert sell["fill_price"] == 107.8  # 110 - 110*0.02


def test_trade_stats_손으로_계산한_값과_일치():
    # 왕복 2건: 하나는 이기고 하나는 진다.
    #   1) 100에 사서 110에 팜 -> +10, 수익률 +10%
    #   2) 200에 사서 180에 팜 -> -20, 수익률 -10%
    trades = pd.DataFrame([
        {"position": 0, "date": None, "side": "buy",  "price": 100.0, "fill_price": 100.0},
        {"position": 2, "date": None, "side": "sell", "price": 110.0, "fill_price": 110.0},
        {"position": 5, "date": None, "side": "buy",  "price": 200.0, "fill_price": 200.0},
        {"position": 9, "date": None, "side": "sell", "price": 180.0, "fill_price": 180.0},
    ])
    stats = trade_stats(trades)

    assert stats["round_trips"] == 2
    assert stats["win_rate"] == 0.5
    assert abs(stats["avg_return"] - 0.0) < 1e-12       # (+0.10 + -0.10) / 2
    assert abs(stats["avg_win"] - 0.10) < 1e-12
    assert abs(stats["avg_loss"] - (-0.10)) < 1e-12
    assert abs(stats["profit_factor"] - 0.5) < 1e-12    # 총이익 10 / 총손실 20
    assert stats["avg_holding_bars"] == 3.0             # (2-0)과 (9-5)의 평균
    assert stats["open_position"] == 0


def test_trade_stats_미청산_포지션_분리():
    # 마지막 매수가 청산되지 않았다면 왕복으로 세지 않고 따로 보고한다
    # (설계 결정 2: 마지막 봉에서 강제 청산하지 않는다).
    trades = pd.DataFrame([
        {"position": 0, "date": None, "side": "buy",  "price": 100.0, "fill_price": 100.0},
        {"position": 2, "date": None, "side": "sell", "price": 110.0, "fill_price": 110.0},
        {"position": 5, "date": None, "side": "buy",  "price": 200.0, "fill_price": 200.0},
    ])
    stats = trade_stats(trades)
    assert stats["round_trips"] == 1
    assert stats["open_position"] == 1
    assert stats["win_rate"] == 1.0


def test_trade_stats_거래_없음():
    # 신호가 하나도 안 나온 전략에서 ZeroDivisionError가 나면 안 된다.
    stats = trade_stats(pd.DataFrame())
    assert stats["round_trips"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["profit_factor"] == 0.0
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_harness.py`
Expected: FAIL — `ImportError: cannot import name 'trade_stats' from 'metrics'`

- [ ] **Step 3: `backtest_engine.py`의 trades 기록에 `fill_price`를 추가한다**

매수/매도 분기(현재 44-53행)를 아래로 교체한다:

```python
        if sig == 1:
            step_cost = price * buy_slippage
            flow -= price + step_cost
            holdings += 1
            # fill_price: 슬리피지까지 반영된 '실제로 나간 돈'.
            # 승률·손익비를 낼 때 원가격(price)을 쓰면 비용이 빠져 실제보다
            # 후하게 나오므로, 체결가를 여기서 함께 기록해 둔다.
            trades.append({"position": i, "date": df["timestamp"].iloc[i],
                           "side": "buy", "price": price,
                           "fill_price": price + step_cost})
        elif sig == -1 and holdings > 0:
            step_cost = price * sell_slippage
            flow += price - step_cost
            holdings -= 1
            trades.append({"position": i, "date": df["timestamp"].iloc[i],
                           "side": "sell", "price": price,
                           "fill_price": price - step_cost})
```

- [ ] **Step 4: `metrics.py` 끝에 `trade_stats`를 추가한다**

```python
def trade_stats(trades: pd.DataFrame) -> dict:
    """
    평평한 매매 기록(buy/sell이 시간순으로 뒤섞인 표)을 왕복 거래 단위로
    묶어 승률·평균·분산 등을 낸다.

    FIFO 짝짓기가 맞는 이유:
      엔진은 봉을 시간순으로 훑으며 한 번에 1주씩만 사고팔고, 보유량이 0이면
      매도를 무시한다. 따라서 k번째 매도는 반드시 k번째 매수보다 뒤에 온다.
      그래서 그냥 순서대로 짝지으면 된다.

    수익률의 분모는 '그 거래의 매수 체결가'다(거래당 1주 기준). 이는
    result.returns(최대 투입원금 대비 일별 변동)와 의미가 다르다.
      - 여기: 이 거래가 몇 % 먹었나
      - returns: 투입 원금 대비 하루하루 얼마나 출렁였나
    둘 다 필요해서 둘 다 낸다.
    """
    empty = {
        "round_trips": 0, "win_rate": 0.0, "avg_return": 0.0,
        "std_return": 0.0, "var_return": 0.0, "avg_win": 0.0,
        "avg_loss": 0.0, "profit_factor": 0.0, "avg_holding_bars": 0.0,
        "open_position": 0,
    }
    if trades.empty:
        return empty

    buys = trades[trades["side"] == "buy"].reset_index(drop=True)
    sells = trades[trades["side"] == "sell"].reset_index(drop=True)

    n = min(len(buys), len(sells))   # 짝지어진 왕복만 집계
    open_position = len(buys) - n    # 청산되지 못하고 남은 매수

    if n == 0:
        return {**empty, "open_position": open_position}

    entry = buys["fill_price"].to_numpy()[:n]
    exit_ = sells["fill_price"].to_numpy()[:n]

    pnl = exit_ - entry            # 원화 손익 (1주 기준)
    ret = pnl / entry              # 수익률

    wins = ret[pnl > 0]
    losses = ret[pnl <= 0]

    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl <= 0].sum()   # 부호를 뒤집어 양수로

    holding_bars = sells["position"].to_numpy()[:n] - buys["position"].to_numpy()[:n]

    return {
        "round_trips": int(n),
        "win_rate": float(len(wins) / n),
        "avg_return": float(ret.mean()),
        "std_return": float(ret.std(ddof=0)),
        "var_return": float(ret.var(ddof=0)),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        # 손익비: 총이익 / 총손실. 손실이 0이면 나눗셈이 불가하니 0으로 둔다
        # (무한대를 넣으면 순위표 정렬이 깨진다).
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else 0.0,
        "avg_holding_bars": float(holding_bars.mean()),
        "open_position": int(open_position),
    }
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `python test_harness.py`
Expected: PASS — 12개 통과

- [ ] **Step 6: 커밋**

```bash
git add backtest_engine.py metrics.py test_harness.py
git commit -m "feat: 체결가 기록 + 왕복 거래 통계 추가"
```

---

### Task 3: 리포트 확장 — 트레이드 통계 블록 + 일별 손익

**Files:**
- Modify: `print_summary.py`
- Modify: `test_harness.py`

**Interfaces:**
- Consumes: Task 2의 `metrics.trade_stats`, `result.trades["fill_price"]`
- Produces:
  - `print_summary(result: BacktestResult) -> None` — 트레이드 통계 블록 포함
  - `to_daily_summary(df, result) -> pd.DataFrame` — 컬럼 `max_book_size`, `max_holdings`, `end_of_day_equity`, `daily_pnl`, `trade_count`

- [ ] **Step 1: `test_harness.py`에 실패하는 테스트를 추가한다**

임포트에 추가:

```python
from print_summary import to_daily_summary
```

테스트 추가:

```python
def test_daily_summary_일별_손익():
    # 이틀치 데이터. 하루가 넘어갈 때 그날의 손익이 누적이 아니라
    # '그날 번 돈'으로 나와야 한다.
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01 09:00", "2026-01-01 09:01",
            "2026-01-02 09:00", "2026-01-02 09:01",
        ]),
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [100.0, 110.0, 110.0, 130.0],
        "low":  [100.0, 110.0, 110.0, 130.0],
        "close": [100.0, 110.0, 110.0, 130.0],
        "volume": [1.0] * 4,
    })
    # 첫 봉에 매수하고 계속 보유 -> 평가손익만 움직인다.
    signal = pd.Series([1, 0, 0, 0], index=df.index)
    result = run_backtest(df, signal, buy_slippage=0.0, sell_slippage=0.0)

    daily = to_daily_summary(df, result)
    assert "daily_pnl" in daily.columns
    # 1일차 마감 누적 +10, 2일차 마감 누적 +30 -> 2일차의 그날 손익은 +20
    assert abs(daily["daily_pnl"].iloc[0] - 10.0) < 1e-9
    assert abs(daily["daily_pnl"].iloc[1] - 20.0) < 1e-9
    # 누적 컬럼은 그대로 살아 있어야 한다
    assert abs(daily["end_of_day_equity"].iloc[1] - 30.0) < 1e-9
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_harness.py`
Expected: FAIL — `AssertionError` (daily_pnl 컬럼 없음)

- [ ] **Step 3: `print_summary.py`의 임포트를 고친다**

파일 상단 임포트를 아래로 교체한다:

```python
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# BacktestResult를 실제로 임포트한다. 지금까지는 임포트 없이 타입 힌트로만
# 써 왔는데, Python 3.14의 지연 annotation 평가(PEP 649) 덕에 우연히 동작했을
# 뿐이라 하위 버전에서는 NameError가 난다.
from backtest_engine import BacktestResult
from metrics import sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio, trade_stats
```

- [ ] **Step 4: `print_summary`의 "Portfolio Metrics" 블록을 교체한다**

```python
    # Portfolio Metrics
    print(f"Max Book Size    : {result.max_book_size:,.0f}원")
    print(f"신호 발생 횟수     : {result.trade_count:,}회")
    print("-" * 50)

    # 거래 단위 통계 — '이 전략이 한 번 들어가서 몇 % 먹고 나오나'를 본다.
    # 위쪽의 Sharpe/MDD는 자본 곡선 기준이라 답하는 질문이 다르다.
    stats = trade_stats(result.trades)
    print(f"왕복 거래 수       : {stats['round_trips']:,}회")
    print(f"승률              : {stats['win_rate']:.1%}")
    print(f"평균 수익률        : {stats['avg_return']:+.3%}  (표준편차 {stats['std_return']:.3%})")
    print(f"평균 이익 / 손실   : {stats['avg_win']:+.3%} / {stats['avg_loss']:+.3%}")
    print(f"손익비 (PF)       : {stats['profit_factor']:.2f}")
    print(f"평균 보유 봉 수    : {stats['avg_holding_bars']:.1f}봉")
    if stats["open_position"]:
        print(f"미청산            : {stats['open_position']}주 (마지막 봉 기준 보유 중)")
    print("-" * 50)
```

- [ ] **Step 5: `to_daily_summary`에 `daily_pnl`을 추가한다**

`.groupby("date").agg(...)` 호출 다음, `if not result.trades.empty:` 앞에 삽입한다:

```python
    # 그날 '번 돈'. end_of_day_equity는 누적이라 하루 성과가 안 보인다.
    # 첫날은 이전 날이 없으므로 마감 누적을 그대로 그날의 손익으로 본다.
    daily["daily_pnl"] = daily["end_of_day_equity"].diff().fillna(
        daily["end_of_day_equity"].iloc[0]
    )
```

- [ ] **Step 6: 테스트 통과를 확인한다**

Run: `python test_harness.py`
Expected: PASS — 13개 통과

- [ ] **Step 7: 커밋**

```bash
git add print_summary.py test_harness.py
git commit -m "feat: 리포트에 거래 통계와 일별 손익 추가"
```

---

### Task 4: 골든 스냅샷 + 단순 전략 3종 마이그레이션

전략을 `entries`/`exits`로 옮길 때 **신호가 한 비트도 달라지면 안 된다.** 먼저 현재 신호를 실데이터로 떠서 저장하고, 옮긴 뒤 동일한지 비교한다.

**Files:**
- Create: `snapshot_signals.py`
- Create: `tests_golden/` (스냅샷 저장 디렉터리)
- Modify: `strategies/mean_reversion/bollinger_band.py`
- Modify: `strategies/mean_reversion/rsi_reversion.py`
- Modify: `strategies/session_based/session_close.py`

**Interfaces:**
- Consumes: Task 1의 `Strategy.entries`/`exits`/`warmup`
- Produces: `snapshot_signals.capture(name, strategy, df) -> None`, `snapshot_signals.verify(name, strategy, df) -> bool`

- [ ] **Step 1: `snapshot_signals.py`를 만든다**

```python
"""
전략 신호의 골든 스냅샷 도구.

리팩터링(예: holding 루프를 entries/exits로 옮기기) 전에 현재 신호를 실데이터로
떠 두고, 리팩터링 후 완전히 동일한지 비교한다. 수익성을 검증하는 게 아니라
'행동이 바뀌지 않았음'을 보장하는 것이 목적이다.

사용법:
    python snapshot_signals.py capture    # 리팩터링 전에 실행
    python snapshot_signals.py verify     # 리팩터링 후에 실행
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import scrap

SNAPSHOT_DIR = Path(__file__).parent / "tests_golden"
TICKER = "005930"
INTERVAL = "1m"


def _load():
    """스냅샷 기준 데이터. 매번 같은 구간을 써야 비교가 의미 있다."""
    df = scrap.load_candles(TICKER, INTERVAL)
    if df.empty:
        raise RuntimeError(
            f"{TICKER} {INTERVAL} 데이터가 없습니다. "
            f"먼저 `python scrap.py {TICKER} --interval {INTERVAL}`를 실행하세요."
        )
    return df.reset_index(drop=True)


def _path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.npy"


def capture(name: str, strategy, df: pd.DataFrame) -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    signal = strategy.generate_signals(df)
    np.save(_path(name), signal.to_numpy(dtype=np.int8))
    nonzero = int((signal != 0).sum())
    print(f"  저장  {name}: {len(signal)}봉, 신호 {nonzero}개")


def verify(name: str, strategy, df: pd.DataFrame) -> bool:
    expected = np.load(_path(name))
    actual = strategy.generate_signals(df).to_numpy(dtype=np.int8)

    if len(expected) != len(actual):
        print(f"  실패  {name}: 길이가 다름 {len(expected)} -> {len(actual)}")
        return False

    diff = np.flatnonzero(expected != actual)
    if len(diff):
        print(f"  실패  {name}: {len(diff)}개 봉에서 신호가 다름 (첫 위치 {diff[0]}, "
              f"기대 {expected[diff[0]]} 실제 {actual[diff[0]]})")
        return False

    print(f"  통과  {name}: {len(actual)}봉 완전 일치")
    return True


def _cases():
    """스냅샷을 뜰 (이름, 전략 인스턴스) 목록. 마이그레이션 대상 전부."""
    from strategies.mean_reversion.bollinger_band import BollingerBandStrategy
    from strategies.mean_reversion.rsi_reversion import RsiReversionStrategy
    from strategies.session_based.session_close import SessionCloseStrategy
    from strategies.session_based.opening import OpeningRangeStrategy
    from strategies.trend_following.ema_cross_with_adx import EmaCrossStrategyWithADX

    return [
        ("bollinger", BollingerBandStrategy(period=20, num_std=2.0)),
        ("rsi", RsiReversionStrategy(period=14, oversold=30, exit_level=50)),
        ("session_close", SessionCloseStrategy()),
        ("opening", OpeningRangeStrategy(market_open_time="09:29")),
        ("adx", EmaCrossStrategyWithADX(fast=6, slow=12, atr_period=20)),
    ]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    df = _load()
    print(f"{TICKER} {INTERVAL}, {len(df)}봉 기준\n")

    if mode == "capture":
        for name, strategy in _cases():
            capture(name, strategy, df)
        print("\n스냅샷 저장 완료. 리팩터링 후 `python snapshot_signals.py verify`로 확인하세요.")
        return 0

    ok = all([verify(name, strategy, df) for name, strategy in _cases()])
    print("\n전부 일치" if ok else "\n불일치 발생 — 리팩터링이 행동을 바꿨습니다")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 마이그레이션 전 스냅샷을 뜬다**

Run: `python snapshot_signals.py capture`
Expected: 5개 전략의 스냅샷이 `tests_golden/`에 저장되고 각 줄에 봉 수와 신호 개수가 출력된다. 이 시점에는 아직 어떤 전략도 수정하지 않았다.

- [ ] **Step 3: 스냅샷을 커밋한다 (비교 기준선 고정)**

```bash
git add snapshot_signals.py tests_golden/
git commit -m "test: 전략 신호 골든 스냅샷 기준선 추가"
```

- [ ] **Step 4: `bollinger_band.py`를 `entries`/`exits`로 옮긴다**

파일 전체를 아래로 교체한다:

```python
from ..base import Strategy
import pandas as pd


class BollingerBandStrategy(Strategy):
    """
    볼린저 밴드 기반 평균회귀 전략.
    종가가 하단 밴드를 이탈(터치)하면 매수하고,
    중심선(이동평균) 또는 상단 밴드로 회귀하면 매도한다.
    """

    def __init__(self, period=20, num_std=2.0, exit_at_middle=True):
        self.period = period
        self.num_std = num_std
        self.exit_at_middle = exit_at_middle  # True: 중심선에서 청산 / False: 상단 밴드에서 청산

        # rolling 창이 다 차기 전에는 밴드가 NaN이라 신호를 내면 안 된다.
        self.warmup = period

    def _bands(self, df: pd.DataFrame):
        """중심선/상단/하단을 한 번에 계산한다. entries와 exits가 같이 쓴다."""
        close = df["close"]
        mid = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        return mid, mid + self.num_std * std, mid - self.num_std * std

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 하단 밴드 이하로 하락 = 과매도, 평균 회귀를 기대
        _, _, lower = self._bands(df)
        return df["close"] <= lower

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 종가가 청산 기준선(중심선 또는 상단 밴드) 이상으로 회복
        mid, upper, _ = self._bands(df)
        target = mid if self.exit_at_middle else upper
        return df["close"] >= target
```

- [ ] **Step 5: `rsi_reversion.py`를 `entries`/`exits`로 옮긴다**

`_rsi` 메서드는 그대로 두고, `__init__`과 `generate_signals`를 아래로 교체한다:

```python
    def __init__(self, period=14, oversold=30, exit_level=50):
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level

        # RSI가 익기 전(min_periods 미충족) 구간은 신호를 내지 않는다.
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] RSI가 과매도 구간에 진입
        return self._rsi(df["close"]) <= self.oversold

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] RSI가 중립선(exit_level)까지 회복
        return self._rsi(df["close"]) >= self.exit_level
```

- [ ] **Step 6: `session_close.py`를 `entries`/`exits`로 옮긴다**

파일 전체를 아래로 교체한다:

```python
from ..base import Strategy
import pandas as pd


class SessionCloseStrategy(Strategy):
    """
    정규장 마감(15:30) 종가 매수 -> 연장세션(20:00) 종가 매도.
    당일 청산, 오버나잇 보유 없음.
    """

    def __init__(self, entry_time="15:30:00", exit_time="20:00:00"):
        self.entry_time = pd.to_datetime(entry_time).time()
        self.exit_time = pd.to_datetime(exit_time).time()

    def _times(self, df: pd.DataFrame):
        if "timestamp" not in df.columns:
            raise ValueError("df에 'timestamp' 컬럼이 필요합니다.")
        ts = pd.to_datetime(df["timestamp"])
        return ts.dt.time, ts.dt.date

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 15:30 봉
        t, _ = self._times(df)
        return t == self.entry_time

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 20:00 봉.
        #
        # 여기에 '그날의 마지막 봉'을 OR로 더한 것은 안전장치다. 어떤 이유로든
        # 20:00 봉이 그날 데이터에 없으면 포지션이 다음 날로 넘어가 버리는데,
        # 이 전략은 오버나잇을 하지 않기로 되어 있다.
        #
        # 미보유 상태의 청산 조건은 to_signals가 어차피 무시하므로, 예전 코드처럼
        # holding 여부를 여기서 따질 필요가 없다.
        t, date = self._times(df)
        is_last_bar_of_day = date != date.shift(-1)   # 다음 행의 날짜가 다르면 그날 마지막 봉
        is_last_bar_of_day.iloc[-1] = True            # 데이터 전체의 마지막 봉도 포함
        return (t == self.exit_time) | is_last_bar_of_day
```

- [ ] **Step 7: 신호가 완전히 동일한지 확인한다**

Run: `python snapshot_signals.py verify`
Expected: 5줄 전부 "통과 ... 완전 일치", 마지막 줄 "전부 일치". (`opening`과 `adx`는 아직 마이그레이션 전이라 당연히 통과한다.)

불일치가 나면 스냅샷이 옳다 — 마이그레이션한 조건식을 고친다. 특히 `session_close`의 `is_last_bar_of_day`가 원본의 `date.iloc[i] != date.iloc[i+1]`과 같은지 확인할 것.

- [ ] **Step 8: 하네스 자체 검사도 통과하는지 확인한다**

Run: `python test_harness.py`
Expected: PASS — 13개 통과

- [ ] **Step 9: 커밋**

```bash
git add strategies/mean_reversion/bollinger_band.py strategies/mean_reversion/rsi_reversion.py strategies/session_based/session_close.py
git commit -m "refactor: 볼린저/RSI/세션마감 전략을 entries·exits로 이전"
```

---

### Task 5: 인덱스·성능 이슈가 있는 전략 2종 마이그레이션

**Files:**
- Modify: `strategies/session_based/opening.py`
- Modify: `strategies/trend_following/ema_cross_with_adx.py`

**Interfaces:**
- Consumes: Task 1의 `Strategy.entries`/`exits`/`warmup`, Task 4의 `snapshot_signals.verify`
- Produces: 없음 (기존 클래스명·생성자 시그니처 유지)

- [ ] **Step 1: `opening.py`를 옮기면서 인덱스 버그를 고친다**

파일 전체를 아래로 교체한다:

```python
from ..base import Strategy
import pandas as pd


class OpeningRangeStrategy(Strategy):
    """
    정규장 시작 직전 매수 -> 개장 N분 후 매도 전략.

    실제로는 09:00 이전(동시호가)에 주문을 넣어도 체결은 09:00 시가에 이루어지므로,
    '개장 캔들'을 매수 신호, '개장 + hold_minutes 캔들'을 매도 신호로 표시하는
    방식으로 구현했다.

    ※ 전제조건: 분봉 데이터 필요. 일봉으로는 의미 있는 백테스트가 불가능하다.
    """

    def __init__(self, market_open_time="09:30", hold_minutes=30, match_tolerance_minutes=5):
        self.market_open_time = pd.to_datetime(market_open_time).time()
        self.hold_minutes = hold_minutes
        self.match_tolerance_minutes = match_tolerance_minutes  # 목표 시각 캔들이 없을 때 허용 오차

    def _marks(self, df: pd.DataFrame):
        """
        날짜별로 진입/청산 봉을 찾아 두 개의 불리언 Series로 만든다.

        예전 구현은 df를 DatetimeIndex로 갈아끼운 뒤 그 인덱스를 가진 Series를
        반환했다. 그런데 엔진에 들어가는 df는 정수 인덱스라 인덱스가 어긋난 채였고,
        run_backtest가 .iloc으로 접근한 덕분에 우연히 동작하고 있었을 뿐이다.
        여기서는 df의 원래 인덱스를 그대로 유지한다.
        """
        if "timestamp" not in df.columns:
            raise ValueError("df에 'timestamp' 컬럼이 필요합니다.")

        ts = pd.to_datetime(df["timestamp"])
        entry_flags = pd.Series(False, index=df.index)
        exit_flags = pd.Series(False, index=df.index)
        tolerance = pd.Timedelta(minutes=self.match_tolerance_minutes)

        for trade_date, positions in ts.groupby(ts.dt.date).groups.items():
            day_ts = ts.loc[positions].sort_values()

            open_target = pd.Timestamp.combine(trade_date, self.market_open_time)
            exit_target = open_target + pd.Timedelta(minutes=self.hold_minutes)

            # 인덱스가 tz-aware면 target도 동일 타임존으로 맞춰준다 (tz_convert 아님!)
            tz = day_ts.dt.tz
            if tz is not None:
                open_target = open_target.tz_localize(tz)
                exit_target = exit_target.tz_localize(tz)

            entry_at = self._first_at_or_after(day_ts, open_target, tolerance)
            exit_at = self._first_at_or_after(day_ts, exit_target, tolerance)

            # 둘 중 하나라도 못 찾았거나 순서가 뒤집혔으면 그날은 거래하지 않는다
            if entry_at is None or exit_at is None or exit_at <= entry_at:
                continue

            entry_flags.loc[entry_at] = True
            exit_flags.loc[exit_at] = True

        return entry_flags, exit_flags

    @staticmethod
    def _first_at_or_after(day_ts: pd.Series, target: pd.Timestamp, tolerance: pd.Timedelta):
        """target 시각 이후 가장 가까운 봉의 '인덱스 라벨'을 tolerance 이내에서 찾는다."""
        candidates = day_ts[day_ts >= target]
        if candidates.empty:
            return None
        if candidates.iloc[0] - target <= tolerance:
            return candidates.index[0]
        return None

    def entries(self, df: pd.DataFrame) -> pd.Series:
        return self._marks(df)[0]

    def exits(self, df: pd.DataFrame) -> pd.Series:
        return self._marks(df)[1]
```

- [ ] **Step 2: `ema_cross_with_adx.py`를 옮기면서 O(n²) 루프를 제거한다**

파일 전체를 아래로 교체한다:

```python
from ..base import Strategy
import pandas as pd


class EmaCrossStrategyWithADX(Strategy):
    """
    EMA 크로스에 변동성 필터를 얹은 전략.
    ATR 백분위가 그동안의 평균 이상일 때(= 시장이 충분히 움직일 때)만 매매한다.
    """

    def __init__(self, fast=6, slow=12, atr_period=20):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period

        # EMA와 ATR 둘 다 익어야 신호를 낼 수 있다.
        self.warmup = max(slow, atr_period)

    def _indicators(self, df: pd.DataFrame):
        """크로스 전환과 변동성 필터를 한 번에 계산한다."""
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()

        # 정배열이면 +1, 역배열이면 -1. 그 값의 diff가 0이 아닌 지점이 크로스다.
        raw_state = pd.Series(0, index=df.index)
        raw_state[ema_fast > ema_slow] = 1
        raw_state[ema_fast < ema_slow] = -1
        transition = raw_state.diff().fillna(0)

        tr = (df["high"] - df["low"]).shift(1).fillna(0)
        atr = tr.ewm(span=self.atr_period).mean()

        # patr: '지금까지 본 ATR 중 현재 ATR이 상위 몇 %인가'.
        #   expanding()을 쓰는 이유는 미래를 보지 않기 위해서다. 전체 구간에
        #   rank(pct=True)를 걸면 아직 오지 않은 봉의 ATR까지 순위에 반영되어
        #   lookahead bias가 생긴다.
        #
        #   예전 구현은 매 봉마다 atr.iloc[:i+1].rank()를 새로 계산하는 O(n^2)
        #   중첩 루프였다. expanding().rank()가 정확히 같은 값을 한 번에 낸다.
        patr = atr.expanding().rank(pct=True)

        # 기준선은 '직전 봉까지의 patr 평균'. shift(1)로 현재 봉을 제외한다
        # (예전 구현의 patr.iloc[:i].mean()과 동일). 첫 봉은 비교 대상이 없어 0.
        patr_mean = patr.expanding().mean().shift(1).fillna(0.0)

        return transition, patr, patr_mean

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 변동성이 평균 이상인 상태에서 골든크로스
        transition, patr, patr_mean = self._indicators(df)
        return (patr >= patr_mean) & (transition > 0)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 변동성이 평균 이상인 상태에서 데드크로스
        transition, patr, patr_mean = self._indicators(df)
        return (patr >= patr_mean) & (transition < 0)
```

- [ ] **Step 3: 신호가 완전히 동일한지 확인한다**

Run: `python snapshot_signals.py verify`
Expected: 5개 전부 "통과 ... 완전 일치", 마지막 줄 "전부 일치".

`adx`가 불일치하면 `expanding().rank(pct=True)`가 원본의 `atr.iloc[:i+1].rank(pct=True).iloc[-1]`과 동치인지, `patr_mean`의 `shift(1)`이 원본의 `patr.iloc[:i].mean()`과 맞는지 확인한다. 스냅샷이 기준이다.

- [ ] **Step 4: 속도가 실제로 개선됐는지 확인한다**

Run: `python -c "import time,scrap; from strategies.trend_following.ema_cross_with_adx import EmaCrossStrategyWithADX; df=scrap.load_candles('005930','1m').reset_index(drop=True); t=time.perf_counter(); EmaCrossStrategyWithADX().generate_signals(df); print(f'{time.perf_counter()-t:.2f}초, {len(df)}봉')"`
Expected: 1초 미만. 이전 O(n²) 루프는 수만 봉에서 수십 초가 걸렸다.

- [ ] **Step 5: 커밋**

```bash
git add strategies/session_based/opening.py strategies/trend_following/ema_cross_with_adx.py
git commit -m "refactor: 개장/ADX 전략을 entries·exits로 이전"
```

---

### Task 6: 전략 레지스트리 + 파라미터 그리드

**Files:**
- Modify: `strategies/__init__.py`
- Create: `grids.py`
- Modify: `test_harness.py`

**Interfaces:**
- Consumes: 마이그레이션된 전략 클래스들
- Produces:
  - `strategies.REGISTRY: dict[str, type]` — 클래스명 → 클래스
  - `grids.GRIDS: dict[str, dict]` — 클래스명 → 파라미터 그리드
  - `grids.VALID: dict[str, callable]` — 클래스명 → 무효 조합 필터

- [ ] **Step 1: `test_harness.py`에 실패하는 테스트를 추가한다**

임포트 추가:

```python
import strategies
from grids import GRIDS, VALID
```

테스트 추가:

```python
def test_registry_전략을_이름으로_찾을_수_있다():
    # CLI가 "EmaCrossStrategy" 같은 문자열로 클래스를 찾아야 한다.
    assert "EmaCrossStrategy" in strategies.REGISTRY
    assert "BollingerBandStrategy" in strategies.REGISTRY
    # 베이스 클래스 자체는 실행 대상이 아니므로 들어 있으면 안 된다.
    assert "Strategy" not in strategies.REGISTRY
    # 레지스트리에 담긴 건 인스턴스가 아니라 클래스여야 한다.
    assert isinstance(strategies.REGISTRY["EmaCrossStrategy"], type)


def test_grids_키는_전부_실재하는_전략():
    # 오타난 클래스명이 grids.py에 남아 있으면 --optimize가 조용히 건너뛴다.
    for name in GRIDS:
        assert name in strategies.REGISTRY, f"REGISTRY에 없는 전략: {name}"
    for name in VALID:
        assert name in GRIDS, f"VALID에만 있고 GRIDS에 없는 전략: {name}"


def test_grids_파라미터명이_생성자와_일치():
    # 그리드 키가 __init__ 인자와 다르면 grid_search가 TypeError로 죽는다.
    import inspect
    for name, grid in GRIDS.items():
        params = inspect.signature(strategies.REGISTRY[name].__init__).parameters
        for key in grid:
            assert key in params, f"{name}에 없는 파라미터: {key}"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python test_harness.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'grids'`

- [ ] **Step 3: `strategies/__init__.py`에 `REGISTRY`를 추가한다**

`__all__` 초기값 줄을 아래로 바꾼다:

```python
__all__ = ["Strategy", "REGISTRY"]

# 이름 -> 클래스. CLI가 "EmaCrossStrategy" 같은 문자열로 전략을 찾을 때 쓴다.
REGISTRY: dict[str, type] = {}
```

수집 루프의 `__all__.append(name)` 다음 줄에 등록을 추가한다:

```python
            REGISTRY[name] = obj
            # 이름으로 찾을 수 있게 레지스트리에도 넣는다 (run.py가 사용).
```

- [ ] **Step 4: `grids.py`를 만든다**

```python
"""
전략별 파라미터 탐색 범위.

run.py --optimize가 여기를 보고 그리드서치를 돌린다. 전략 코드는 순수하게
유지하고 '어디를 뒤질지'는 이 파일 한 곳에 모은다.

여기에 없는 전략은 --optimize를 줘도 조용히 기본 파라미터 1회 실행으로
넘어간다. 탐색할 게 없는 전략(예: 시간 기반)은 그게 맞는 동작이다.

범위를 넓힐수록 조합 수가 곱셈으로 늘어난다. fast 11개 x slow 10개 =
110회 백테스트인데, 여기에 세 번째 축을 곱하면 금방 수천 회가 된다.
"""

GRIDS: dict[str, dict] = {
    "EmaCrossStrategy": {
        "fast": range(5, 60, 5),
        "slow": range(20, 120, 10),
    },
    "EmaCrossStrategyWithADX": {
        "fast": range(5, 30, 5),
        "slow": range(20, 80, 10),
        "atr_period": [10, 20, 30],
    },
    "BollingerBandStrategy": {
        "period": [10, 20, 30, 40],
        "num_std": [1.5, 2.0, 2.5, 3.0],
    },
    "RsiReversionStrategy": {
        "period": [7, 14, 21],
        "oversold": [20, 25, 30, 35],
        "exit_level": [45, 50, 55, 60],
    },
}

# 무효한 조합을 걸러내는 함수. 여기 없는 전략은 모든 조합을 다 시도한다.
VALID: dict[str, callable] = {
    # 단기선이 장기선보다 짧아야 크로스가 의미를 갖는다
    "EmaCrossStrategy": lambda p: p["fast"] < p["slow"],
    "EmaCrossStrategyWithADX": lambda p: p["fast"] < p["slow"],
    # 과매도 기준이 청산 기준보다 낮아야 왕복이 성립한다
    "RsiReversionStrategy": lambda p: p["oversold"] < p["exit_level"],
}
```

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `python test_harness.py`
Expected: PASS — 16개 통과

- [ ] **Step 6: 커밋**

```bash
git add strategies/__init__.py grids.py test_harness.py
git commit -m "feat: 전략 레지스트리와 파라미터 그리드 추가"
```

---

### Task 7: CLI `run.py`

**Files:**
- Create: `run.py`
- Delete: `backtest.py`, `run_optimize.py`, `test.py`, `test1.py`

**Interfaces:**
- Consumes: `strategies.REGISTRY`, `grids.GRIDS`/`VALID`, `optimize.grid_search`, `backtest_engine.run_backtest`, `metrics.*`, `print_summary.*`, `validation.walk_forward_split`
- Produces: CLI 진입점. 다른 모듈이 임포트하지 않는다.

- [ ] **Step 1: `run.py`를 만든다**

```python
"""
백테스팅 CLI. 실행 · 자동 최적화 · 전략 비교를 전부 여기서 한다.

    python run.py EmaCrossStrategy --ticker 005930
    python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
    python run.py --all --ticker 005930 000660 035420 --optimize

예전에는 backtest.py와 run_optimize.py 본문을 직접 고쳐 가며 돌렸다.
이 파일이 그 둘을 대체한다.
"""
import argparse
import os

import pandas as pd

import scrap
import strategies
from backtest_engine import run_backtest
from grids import GRIDS, VALID
from metrics import sharpe_ratio, max_drawdown, trade_stats
from optimize import grid_search
from print_summary import print_summary, plot_backtest, to_daily_summary
from validation import walk_forward_split

GRAPH_DIR = os.path.join(os.path.dirname(__file__), "graph")


def run_one(name: str, ticker: str, interval: str, optimize: bool, metric: str):
    """
    전략 하나를 종목 하나에 돌린다.

    --optimize면 train 구간에서 그리드서치를 돌려 최적 파라미터를 고르고,
    그 파라미터를 test 구간(out-of-sample)에 그대로 적용한다. 이렇게 해야
    '파라미터를 맞춰 놓고 같은 데이터로 자랑하는' 자기기만을 피할 수 있다.

    반환: (test 구간 df, BacktestResult, 사용한 파라미터 dict, 그리드서치 순위표 or None)
    """
    strategy_cls = strategies.REGISTRY[name]

    df = scrap.load_candles(ticker, interval)
    if df.empty:
        raise SystemExit(
            f"{ticker} {interval} 데이터가 없습니다. "
            f"먼저 `python scrap.py {ticker} --interval {interval}`를 실행하세요."
        )
    df = df.reset_index(drop=True)
    train, test = walk_forward_split(df)

    params: dict = {}
    leaderboard = None

    if optimize and name in GRIDS:
        opt = grid_search(
            train,
            strategy_factory=strategy_cls,
            param_grid=GRIDS[name],
            metric=metric,
            valid_combo=VALID.get(name),
        )
        params = opt.best_params
        leaderboard = opt.leaderboard

    # 그리드가 없으면 params가 빈 dict라 생성자 기본값이 그대로 쓰인다.
    strategy = strategy_cls(**params)
    signal = strategy.generate_signals(test)
    result = run_backtest(test, signal)

    return test, result, params, leaderboard


def cmd_single(args):
    """전략 하나를 자세히 본다."""
    name = args.strategy
    ticker = args.ticker[0]

    test, result, params, leaderboard = run_one(
        name, ticker, args.interval, args.optimize, args.metric
    )

    print(f"\n{name} / {ticker} / {args.interval}")
    if leaderboard is not None:
        print(f"\n[ train 그리드서치 상위 10개 — 기준: {args.metric} ]")
        print(leaderboard.head(10).to_string(index=False))
        print(f"\n최적 파라미터: {params}")
        print("\n아래는 이 파라미터를 test 구간(out-of-sample)에 적용한 결과입니다.")
    elif args.optimize:
        print(f"(grids.py에 {name}의 탐색 범위가 없어 기본 파라미터로 실행합니다)")

    print()
    print_summary(result)

    if args.daily:
        print("\n[ 일별 요약 ]")
        print(to_daily_summary(test, result).to_string())

    if args.plot:
        os.makedirs(GRAPH_DIR, exist_ok=True)
        suffix = "_opt" if leaderboard is not None else ""
        path = os.path.join(GRAPH_DIR, f"{name}_{ticker}_{args.interval}{suffix}.png")
        plot_backtest(test, result, f"{name} / {ticker}").savefig(path, dpi=120)
        print(f"\n그래프 저장: {path}")


def cmd_compare(args):
    """전략 x 종목을 전부 돌려 한 장의 순위표로 낸다."""
    rows = []

    for name in sorted(strategies.REGISTRY):
        for ticker in args.ticker:
            try:
                _, result, params, _ = run_one(
                    name, ticker, args.interval, args.optimize, args.metric
                )
            except Exception as exc:
                # 한 전략이 죽어도 나머지 비교는 계속되어야 한다.
                # (예: 시간 기반 전략에 일봉을 물린 경우)
                print(f"  건너뜀  {name} / {ticker}: {type(exc).__name__}: {exc}")
                continue

            stats = trade_stats(result.trades)
            rows.append({
                "전략": name,
                "종목": ticker,
                "샤프": round(sharpe_ratio(result.returns), 2),
                "MDD": round(max_drawdown(result.equity_curve), 4),
                "승률": round(stats["win_rate"], 3),
                "왕복": stats["round_trips"],
                "순손익": round(result.equity_curve.iloc[-1], 0),
                "벤치마크": round(result.benchmark_pnl, 0),
                "파라미터": params or "기본값",
            })

    if not rows:
        raise SystemExit("실행된 조합이 없습니다.")

    table = pd.DataFrame(rows).sort_values("샤프", ascending=False).reset_index(drop=True)
    print("\n[ 비교 결과 — test 구간(out-of-sample) 기준, 샤프 내림차순 ]")
    print(table.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description="백테스팅 실행 / 최적화 / 비교",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예시:\n"
               "  python run.py EmaCrossStrategy --ticker 005930\n"
               "  python run.py BollingerBandStrategy --ticker 005930 --optimize --plot --daily\n"
               "  python run.py --all --ticker 005930 000660 --optimize",
    )
    parser.add_argument("strategy", nargs="?",
                        help=f"전략 클래스명. 가능: {', '.join(sorted(strategies.REGISTRY))}")
    parser.add_argument("--all", action="store_true", help="등록된 전략 전부를 돌려 순위표로 비교")
    parser.add_argument("--ticker", nargs="+", default=["005930"], help="종목 코드 (여러 개 가능)")
    parser.add_argument("--interval", default="1m", help="봉 주기 (기본: 1m)")
    parser.add_argument("--optimize", action="store_true",
                        help="grids.py 범위로 train 그리드서치 후 test에 적용")
    parser.add_argument("--metric", default="sharpe",
                        choices=["sharpe", "sortino", "calmar", "mdd"],
                        help="최적화 기준 (기본: sharpe)")
    parser.add_argument("--plot", action="store_true", help="graph/에 그래프 저장")
    parser.add_argument("--daily", action="store_true", help="일별 요약표 출력")
    args = parser.parse_args()

    if args.all:
        return cmd_compare(args)

    if not args.strategy:
        parser.error("전략명을 주거나 --all을 쓰세요.")
    if args.strategy not in strategies.REGISTRY:
        parser.error(f"모르는 전략: {args.strategy}\n"
                     f"가능: {', '.join(sorted(strategies.REGISTRY))}")

    return cmd_single(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 단일 실행을 확인한다**

Run: `python run.py EmaCrossStrategy --ticker 005930`
Expected: 요약 리포트가 출력되고, 승률·평균 수익률·손익비·평균 보유 봉 수 줄이 보인다.

- [ ] **Step 3: 자동 최적화 흐름을 확인한다**

Run: `python run.py BollingerBandStrategy --ticker 005930 --optimize --daily`
Expected: train 그리드서치 상위 10개 표 → 최적 파라미터 → test 구간 요약 → 일별 요약표(`daily_pnl` 컬럼 포함) 순으로 출력된다.

- [ ] **Step 4: 비교 모드를 확인한다**

Run: `python run.py --all --ticker 005930 000660`
Expected: 전략 × 종목 조합이 샤프 내림차순 표 한 장으로 나온다. 실패한 조합은 "건너뜀" 줄로 표시되고 나머지는 계속 진행된다.

- [ ] **Step 5: 그래프 저장을 확인한다**

Run: `python run.py EmaCrossStrategy --ticker 005930 --plot`
Expected: `graph/EmaCrossStrategy_005930_1m.png`가 생성된다.

- [ ] **Step 6: 대체된 스크립트를 삭제한다**

```bash
git rm backtest.py run_optimize.py test.py test1.py
```

`test.py`와 `test1.py`는 테스트가 아니라 `pkgutil` 동작을 확인하던 스크래치 파일이다. `backtest.py`와 `run_optimize.py`는 `run.py`가 완전히 대체한다.

- [ ] **Step 7: 커밋**

```bash
git add run.py
git commit -m "feat: 통합 CLI run.py 추가, 구 실행 스크립트 삭제"
```

---

### Task 8: 문서 갱신 + 최종 확인

**Files:**
- Modify: `CLAUDE.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1-7 전부
- Produces: 없음

- [ ] **Step 1: `.gitignore`를 갱신한다**

```
.env
__pycache__/
*.pyc
```

이미 커밋된 `.pyc`는 인덱스에서 뺀다:

```bash
git rm -r --cached __pycache__ strategies/__pycache__ strategies/mean_reversion/__pycache__ strategies/session_based/__pycache__ strategies/trend_following/__pycache__
```

- [ ] **Step 2: `CLAUDE.md`의 Commands 절을 갱신한다**

기존 명령 블록과 그 아래 두 문단을 아래로 교체한다:

    프레임워크 없음. 빌드/린트 파이프라인도 없고 `requirements.txt`도 없다 (pandas, numpy, requests, python-dotenv, matplotlib이 전역 설치되어 있다).

    ```bash
    python scrap.py 005930 000660 --interval 1m        # 캔들 수집 → market_data.db (증분)
    python run.py EmaCrossStrategy --ticker 005930      # 단일 백테스트
    python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
    python run.py --all --ticker 005930 000660          # 전략 × 종목 순위표
    python test_harness.py                              # 하네스 자체 검사 (assert 기반)
    python snapshot_signals.py verify                   # 전략 신호가 안 바뀌었는지 확인
    ```

    `run.py`가 실행·최적화·비교를 모두 담당한다. 파일을 열어 고칠 필요 없이 플래그로 제어한다. `--optimize`는 `grids.py`의 탐색 범위로 train 그리드서치를 돌린 뒤 그 파라미터를 test 구간에 적용해 out-of-sample로 보고한다.

- [ ] **Step 3: "신호는 상태가 아니라 이벤트다" 문단을 교체한다**

    **신호는 상태가 아니라 이벤트다.** `run_backtest`는 1이 나올 때마다 무조건 1주를 더 산다 — 보유량 상한이 없다. 그래서 `Strategy` 베이스가 `to_signals()`로 상태머신을 한 번만 구현하고, 전략은 `entries(df)` / `exits(df)` 불리언 조건식만 쓴다. 중복 진입 차단과 워밍업 절단은 베이스가 처리한다.

    쿨다운·트레일링 스톱처럼 진짜 순차 상태가 필요한 전략만 `generate_signals`를 직접 오버라이드한다 (`ema_cross_with_atr`가 유일한 예). 그 경우 중복 진입은 스스로 막아야 한다.

    동시 신호 규칙: 미보유면 진입이 이기고, 보유 중이면 청산이 이긴다. 마지막 봉에서 강제 청산하지 않으며, 미청산 포지션은 왕복 거래로 집계하지 않고 리포트에 따로 표시한다.

- [ ] **Step 4: "워밍업 구간" 문단을 교체한다**

    **워밍업 구간**: 지표 기반 전략은 `__init__`에서 `self.warmup`을 설정한다 (보통 가장 긴 지표 기간). `ewm`과 `rolling`은 초기 구간이 신뢰할 수 없어 베이스가 그만큼 신호를 0으로 누른다.

- [ ] **Step 5: `print_summary` 함정 문단을 삭제한다**

Task 3에서 `BacktestResult`를 명시적으로 임포트했으므로 "`print_summary.py`는 `BacktestResult`를 import하지 않는다" 문단은 더 이상 사실이 아니다. 통째로 지운다.

- [ ] **Step 6: "리포 위생" 절을 갱신한다**

    ## 리포 위생

    `.gitignore`가 `.env`와 `__pycache__/`를 막는다. 14MB `market_data.db`는 여전히 커밋되어 있다.

- [ ] **Step 7: 전체 검사를 돌린다**

Run: `python test_harness.py && python snapshot_signals.py verify && python run.py --all --ticker 005930`
Expected: 16개 통과 → 5개 신호 전부 일치 → 순위표 출력. 세 단계 모두 오류 없이 끝난다.

- [ ] **Step 8: 커밋**

```bash
git add CLAUDE.md .gitignore
git commit -m "docs: CLAUDE.md를 새 하네스에 맞게 갱신"
```

---

## 미해결 관찰 (이번 범위 밖) — 이후 해결됨

`strategies/trend_following/ema_cross_with_atr.py`는 `patr = atr.rank(pct=True)`와 `patr_threshold = patr.mean()`을 썼다. 둘 다 **전체 구간**에 걸친 계산이라 아직 오지 않은 봉의 ATR을 순위와 평균에 반영하는 lookahead bias였다.

계획 수립 시점에는 범위 밖으로 두었으나, 실행 후 사용자 승인을 받아 커밋 `517da9f`에서 `expanding()`으로 수정했다. test 구간 성과 변화: 005930은 변동 없음(달라진 14봉이 전부 train 구간), 000660은 승률 50.0% → 37.5%, 순손익 146,632원 → 140,365원.

같은 커밋에서 MDD/Calmar가 `-inf`/`nan`으로 나오던 문제도 별도로 수정했다(`6f1cbd8`). 자세한 내용은 `CLAUDE.md`를 볼 것.
