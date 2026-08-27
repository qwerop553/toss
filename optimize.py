"""
전략 파라미터 그리드서치 모듈. 특정 전략에 종속되지 않고 재사용 가능.
"""
from dataclasses import dataclass
from itertools import product
from typing import Callable, Iterable
import pandas as pd

from backtest_engine import run_backtest
from metrics import sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio


@dataclass
class OptimizationResult:
    best_params: dict
    best_score: float
    leaderboard: pd.DataFrame  # 모든 조합의 성능 비교, metric 기준 정렬됨


_METRIC_FUNCS = {
    "sharpe": lambda r: sharpe_ratio(r.returns),
    "sortino": lambda r: sortino_ratio(r.returns),
    "calmar": lambda r: calmar_ratio(r.returns, r.equity_curve),
    "mdd": lambda r: -abs(max_drawdown(r.equity_curve)),  # MDD는 작을수록 좋으니 부호 반전
}


def grid_search(
    df: pd.DataFrame,
    strategy_factory: Callable[..., "Strategy"],
    param_grid: dict[str, Iterable],
    metric: str = "sharpe",
    buy_slippage: float = 0.00015,
    sell_slippage: float = 0.00215,
    valid_combo: Callable[[dict], bool] | None = None,
) -> OptimizationResult:
    """
    df: 백테스트에 쓸 데이터 (보통 train 구간)
    strategy_factory: 파라미터를 kwargs로 받아 Strategy 인스턴스를 만드는 함수/클래스
                       예: EmaCrossStrategy
    param_grid: {"fast": [5,10,12], "slow": [20,26,30]} 형태
    metric: "sharpe" | "sortino" | "calmar" | "mdd" 중 최적화 기준
    valid_combo: 무효 조합을 걸러내는 함수. 예: lambda p: p["fast"] < p["slow"]
    """
    if metric not in _METRIC_FUNCS:
        raise ValueError(f"지원하지 않는 metric: {metric} (가능: {list(_METRIC_FUNCS)})")
    score_fn = _METRIC_FUNCS[metric]

    keys = list(param_grid.keys())
    combos = list(product(*param_grid.values()))

    rows = []
    best_score = float("-inf")
    best_params = None

    for combo in combos:
        params = dict(zip(keys, combo))

        if valid_combo is not None and not valid_combo(params):
            continue

        strategy = strategy_factory(**params)
        signal = strategy.generate_signals(df)
        result = run_backtest(df, signal, buy_slippage=buy_slippage, sell_slippage=sell_slippage)

        score = score_fn(result)
        rows.append({
            **params,
            "sharpe": sharpe_ratio(result.returns),
            "sortino": sortino_ratio(result.returns),
            "mdd": max_drawdown(result.equity_curve),
            "calmar": calmar_ratio(result.returns, result.equity_curve),
            "trade_count": result.trade_count,
            "net_pnl": result.equity_curve.iloc[-1],
        })

        if score > best_score:
            best_score = score
            best_params = params

    if not rows:
        raise ValueError("유효한 파라미터 조합이 없습니다. valid_combo 조건을 확인하세요.")

    sort_col = "mdd" if metric == "mdd" else metric
    ascending = (metric == "mdd")  # mdd는 절댓값이 작을수록(0에 가까울수록) 좋음
    leaderboard = pd.DataFrame(rows).sort_values(sort_col, ascending=ascending).reset_index(drop=True)

    return OptimizationResult(best_params=best_params, best_score=best_score, leaderboard=leaderboard)