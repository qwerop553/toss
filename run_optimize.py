import scrap
from strategies.trend_following.ema_cross_with_adx import EmaCrossStrategyWithADX
from backtest_engine import run_backtest
from optimize import grid_search
from validation import walk_forward_split
from metrics import sharpe_ratio

df = scrap.load_candles("005930", interval="1m")
train, test = walk_forward_split(df)

# 1. train에서 최적 파라미터 탐색
opt_result = grid_search(
    train,
    strategy_factory=EmaCrossStrategyWithADX,
    param_grid={"fast": range(6, 60, 1), "slow": range(12, 120, 2), "adx": range(8, 20, 1)},
    metric="sharpe",
    valid_combo=lambda p: p["fast"] < p["slow"],  # fast가 slow보다 짧아야 의미있는 크로스
)

print("최적 파라미터 (train 기준):", opt_result.best_params)
print(opt_result.leaderboard.head(10))

# 2. train에서 고른 파라미터를 test(out-of-sample)에 그대로 적용해서 오버피팅 검증
best_strategy = EmaCrossStrategyWithADX(**opt_result.best_params)
test_signal = best_strategy.generate_signals(test)
test_result = run_backtest(test, test_signal)

print(f"Out-of-sample Sharpe: {sharpe_ratio(test_result.returns):.2f}")
print(f"Out-of-sample Trade count: {test_result.trade_count}")