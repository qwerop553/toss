# -*- coding: utf-8 -*-
"""
시장미시구조 추정량과 전략 5개의 자기검사.

    python strategies/tests/test_microstructure.py

추정량은 손으로 계산한 값과 맞춰 본다. Roll 스프레드처럼 '자주 정의되지 않는' 것은
그 성질 자체를 검사한다 — 조용히 전량 NaN이 되면 전략이 신호를 0회 내고 끝나는데,
그건 터지지 않아서 알아채기 어렵다(실제로 한 번 당했다).
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from strategies import (AmihudIlliquidityStrategy, RollSpreadStrategy,
                        OrderFlowImbalanceStrategy, AdverseSelectionStrategy,
                        OvernightInventoryStrategy)
from strategies.microstructure.base import close_location_value, signed_volume, amihud, roll_spread
from strategies import indicators as ind
import strategies as S

SCORE_STRATEGIES = [AmihudIlliquidityStrategy(), RollSpreadStrategy(),
                    OrderFlowImbalanceStrategy(), AdverseSelectionStrategy()]


def make_daily(n=1200, seed=0):
    rng = np.random.default_rng(seed)
    close = 50000 * np.cumprod(1 + rng.normal(0, 0.015, n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": np.roll(close, 1),
        "high": close * (1 + abs(rng.normal(0, 0.01, n))),
        "low": close * (1 - abs(rng.normal(0, 0.01, n))),
        "close": close,
        "volume": rng.lognormal(12, 1.0, n),
    })


def make_intraday(days=8, bars=390, seed=0):
    """09:00~15:29 분봉. 오버나잇 갭이 있어야 OvernightInventoryStrategy가 의미를 갖는다."""
    rng = np.random.default_rng(seed)
    rows, price = [], 50000.0
    for day in range(days):
        start = pd.Timestamp("2026-01-05 09:00") + pd.Timedelta(days=day)
        price *= 1 + rng.normal(0, 0.008)
        for b in range(bars):
            price *= 1 + rng.normal(0, 0.0006)
            rows.append((start + pd.Timedelta(minutes=b), price,
                         price * 1.0004, price * 0.9996, price,
                         float(rng.integers(100, 10000))))
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["open"] = df["close"].shift(1).fillna(df["close"])
    return df


def test_close_location_value():
    df = pd.DataFrame({"high": [10., 10, 10], "low": [8., 8, 10],
                       "close": [10., 8, 10], "volume": [100., 100, 100]})
    clv = close_location_value(df)
    assert clv.iloc[0] == 1.0, "고가 마감이면 +1"
    assert clv.iloc[1] == -1.0, "저가 마감이면 -1"
    assert np.isnan(clv.iloc[2]), "고가 == 저가면 주도권을 정의할 수 없다"
    assert signed_volume(df).iloc[0] == 100.0


def test_roll_spread_is_often_undefined():
    """
    Roll 추정량은 공분산이 양수면 정의되지 않는다. 그게 정상이고, 그 성질이 사라지면
    구현이 틀린 것이다(예: -cov의 절댓값을 씌우면 항상 값이 나오지만 뜻이 없다).
    """
    # 완전한 상승 추세: Δp가 양의 자기상관 -> 전 구간 NaN이어야 한다
    up = pd.DataFrame({"close": np.arange(100.0, 200.0)})
    assert roll_spread(up, 20).dropna().empty, "추세 구간에서 값이 나오면 안 된다"

    # 지그재그(매수·매도 번갈아 체결): 강한 음의 자기상관 -> 정의되고, 진폭에 비례.
    #
    # 진폭 1이면 Δp가 ±1로 번갈고 모든 곱이 -1이라 표본공분산은 -n/(n-1)이다
    # (pandas의 rolling.cov는 ddof=1). 그래서 스프레드는 정확히 2가 아니라
    # 2*sqrt(n/(n-1)) = 2.0520이 나온다. 교과서의 2는 ddof=0일 때의 값이다 —
    # 여기서 2.0을 기대하면 틀리는 건 구현이 아니라 기대값이다.
    zig = pd.DataFrame({"close": 100 + np.tile([0.0, 1.0], 60)})
    s = roll_spread(zig, 20).dropna()
    expected = 2 * np.sqrt(20 / 19)
    assert len(s) > 0 and np.allclose(s, expected, atol=1e-9), \
        f"진폭 1인 지그재그의 내재 스프레드는 {expected:.4f}여야 하는데 {s.unique()[:3]}"


def test_amihud_direction():
    """거래대금이 작을수록 비유동성이 커야 한다."""
    n = 100
    base = pd.DataFrame({"close": 100 + np.tile([0.0, 1.0], n // 2)})
    thin = base.assign(volume=1e3)
    thick = base.assign(volume=1e9)
    assert amihud(thin, 20).iloc[-1] > amihud(thick, 20).iloc[-1]


def test_no_lookahead():
    df = make_daily(seed=1)
    for strat in SCORE_STRATEGIES:
        full = strat.generate_signals(df)
        for k in (500, 800, 1000):
            part = strat.generate_signals(df.iloc[:k].copy())
            bad = np.flatnonzero(full.iloc[:k].to_numpy() != part.to_numpy())
            assert len(bad) == 0, \
                f"{type(strat).__name__}: {k}봉에서 자르니 {bad[:5]}번 신호가 달라진다"


def test_signals_actually_fire():
    """
    신호가 0회면 조용히 '거래 없음'으로 끝나 성과표에서 알아채기 어렵다.
    RollSpreadStrategy가 실제로 이 함정에 빠졌었다(rolling의 min_periods 기본값).
    """
    df = make_daily(n=2000, seed=2)
    for strat in SCORE_STRATEGIES:
        n = int((strat.generate_signals(df) == 1).sum())
        assert n > 0, f"{type(strat).__name__}: 진입 신호가 한 번도 안 났다"


def test_overnight_holds_only_overnight():
    """종가에 사서 다음 날 첫 봉에 판다. 장중에는 절대 들고 있지 않아야 한다."""
    df = make_intraday(seed=3)
    sig = OvernightInventoryStrategy().generate_signals(df)
    holding = sig.cumsum()
    assert holding.isin((0, 1)).all()

    bar_no = ind.bar_of_day(df)
    buys, sells = bar_no[sig == 1], bar_no[sig == -1]
    assert (buys > 0).all(), "매수는 그날 마지막 봉이어야 한다"
    assert (sells == 0).all(), "매도는 다음 날 첫 봉이어야 한다"
    assert ind.is_last_bar_of_day(df)[sig == 1].all()

    # 보유 중인 봉은 '그날 첫 봉'뿐이어야 한다 (직전 봉 종료 시점에 보유 -> 이 봉에서 청산)
    held_bars = bar_no[holding.shift(1).fillna(0) > 0]
    assert (held_bars == 0).all(), \
        f"장중에 보유 중인 봉이 있다: {sorted(set(held_bars))[:5]}"


def test_bases_not_registered():
    for name in ("PercentileScoreStrategy", "FormulaicAlpha"):
        assert name not in S.REGISTRY, f"{name}이 전략으로 등록됐다"
    for name in ("AmihudIlliquidityStrategy", "OvernightInventoryStrategy"):
        assert name in S.REGISTRY, f"{name}이 자동 등록되지 않았다"


if __name__ == "__main__":
    for fn in (test_close_location_value, test_roll_spread_is_often_undefined,
               test_amihud_direction, test_no_lookahead, test_signals_actually_fire,
               test_overnight_holds_only_overnight, test_bases_not_registered):
        fn()
        print(f"  ok  {fn.__name__}")
    print("모두 통과")
