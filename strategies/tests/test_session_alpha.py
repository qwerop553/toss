# -*- coding: utf-8 -*-
"""
새로 추가한 세션 기반 전략 5개의 자기검사. 프레임워크 없이 assert만 쓴다.

    python strategies/tests/test_session_alpha.py

여기서 보는 것은 수익성이 아니라 '규칙이 규칙대로 도는가'다. 수익성은
backtest.results가 종목을 가로질러 판단한다.

가장 중요한 검사는 truncation invariance(잘라도 같은가)다. 데이터를 k봉에서
끊고 다시 신호를 만들었을 때 앞의 k-1봉 신호가 그대로여야 한다. 하나라도
달라지면 그 전략은 아직 오지 않은 봉을 보고 현재 신호를 정한 것이다 —
백테스트 성과만 좋아지고 실전에서는 재현되지 않는 전형적인 lookahead다.
(마지막 봉은 제외한다. is_last_bar_of_day가 '데이터의 끝 = 그날의 끝'으로
보고 강제 청산을 내는 것은 의도된 동작이다.)
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from strategies import (AfternoonOversoldStrategy, AfternoonRangeBottomStrategy,
                        GapDownOpenFadeStrategy, AfternoonVwapRecoveryStrategy,
                        GapUpFadeRecoveryStrategy)
from strategies import indicators as ind

STRATEGIES = [AfternoonOversoldStrategy(), AfternoonRangeBottomStrategy(),
              GapDownOpenFadeStrategy(), AfternoonVwapRecoveryStrategy(),
              GapUpFadeRecoveryStrategy()]


def make_df(days=6, bars=390, seed=0):
    """09:00~15:29 분봉을 days일치 만든다. 갭·추세가 섞이도록 난수를 쓴다."""
    rng = np.random.default_rng(seed)
    rows, price = [], 50000.0
    for day in range(days):
        start = pd.Timestamp("2026-01-05 09:00") + pd.Timedelta(days=day)
        price *= 1 + rng.normal(0, 0.006)          # 오버나잇 갭
        for b in range(bars):
            price *= 1 + rng.normal(0, 0.0006)
            hi = price * (1 + abs(rng.normal(0, 0.0004)))
            lo = price * (1 - abs(rng.normal(0, 0.0004)))
            rows.append((start + pd.Timedelta(minutes=b), price, hi, lo, price,
                         float(rng.integers(100, 10000))))
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    # open은 직전 종가로 이어 붙인다(첫 봉만 자기 종가). 갭 계산이 의미를 갖도록.
    df["open"] = df["close"].shift(1).fillna(df["close"])
    return df


def test_helpers():
    df = make_df(days=3, bars=10)
    bar_no = ind.bar_of_day(df)
    assert list(bar_no[:10]) == list(range(10)), "bar_of_day가 날짜마다 리셋되지 않는다"
    assert bar_no.iloc[10] == 0

    op = ind.day_open(df)
    assert (op[:10] == df["open"].iloc[0]).all(), "day_open이 당일 시가로 채워지지 않는다"
    assert op.iloc[10] == df["open"].iloc[10]
    assert op.index.equals(df.index), "day_open의 인덱스가 df와 다르다"


def test_no_lookahead():
    """데이터를 잘라도 앞부분 신호가 그대로여야 한다."""
    df = make_df(days=5, seed=1)
    for strat in STRATEGIES:
        full = strat.generate_signals(df)
        for k in (700, 1300, 1750):          # 하루 경계, 장중, 오후 한복판
            part = strat.generate_signals(df.iloc[:k].copy())
            a, b = full.iloc[:k - 1].to_numpy(), part.iloc[:k - 1].to_numpy()
            bad = np.flatnonzero(a != b)
            assert len(bad) == 0, (
                f"{type(strat).__name__}: {k}봉에서 자르니 {bad[:5]}번 신호가 달라진다 "
                "— 미래 봉을 보고 있다")


def test_no_overnight_and_single_round_trip():
    """
    오버나잇 금지(다섯 전략 공통) + 하루 한 왕복 상한.

    AfternoonVwapRecoveryStrategy만 상한에서 뺀다. 이 전략은 VWAP 이탈을 손절로
    쓰기 때문에 같은 날 다시 VWAP 위로 올라오면 재진입하는 것이 설계 의도다.
    나머지 넷은 청산 조건이 '그날 마지막 봉'뿐이라 하루 한 번을 넘길 수 없고,
    넘긴다면 to_signals의 중복 진입 차단이 깨진 것이다.
    """
    df = make_df(days=6, seed=2)
    dates = ind.bar_dates(df)
    for strat in STRATEGIES:
        sig = strat.generate_signals(df)
        holding = sig.cumsum()
        assert holding.min() >= 0 and holding.max() <= 1, \
            f"{type(strat).__name__}: 보유량이 0/1을 벗어난다"
        # 마지막 날은 데이터가 거기서 끝나 청산 신호가 나므로 함께 검사해도 된다
        reentry_ok = isinstance(strat, AfternoonVwapRecoveryStrategy)
        for d, idx in df.groupby(dates).groups.items():
            day_sig = sig.loc[idx]
            assert day_sig.sum() == 0, \
                f"{type(strat).__name__}: {d}에 미청산 포지션이 남아 다음 날로 넘어간다"
            if not reentry_ok:
                assert (day_sig == 1).sum() <= 1, \
                    f"{type(strat).__name__}: {d}에 두 번 이상 진입했다"


def test_entry_window():
    """진입은 설정한 순번 구간 안에서만 일어나야 한다."""
    df = make_df(days=8, seed=3)
    bar_no = ind.bar_of_day(df)
    for strat in STRATEGIES:
        buys = bar_no[strat.generate_signals(df) == 1]
        if buys.empty:
            continue
        lo = getattr(strat, "after_bar", getattr(strat, "entry_from", 0))
        hi = getattr(strat, "max_entry_bar", getattr(strat, "entry_to", 10 ** 9))
        assert buys.min() >= lo and buys.max() <= hi, \
            f"{type(strat).__name__}: 진입 순번 {buys.min()}~{buys.max()}이 [{lo},{hi}]를 벗어난다"


if __name__ == "__main__":
    for fn in (test_helpers, test_no_lookahead,
               test_no_overnight_and_single_round_trip, test_entry_window):
        fn()
        print(f"  ok  {fn.__name__}")
    print("모두 통과")
