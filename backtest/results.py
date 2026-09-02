"""
백테스트 결과의 일 단위 캐시. 새로 붙은 봉만 계산해서 기존 결과에 이어붙인다.

왜 있나:
  전략 41개 × 종목 50개면 2050 조합이고, 매번 처음부터 돌리면 시간의 대부분이
  run_backtest의 파이썬 루프에서 나간다(8600봉에 0.21~0.25초).
  그런데 그 루프는 순수한 순차 시뮬레이션이고, 한 봉에서 다음 봉으로 넘어가는
  상태가 '보유 수량'과 '누적 실현현금' 둘뿐이다. 그래서 하루가 끝날 때마다 그
  둘을 저장해 두면, 새 봉이 붙었을 때 마지막 저장 지점부터 새 날짜만 돌려도
  처음부터 돌린 것과 정확히 같은 숫자가 나온다.

  실측(2종목 × 41전략): 콜드 37초 → 웜 6초. 남은 6초는 대부분 신호 계산이다.
  신호는 캐시하지 않는다 — ewm·expanding·obv가 사실상 기억이 무한이라 뒤쪽만
  떼어 계산하면 값이 달라지고, 어차피 전략당 4~40밀리초라 아낄 게 없다.

두 가지 출력 (요청받은 두 갈래):
  results.db        기계용. 날짜 단위 누적 손익·보유·체결 기록. 증분 갱신의 재료.
  results/report.md 사람용 요약. 캐시에서 만들므로 백테스트를 다시 돌리지 않는다.
  results/detail.csv 사람용 상세. 전략 × 종목 전 조합.

캐시 단위가 왜 하필 '거래일'인가:
  walk_forward_split이 비율(70/30)이라 봉이 늘면 분할 지점이 앞으로 밀린다.
  분할 지점을 경계로 저장하면 어제 캐시가 오늘 캐시의 앞부분이 아니게 되어
  애초에 이어붙지 않는다. 날짜는 봉이 늘어도 뒤로 밀리지 않는 유일한 경계다.
  그래서 저장은 날짜로 하고, train/test 분할은 저장할 때가 아니라 **읽을 때**
  날짜 목록을 잘라서 한다. 분할 비율을 바꿔도 캐시는 그대로 재사용된다.

알고 써야 할 세 가지:
  1. 샤프·소르티노는 일별이 아니라 **봉 단위**다. 손익의 합·제곱합을 날짜별로
     저장해 두고 읽을 때 평균·분산을 복원한다 — 셋 다 가산적이라 날짜로 접어도
     값이 손상되지 않는다. 일별 수익률로 내면 표본이 8600개에서 12개(현재 보유
     데이터 기준)로 줄어 숫자가 의미를 잃는다.
  2. **MDD만 정확하지 않다.** 봉마다 누적 최고점을 들고 있어야 정확한데 그러면
     캐시할 이유가 없어진다. 하루 안에서 고점이 저점보다 먼저 왔다고 가정한
     '상한'을 낸다 — 실제 낙폭은 이보다 얕거나 같다.
  3. 전 구간을 끊지 않고 이어서 돌리므로 train에서 들고 있던 포지션이 test 시작
     시점에 그대로 넘어온다. run.py는 test 슬라이스를 무포지션에서 시작하므로
     같은 전략·같은 종목이라도 run.py와 숫자가 완전히 같지는 않다.

사용법:
    python results.py                             # 전 종목 × 전 전략 증분 갱신 + 리포트
    python results.py --ticker 005930 000660
    python results.py --strategy PivotPointStrategy --ticker 005930
    python results.py --report-only               # 계산 없이 캐시로 리포트만 다시 씀
    python results.py --selfcheck                 # 증분 = 전량 재계산인지 검증
"""
import argparse
import inspect
import json
import os
import sqlite3
import time
from functools import lru_cache

import pandas as pd

from data import candles
import strategies
from data import tickers
from backtest.engine import run_backtest
from backtest.metrics import trade_stats

BASE = os.path.dirname(os.path.abspath(__file__))   # backtest/
ROOT = os.path.dirname(BASE)                        # 리포 루트
DB_PATH = os.path.join(ROOT, "results.db")
OUT_DIR = os.path.join(ROOT, "results")

BUY_SLIPPAGE = 0.00015
SELL_SLIPPAGE = 0.00215

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily (
    strategy  TEXT NOT NULL,
    params    TEXT NOT NULL,   -- json.dumps(sort_keys=True). 기본 파라미터는 '{}'
    ticker    TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    date      TEXT NOT NULL,   -- 'YYYY-MM-DD'
    fp        REAL NOT NULL,   -- 소스 지문. 코드가 바뀌면 이 행은 버려진다
    equity    REAL NOT NULL,   -- 그날 마지막 봉의 누적 손익 (비용 차감 후)
    gross     REAL NOT NULL,   -- 같은 것, 비용 차감 전. 그래서 비용 = gross - equity
    holdings  INTEGER NOT NULL,-- 그날 마지막 봉의 보유 수량 (이어받을 상태 1/2)
    close     REAL NOT NULL,   -- 그날 종가 (실현현금을 되돌리는 데 쓴다, 상태 2/2)
    max_book  REAL NOT NULL,   -- 그날 안에서의 최대 평가금액
    bars      INTEGER NOT NULL,-- 그날 봉 수. 아래 합계들의 표본 수 n이다
    -- 봉 단위 손익의 합·제곱합. 평균과 분산은 이 둘과 n만 있으면 복원되고,
    -- 셋 다 날짜를 가로질러 그냥 더하면 되므로 일 단위로 접어도 샤프가 봉
    -- 해상도 그대로 나온다. 이게 없으면 표본이 8600개에서 12개로 줄어든다.
    ret_sum   REAL NOT NULL,
    ret_sq    REAL NOT NULL,
    neg_n     INTEGER NOT NULL, -- 손실 봉만 따로. 소르티노의 하방편차용
    neg_sum   REAL NOT NULL,
    neg_sq    REAL NOT NULL,
    eq_max    REAL NOT NULL,   -- 그날 안에서의 누적손익 최고/최저. MDD 상한용
    eq_min    REAL NOT NULL,
    trades    TEXT NOT NULL,   -- 그날 체결 기록 JSON 배열
    PRIMARY KEY (strategy, params, ticker, timeframe, date)
)
"""

# 스키마를 고치면 옛 DB는 컬럼이 없어 조회가 죽는다. 버전을 박아 두고 다르면
# 통째로 버린다 — 캐시는 언제든 다시 만들 수 있으니 마이그레이션은 사치다.
SCHEMA_VERSION = 2


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        conn.execute("DROP TABLE IF EXISTS daily")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute(SCHEMA)
    return conn


@lru_cache(maxsize=None)
def _candles(ticker: str, interval: str) -> pd.DataFrame:
    """
    한 프로세스 안에서 같은 종목을 41번 다시 읽지 않도록 캐싱한다.
    load_candles가 0.13초라 전 전략 스윕에서는 이것만으로도 크게 준다.
    반환된 DataFrame을 호출자가 변형하면 안 된다 (같은 객체를 공유한다).
    """
    return candles.load_candles(ticker, interval).reset_index(drop=True)


@lru_cache(maxsize=None)
def _day_labels(ticker: str, interval: str) -> pd.Series:
    """
    봉마다의 'YYYY-MM-DD' 문자열. 종목당 한 번만 만들어 전 전략이 나눠 쓴다.

    dt.strftime이 행당 10마이크로초쯤 걸려서, 8600봉 × 전략 41개면 이것만으로
    3초가 넘게 나간다. 캔들과 마찬가지로 전략이 바뀌어도 값은 같으니 캐싱한다.
    """
    return _candles(ticker, interval)["timestamp"].dt.strftime("%Y-%m-%d")


@lru_cache(maxsize=None)
def _fingerprint(name: str) -> float:
    """
    전략 소스가 바뀌었는데 옛날 숫자를 계속 보는 사고를 막는 지문.

    전략 자기 파일과, 거의 모든 전략이 물고 있는 공용 모듈(지표·베이스·엔진)의
    수정 시각 중 가장 최근 것을 쓴다. 내용 해시가 아니라 mtime인 이유는 싸기
    때문이다 — 내용이 같은데 저장만 다시 한 경우 헛되이 재계산하지만, 그 대가는
    '고친 코드로 옛날 결과를 보는 것'보다 압도적으로 싸다.
    """
    files = [
        inspect.getfile(strategies.REGISTRY[name]),
        os.path.join(ROOT, "strategies", "indicators.py"),
        os.path.join(ROOT, "strategies", "base.py"),
        os.path.join(BASE, "engine.py"),
    ]
    # 없는 파일을 조용히 건너뛰면 안 된다. 경로가 틀어진 채로도 지문이 계산되어
    # 코드를 고쳐도 캐시가 영영 무효화되지 않고, 옛날 결과를 새 결과로 착각하게
    # 된다. 파일이 옮겨지면 여기서 바로 터지는 편이 낫다.
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise RuntimeError(f"지문 계산에 필요한 파일이 없습니다: {missing}")
    return max(os.path.getmtime(f) for f in files)


# ---------------------------------------------------------------- 증분 계산

def evaluate(name: str, ticker: str, interval: str = "1m",
             params: dict | None = None, conn: sqlite3.Connection | None = None,
             rebuild: bool = False) -> pd.DataFrame:
    """
    전략 하나 × 종목 하나를 전 구간에 대해 평가하고, 날짜 단위 결과를 돌려준다.

    캐시가 있으면 저장되지 않은 날짜만 계산해서 이어붙인다. 결과는 처음부터
    돌린 것과 정확히 같다 (--selfcheck가 이걸 검증한다).

    반환: date, equity, gross, holdings, close, max_book, bars, trades 컬럼의
          DataFrame. 데이터가 없으면 빈 DataFrame.
    """
    cls = strategies.REGISTRY[name]
    params = params or {}
    pkey = json.dumps(params, sort_keys=True)
    fp = _fingerprint(name)
    key = (name, pkey, ticker, interval)

    df = _candles(ticker, interval)
    if df.empty:
        return pd.DataFrame()

    own = conn is None
    conn = conn or connect()
    try:
        days = _day_labels(ticker, interval)
        all_days = days.drop_duplicates().tolist()

        keep = _load_cached(conn, key, fp) if not rebuild else pd.DataFrame()

        # 마지막으로 저장된 날은 장중에 수집된 반쪽일 수 있다. 무조건 버리고
        # 다시 돈다 — 하루치 재계산은 싸고, 반쪽 하루를 완성분으로 믿는 건 비싸다.
        if len(keep):
            keep = keep.iloc[:-1]

        # 캐시가 데이터의 앞부분과 정확히 일치하지 않으면(과거 봉이 뒤늦게
        # 보충됐거나 하는 경우) 이어붙일 근거가 없으니 통째로 버린다.
        if len(keep) and keep["date"].tolist() != all_days[:len(keep)]:
            keep = keep.iloc[0:0]

        if len(keep) >= len(all_days):      # 위에서 한 날을 잘라냈으니 보통 안 온다
            return keep.reset_index(drop=True)

        start_day = all_days[len(keep)]
        start_pos = int(days.searchsorted(start_day))

        # 신호는 항상 전 구간에서 계산한다. ewm·expanding·obv는 사실상 기억이
        # 무한이라 뒤쪽만 떼어 계산하면 값이 달라진다. 어차피 0.03초라 아낄 게 없다.
        signal = cls(**params).generate_signals(df)

        tail = df.iloc[start_pos:].reset_index(drop=True)
        tail_signal = signal.iloc[start_pos:].reset_index(drop=True)

        # 이어받을 상태 복원. equity = 누적실현현금 + 보유수량 × 종가 이므로
        # 종가로 평가금액을 빼면 누적 실현현금이 나온다.
        if len(keep):
            prev = keep.iloc[-1]
            h0 = int(prev["holdings"])
            cash0 = float(prev["equity"]) - h0 * float(prev["close"])
            gross_cash0 = float(prev["gross"]) - h0 * float(prev["close"])
        else:
            h0, cash0, gross_cash0 = 0, 0.0, 0.0

        res = run_backtest(tail, tail_signal, buy_slippage=BUY_SLIPPAGE,
                           sell_slippage=SELL_SLIPPAGE, holdings0=h0)

        prev_equity = float(keep["equity"].iloc[-1]) if len(keep) else 0.0
        tail_days = days.iloc[start_pos:].reset_index(drop=True)
        fresh = _fold_days(tail, tail_days, res, start_pos, cash0, gross_cash0,
                           prev_equity)
        _save(conn, key, fp, fresh)

        return pd.concat([keep, fresh], ignore_index=True)
    finally:
        if own:
            conn.close()


def _fold_days(tail: pd.DataFrame, day: pd.Series, res, start_pos: int,
               cash0: float, gross_cash0: float, prev_equity: float) -> pd.DataFrame:
    """
    봉 단위 백테스트 결과를 날짜 단위로 접는다.

    누적값(equity/gross/holdings/close)은 그날 마지막 봉의 값을 그대로 들고,
    최대·최소는 그날 안의 극값을 든다. 손익의 합·제곱합은 날짜를 넘어 그냥
    더해지므로, 읽을 때 이걸로 봉 단위 평균·표준편차를 정확히 복원한다.
    """
    equity = res.equity_curve + cash0
    # 봉 손익. 첫 봉은 diff가 NaN이라 직전 날 종가 시점의 누적손익과의 차로 메운다.
    # 이 한 칸을 빠뜨리면 날짜 경계마다 손익이 하나씩 사라진다.
    pnl = equity.diff()
    pnl.iloc[0] = equity.iloc[0] - prev_equity
    neg = pnl.where(pnl < 0, 0.0)

    frame = pd.DataFrame({
        "date": day,
        "equity": equity,
        "gross": res.gross_equity_curve + gross_cash0,
        "holdings": res.holdings,
        "close": tail["close"],
        "book": res.holdings * tail["close"],
        "pnl": pnl,
        "pnl_sq": pnl ** 2,
        "is_neg": (pnl < 0).astype(int),
        "neg": neg,
        "neg_sq": neg ** 2,
    })
    agg = frame.groupby("date", sort=True).agg(
        equity=("equity", "last"),
        gross=("gross", "last"),
        holdings=("holdings", "last"),
        close=("close", "last"),
        # 전 구간 최대 평가금액 = 날짜별 최대들의 최대. 접어도 정확하다.
        max_book=("book", "max"),
        bars=("equity", "size"),
        ret_sum=("pnl", "sum"),
        ret_sq=("pnl_sq", "sum"),
        neg_n=("is_neg", "sum"),
        neg_sum=("neg", "sum"),
        neg_sq=("neg_sq", "sum"),
        eq_max=("equity", "max"),
        eq_min=("equity", "min"),
    ).reset_index()

    by_day: dict[str, list] = {}
    if not res.trades.empty:
        tr = res.trades.copy()
        # position은 tail 안의 상대 위치다. 그래서 그대로 day를 되짚을 수 있고
        # (여기서 strftime을 다시 돌리면 체결 많은 전략에서 그만큼 손해다),
        # 되짚은 뒤에는 전 구간 기준 절대 봉 번호로 바꿔 둔다 — 캐시에 남는 값은
        # 여러 번의 실행에 걸쳐 이어 붙으므로 기준이 전 구간이어야 trade_stats가
        # 보유 봉수를 제대로 센다.
        tr["day"] = day.to_numpy()[tr["position"].to_numpy()]
        tr["position"] = tr["position"] + start_pos
        for d, g in tr.groupby("day"):
            by_day[d] = g[["position", "side", "price", "fill_price"]].to_dict("records")

    agg["trades"] = [json.dumps(by_day.get(d, [])) for d in agg["date"]]
    return agg


_COLS = ["date", "equity", "gross", "holdings", "close", "max_book", "bars",
         "ret_sum", "ret_sq", "neg_n", "neg_sum", "neg_sq", "eq_max", "eq_min",
         "trades"]
_INT_COLS = {"holdings", "bars", "neg_n"}


def _load_cached(conn, key, fp) -> pd.DataFrame:
    rows = conn.execute(
        f"SELECT {', '.join(_COLS)} FROM daily "
        "WHERE strategy=? AND params=? AND ticker=? AND timeframe=? AND fp=? "
        "ORDER BY date", (*key, fp)).fetchall()
    out = pd.DataFrame(rows, columns=_COLS)
    # sqlite에서 나온 행은 object dtype이라 이어붙인 뒤 산술이 파이썬 객체 연산이
    # 된다. 여기서 숫자 컬럼을 눌러 두면 아래 집계가 전부 numpy 경로를 탄다.
    for c in _COLS:
        if c not in ("date", "trades"):
            out[c] = pd.to_numeric(out[c])
    return out


def _save(conn, key, fp, rows: pd.DataFrame) -> None:
    # 지문이 다른 옛 행은 여기서 치운다. 놔두면 DB만 계속 부푼다.
    conn.execute("DELETE FROM daily WHERE strategy=? AND params=? AND ticker=? "
                 "AND timeframe=? AND fp<>?", (*key, fp))
    cols = ", ".join(_COLS)
    holes = ", ".join("?" * (5 + len(_COLS)))   # 키 4 + fp 1 + 값들
    conn.executemany(
        f"INSERT OR REPLACE INTO daily "
        f"(strategy, params, ticker, timeframe, fp, {cols}) VALUES ({holes})",
        [(*key, fp, *(int(v) if c in _INT_COLS else v
                      for c, v in zip(_COLS, row)))
         for row in rows[_COLS].itertuples(index=False, name=None)])
    conn.commit()


# ---------------------------------------------------------------- 지표 집계

def summarize(daily: pd.DataFrame, span: str = "test",
              train_ratio: float = 0.7, periods_per_year: int = 252) -> dict | None:
    """
    일 단위 캐시에서 지표를 낸다. span: 'test' | 'train' | 'full'.

    분할은 날짜 목록을 비율로 자른다. 봉 수가 아니라 날짜 수 기준이라 run.py의
    분할 지점과 정확히 같지는 않다 (하루 중간을 자르지 않으니 이쪽이 더 낫다).

    샤프·소르티노는 저장해 둔 합·제곱합으로 **봉 단위** 통계를 복원해서 낸다.
    일별로 접힌 12개 점으로 내면 표본이 모자라 숫자가 무의미해지기 때문이다.
    periods_per_year=252는 run.py와 맞춘 값이지 실제 연간 봉 수가 아니다 —
    전략끼리 줄 세우는 데만 쓰고 절대값에 의미를 두지 마라.
    """
    if daily is None or len(daily) < 2:
        return None

    cut = int(len(daily) * train_ratio)
    part = {"train": daily.iloc[:cut], "test": daily.iloc[cut:],
            "full": daily}[span]
    if len(part) < 2:
        return None

    # 구간 시작 시점의 누적 손익을 0으로 재기준한다. 그래야 test 구간의 순손익이
    # 'test에서 번 돈'이 된다 (train에서 번 돈이 딸려 오지 않는다).
    base_i = part.index[0] - 1
    has_base = base_i in daily.index
    base = float(daily["equity"].loc[base_i]) if has_base else 0.0
    gross_base = float(daily["gross"].loc[base_i]) if has_base else 0.0

    equity = part["equity"].astype(float) - base
    capital = float(part["max_book"].max())
    if capital <= 0:                    # 한 번도 보유하지 않은 경우
        capital = float(part["close"].iloc[0])

    # 봉 단위 통계 복원. 합계가 원화 손익이라 capital로 나눠 수익률로 만든다.
    # 샤프는 평균/표준편차라 capital이 약분되지만, 표기를 통일하려고 나눠 둔다.
    n = int(part["bars"].sum())
    mean = float(part["ret_sum"].sum()) / n / capital
    var = float(part["ret_sq"].sum()) / n / capital ** 2 - mean ** 2
    std = _sample_std(var, n)

    neg_n = int(part["neg_n"].sum())
    neg_mean = float(part["neg_sum"].sum()) / neg_n / capital if neg_n else 0.0
    neg_var = (float(part["neg_sq"].sum()) / neg_n / capital ** 2 - neg_mean ** 2
               if neg_n else 0.0)
    neg_std = _sample_std(neg_var, neg_n)

    ann = periods_per_year ** 0.5
    sharpe = mean / std * ann if std > 0 else 0.0
    sortino = mean / neg_std * ann if neg_std > 0 else 0.0

    # MDD는 '상한'이다. 하루 안에서 고점이 저점보다 먼저 왔다고 가정하고 계산한다
    # (그 반대면 실제 낙폭은 이보다 얕다). 봉 단위 낙폭을 정확히 내려면 봉마다
    # 누적 최고점을 들고 있어야 해서 캐시의 존재 이유가 사라진다.
    run_max = (part["eq_max"].astype(float) - base).cummax()
    mdd = float(((part["eq_min"].astype(float) - base - run_max) / capital).min())
    mdd = min(mdd, 0.0)

    trades = _part_trades(part)
    stats = trade_stats(trades)

    net = float(equity.iloc[-1])
    cost = float(part["gross"].iloc[-1] - gross_base) - net
    entry = float(part["close"].iloc[0]) * (1 + BUY_SLIPPAGE)
    exit_ = float(part["close"].iloc[-1]) * (1 - SELL_SLIPPAGE)
    total_return = net / capital

    return {
        "days": len(part),
        "bars": n,
        "sharpe": sharpe,
        "sortino": sortino,
        "mdd": mdd,
        # 칼마는 연율화 수익률 / MDD. metrics.calmar_ratio는 봉 수로 연율화하는데
        # 여기서는 거래일 수를 쓴다 (연 252 거래일 기준이 읽기 쉽다).
        "calmar": (((1 + total_return) ** (252 / len(part)) - 1) / abs(mdd)
                   if mdd < 0 and total_return > -1 else 0.0),
        "net_pnl": net,
        "return_pct": total_return,
        "gross_return_pct": (net + cost) / capital,
        "cost_pct": cost / capital,
        "capital": capital,
        "benchmark_pct": (exit_ - entry) / entry,
        **stats,
    }


def _sample_std(var: float, n: int) -> float:
    """
    합·제곱합에서 나온 모분산(ddof=0)을 pandas와 같은 표본표준편차(ddof=1)로
    바꾼다. 부동소수 오차로 var가 아주 작은 음수가 되는 경우가 있어 0으로 눌러야
    sqrt에서 nan이 나오지 않는다.
    """
    if n < 2 or var <= 0:
        return 0.0
    return (var * n / (n - 1)) ** 0.5


def _part_trades(part: pd.DataFrame) -> pd.DataFrame:
    """
    구간 안의 체결만 모아 평평한 표로 돌려준다.

    맨 앞의 매도는 버린다. 그 매수는 이전 구간에서 일어났으므로 짝이 없고,
    그대로 두면 trade_stats의 FIFO 짝짓기가 한 칸씩 밀려 엉뚱한 승률이 나온다.
    """
    recs = []
    for blob in part["trades"]:
        recs.extend(json.loads(blob))
    while recs and recs[0]["side"] == "sell":
        recs.pop(0)
    return pd.DataFrame(recs, columns=["position", "side", "price", "fill_price"])


# ---------------------------------------------------------------- 리포트

def sweep(names, tickers_, interval, conn, rebuild=False, span="test") -> pd.DataFrame:
    """전략 × 종목 전 조합을 증분 평가하고 지표 한 줄씩 쌓는다."""
    rows, t0 = [], time.time()
    total = len(names) * len(tickers_)
    done = 0

    for name in names:
        for ticker in tickers_:
            done += 1
            try:
                daily = evaluate(name, ticker, interval, conn=conn, rebuild=rebuild)
                stats = summarize(daily, span=span)
            except Exception as exc:
                print(f"  건너뜀  {name} / {ticker}: {type(exc).__name__}: {exc}")
                continue
            if stats is None:
                continue
            rows.append({"전략": name, "종목": ticker,
                         "종목명": tickers.KOSPI50.get(ticker, ""), **stats})
        print(f"  [{done}/{total}] {name}  ({time.time() - t0:.1f}s)", flush=True)

    return pd.DataFrame(rows)


def _block(text: str) -> str:
    """표를 코드펜스로 감싼다. to_markdown은 tabulate를 끌어오는데 이 리포에
    없는 의존성이고, 열 폭이 고정된 코드블록이 콘솔·에디터 어디서든 더 잘 읽힌다."""
    return "\n".join(["```", text, "```"])


def write_report(detail: pd.DataFrame, interval: str, span: str) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "detail.csv")
    md_path = os.path.join(OUT_DIR, "report.md")

    detail.to_csv(csv_path, index=False, encoding="utf-8-sig", float_format="%.6f")

    # 전략별로 종목을 가로질러 접는다. 평균이 아니라 중앙값을 쓰는 이유는 한
    # 종목에서 크게 터진 값이 전략 전체를 대표하는 것처럼 보이지 않게 하려는 것이다.
    g = detail.groupby("전략")
    summary = pd.DataFrame({
        "종목수": g.size(),
        "샤프중앙": g["sharpe"].median(),
        "수익중앙%": g["return_pct"].median() * 100,
        "비용전%": g["gross_return_pct"].median() * 100,
        "비용%": g["cost_pct"].median() * 100,
        "양수비율": g["return_pct"].apply(lambda s: (s > 0).mean()),
        "MDD중앙": g["mdd"].median(),
        "왕복중앙": g["round_trips"].median(),
        "승률중앙": g["win_rate"].median(),
    }).sort_values("수익중앙%", ascending=False)

    span_label = {"test": "test 구간(out-of-sample)", "train": "train 구간",
                  "full": "전 구간"}[span]
    bench = detail.groupby("종목")["benchmark_pct"].first().median() * 100

    lines = [
        "# 백테스트 결과",
        "",
        f"- 생성: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- 구간: {span_label} / 봉 주기 {interval} / 기본 파라미터",
        f"- 전략 {summary.shape[0]}개 × 종목 {detail['종목'].nunique()}개",
        f"- 매수·보유 벤치마크(종목 중앙값): {bench:+.2f}%",
        "",
        "> 샤프·소르티노는 봉 단위 수익률 기준이다(합·제곱합을 날짜별로 저장해 복원).",
        "> 연율화 252는 run.py와 맞춘 값이지 실제 연간 봉 수가 아니다 — 줄 세우는 데만 써라.",
        "> MDD는 상한이다. 장중 고점이 저점보다 먼저 왔다고 가정하므로 실제 낙폭은 이보다 얕다.",
        "> train에서 들고 있던 포지션이 test로 넘어오므로 run.py 숫자와 완전히 같지는 않다.",
        "",
        "## 전략 순위 (종목 중앙값, 수익 내림차순)",
        "",
        _block(summary.round(4).to_string()),
        "",
        "## 상위 5개 전략의 종목별 상세",
        "",
    ]

    cols = ["종목", "종목명", "sharpe", "return_pct", "cost_pct", "mdd",
            "round_trips", "win_rate", "net_pnl"]
    for name in summary.head(5).index:
        part = detail[detail["전략"] == name][cols]
        part = part.sort_values("return_pct", ascending=False)
        lines += [f"### {name}", "",
                  _block(part.round(4).to_string(index=False)), ""]

    lines += ["## 전체 상세", "",
              "종목별 전 조합은 `results/detail.csv`에 있다 "
              f"({len(detail)}행, 엑셀에서 바로 열린다).", ""]

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n리포트: {md_path}")
    print(f"상세  : {csv_path}")


# ---------------------------------------------------------------- 자체 검증

def selfcheck(name="PivotPointStrategy", ticker="005930", interval="1m") -> None:
    """
    증분 계산이 전량 재계산과 같은 결과를 내는지 확인한다.

    앞쪽 날짜만 캐시에 심어 둔 뒤 이어서 돌린 결과와, 캐시 없이 처음부터 돌린
    결과를 비교한다. 이 등식이 깨지면 캐시 전체가 거짓말이 되므로 여기가
    이 파일에서 유일하게 반드시 통과해야 하는 지점이다.
    """
    tmp = os.path.join(OUT_DIR, "_selfcheck.db")
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(tmp):
        os.remove(tmp)

    conn = connect(tmp)
    df = _candles(ticker, interval)
    assert not df.empty, f"{ticker} {interval} 데이터가 없다"

    full = evaluate(name, ticker, interval, conn=conn, rebuild=True)
    assert len(full) > 5, f"거래일이 너무 적어 검증할 수 없다 ({len(full)}일)"

    # 앞 절반만 남기고 지운 뒤, 나머지를 증분으로 채우게 한다.
    half = full["date"].iloc[len(full) // 2]
    conn.execute("DELETE FROM daily WHERE date > ?", (half,))
    conn.commit()
    incr = evaluate(name, ticker, interval, conn=conn)
    conn.close()
    os.remove(tmp)

    assert full["date"].tolist() == incr["date"].tolist(), "날짜 목록이 다르다"
    for col in ("equity", "gross", "holdings", "max_book", "bars",
                "ret_sum", "ret_sq", "neg_n", "neg_sum", "neg_sq",
                "eq_max", "eq_min"):
        a = full[col].astype(float).to_numpy()
        b = incr[col].astype(float).to_numpy()
        worst = abs(a - b).max()
        assert worst < 1e-6, f"{col}이 어긋난다 (최대 {worst})"
    assert full["trades"].tolist() == incr["trades"].tolist(), "체결 기록이 다르다"

    # 지표는 값 비교를 부동소수 오차 허용으로 한다. 이어받기가 누적 실현현금을
    # 뺄셈으로 복원하는 탓에 마지막 몇 비트가 연속 실행과 달라질 수 있다.
    s_full, s_incr = summarize(full), summarize(incr)
    for k, v in s_full.items():
        w = s_incr[k]
        assert abs(v - w) < 1e-9 * max(1.0, abs(v)), f"{k}이 다르다 ({v} vs {w})"

    # 접어 놓은 합계로 복원한 샤프가, 봉 시계열에서 직접 낸 샤프와 같은지 본다.
    # 캐시의 핵심 주장이 '접어도 봉 해상도가 유지된다'이므로 여기서 확인한다.
    from metrics import sharpe_ratio
    sig = strategies.REGISTRY[name]().generate_signals(df)
    res = run_backtest(df, sig, buy_slippage=BUY_SLIPPAGE, sell_slippage=SELL_SLIPPAGE)
    capital = summarize(full, span="full")["capital"]
    direct = sharpe_ratio(res.equity_curve.diff().fillna(res.equity_curve.iloc[0])
                          / capital)
    folded = summarize(full, span="full")["sharpe"]
    assert abs(direct - folded) < 1e-6, f"샤프가 접히며 손상됐다 ({direct} vs {folded})"

    print(f"selfcheck 통과: {name} / {ticker} / {len(full)}일 "
          f"(증분 {len(full) - len(full) // 2}일 재계산, "
          f"봉 단위 샤프 복원 오차 {abs(direct - folded):.2e})")


# ---------------------------------------------------------------- CLI

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", nargs="+", help="기본: 등록된 전략 전부")
    p.add_argument("--ticker", nargs="+", help="기본: tickers.KOSPI50 전부")
    p.add_argument("--interval", default="1m")
    p.add_argument("--span", default="test", choices=["test", "train", "full"],
                   help="리포트에 쓸 구간 (기본: test)")
    p.add_argument("--rebuild", action="store_true", help="캐시를 무시하고 전부 다시 계산")
    p.add_argument("--report-only", action="store_true",
                   help="계산 없이 캐시에 있는 것만으로 리포트를 다시 쓴다")
    p.add_argument("--selfcheck", action="store_true", help="증분 = 전량 재계산 검증")
    args = p.parse_args()

    if args.selfcheck:
        return selfcheck(interval=args.interval)

    names = args.strategy or sorted(strategies.REGISTRY)
    codes = args.ticker or list(tickers.KOSPI50)

    conn = connect()
    try:
        if args.report_only:
            # 캐시에 실제로 들어 있는 조합만 추린다.
            have = {(s, t) for s, t in conn.execute(
                "SELECT DISTINCT strategy, ticker FROM daily WHERE timeframe=?",
                (args.interval,))}
            names = [n for n in names if any((n, t) in have for t in codes)]
            codes = [t for t in codes if any((n, t) in have for n in names)]
            if not names:
                raise SystemExit("캐시가 비어 있다. --report-only 없이 먼저 돌려라.")

        detail = sweep(names, codes, args.interval, conn,
                       rebuild=args.rebuild, span=args.span)
    finally:
        conn.close()

    if detail.empty:
        raise SystemExit("평가된 조합이 없다.")

    write_report(detail, args.interval, args.span)

    top = detail.groupby("전략")["return_pct"].median().sort_values(ascending=False)
    print("\n[ 수익 중앙값 상위 5 ]")
    print((top.head(5) * 100).round(2).to_string())


if __name__ == "__main__":
    main()
