# -*- coding: utf-8 -*-
"""
WorldQuant 알파 5개와 연산자의 자기검사. 프레임워크 없이 assert만 쓴다.

    python strategies/tests/test_formulaic.py

연산자는 손으로 계산한 값과 맞춰 본다. 논문 정의를 잘못 옮기면 알파값이 조용히
틀리고, 백테스트는 아무 불평 없이 그 틀린 값으로 숫자를 내놓는다.

전략은 truncation invariance(잘라도 같은가)를 본다 — test_session_alpha.py와 같은
이유다. 다만 여기서는 마지막 봉을 제외할 필요가 없다. 이 전략들은 '그날 마지막 봉에
청산' 같은 규칙이 없어서 데이터 끝이 신호에 영향을 주지 않는다.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from strategies import (Alpha006Strategy, Alpha012Strategy, Alpha026Strategy,
                        Alpha035Strategy, Alpha101Strategy)
from strategies.formulaic.base import delta, correlation, ts_rank, ts_max, FormulaicAlpha
import strategies as S

STRATEGIES = [Alpha006Strategy(), Alpha012Strategy(), Alpha026Strategy(),
              Alpha035Strategy(), Alpha101Strategy()]


def make_df(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    close = 50000 * np.cumprod(1 + rng.normal(0, 0.012, n))
    high = close * (1 + abs(rng.normal(0, 0.008, n)))
    low = close * (1 - abs(rng.normal(0, 0.008, n)))
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D"),
        "open": np.roll(close, 1), "high": high, "low": low, "close": close,
        # 거래량 분포는 꼬리가 두껍다. ts_rank가 그 꼬리에 강한지 보려면 그대로 흉내내야 한다.
        "volume": rng.lognormal(12, 1.0, n),
    })


def test_operators():
    x = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0])

    # delta(x, d) = 오늘 값 - d봉 전 값
    assert delta(x, 1).tolist()[1:] == [2.0, -1.0, 3.0, -1.0]
    assert np.isnan(delta(x, 1).iloc[0])

    # ts_max(x, d) = 최근 d봉 최댓값
    assert ts_max(x, 3).tolist()[2:] == [3.0, 5.0, 5.0]

    # ts_rank(x, d) = 최근 d봉 중 현재 값의 순위 (0~1)
    #   마지막 3봉 [2,5,4]에서 4는 2등/3개 -> 2/3
    assert abs(ts_rank(x, 3).iloc[4] - 2 / 3) < 1e-12
    #   [1,3,2]에서 2는 2등/3개 -> 2/3
    assert abs(ts_rank(x, 3).iloc[2] - 2 / 3) < 1e-12
    assert ts_rank(x, 3).dropna().between(0, 1).all()

    # correlation(x, y, d): 완전히 같이 움직이면 +1, 반대면 -1
    y = pd.Series([2.0, 6.0, 4.0, 10.0, 8.0])          # y = 2x
    assert abs(correlation(x, y, 5).iloc[4] - 1.0) < 1e-10
    assert abs(correlation(x, -y, 5).iloc[4] + 1.0) < 1e-10


def test_alpha101_formula():
    """가장 짧은 알파는 손으로 맞춰 볼 수 있다."""
    df = pd.DataFrame({"open": [100.0], "high": [110.0], "low": [90.0], "close": [108.0]})
    got = Alpha101Strategy().alpha(df).iloc[0]
    assert abs(got - (108 - 100) / ((110 - 90) + .001)) < 1e-12
    # 고가 == 저가여도 0으로 나누지 않는다 (.001 가드)
    flat = pd.DataFrame({"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0]})
    assert np.isfinite(Alpha101Strategy().alpha(flat).iloc[0])


def test_no_lookahead():
    """데이터를 잘라도 앞부분 신호가 그대로여야 한다."""
    df = make_df(seed=1)
    for strat in STRATEGIES:
        full = strat.generate_signals(df)
        for k in (600, 900, 1200):
            part = strat.generate_signals(df.iloc[:k].copy())
            bad = np.flatnonzero(full.iloc[:k].to_numpy() != part.to_numpy())
            assert len(bad) == 0, (
                f"{type(strat).__name__}: {k}봉에서 자르니 {bad[:5]}번 신호가 달라진다 "
                "— 미래 봉을 보고 있다")


def test_holdings_are_binary():
    """to_signals를 거치므로 보유량은 0/1을 벗어날 수 없다. 평가 코드가 이 성질에 기댄다."""
    df = make_df(seed=2)
    for strat in STRATEGIES:
        h = strat.generate_signals(df).cumsum()
        assert h.isin((0, 1)).all(), f"{type(strat).__name__}: 보유량이 0/1을 벗어난다"


def test_warmup_is_silent():
    """워밍업 구간에는 신호가 없어야 한다. rolling 초기값은 신뢰할 수 없다."""
    df = make_df(seed=3)
    for strat in STRATEGIES:
        sig = strat.generate_signals(df)
        assert (sig.iloc[:strat.warmup] == 0).all(), \
            f"{type(strat).__name__}: 워밍업({strat.warmup}봉) 안에서 신호가 났다"


def test_base_not_registered():
    """추상 베이스가 전략으로 등록되면 --all이 그걸 인스턴스화하다 터진다."""
    assert "FormulaicAlpha" not in S.REGISTRY
    for name in ("Alpha006Strategy", "Alpha101Strategy"):
        assert name in S.REGISTRY, f"{name}이 자동 등록되지 않았다"


if __name__ == "__main__":
    for fn in (test_operators, test_alpha101_formula, test_no_lookahead,
               test_holdings_are_binary, test_warmup_is_silent, test_base_not_registered):
        fn()
        print(f"  ok  {fn.__name__}")
    print("모두 통과")
