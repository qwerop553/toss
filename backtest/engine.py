"""
백테스트 시뮬레이션의 뼈대. run_backtest가 신호 시리즈를 받아 체결을 흉내내고
BacktestResult를 돌려준다.
"""
from dataclasses import dataclass
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False 

@dataclass
class BacktestResult:
    equity_curve: pd.Series        # 비용 차감 후 누적 손익
    gross_equity_curve: pd.Series  # 비용 제외 전(cost 없었다면) 누적 손익
    total_cost: float              # 슬리피지로 나간 총 비용
    holdings: pd.Series
    max_book_size: float
    trade_count: int
    trades: pd.DataFrame
    returns: pd.Series              # 일별 수익률(%), 최대 투입원금 대비
    benchmark_pnl: float             # 첫날 매수 ~ 마지막날 매도, 원화 손익
    benchmark_return_pct: float      # 벤치마크 수익률(%)
    benchmark_equity_curve: pd.Series  # 그래프 비교용


def run_backtest(df: pd.DataFrame, signal: pd.Series,
                  buy_slippage: float = 0.00015,
                  sell_slippage: float = 0.00215,
                  holdings0: int = 0) -> BacktestResult:
    """
    holdings0: 시작 시점에 이미 들고 있는 수량. 기본 0이라 평소 동작은 그대로다.

    왜 필요한가:
      이 루프는 순수한 순차 시뮬레이션이고, 한 봉에서 다음 봉으로 넘어가는 상태가
      holdings 하나뿐이다. 그래서 중간부터 이어서 돌릴 수 있다 — results.py의
      일 단위 증분 캐시가 이 인자로 마지막 저장 지점의 보유량을 되돌려 넣는다.
      누적 실현현금은 여기서 다루지 않는다(항상 0에서 시작한다). 호출자가
      직접 더해야 한다. 그 편이 엔진이 몰라도 되는 상태를 안 들고 있어 낫다.
    """

    holdings = holdings0
    holdings_series, cash_flow, cost_series, trades = [], [], [], []

    for i in range(len(df)):
        price = df["close"].iloc[i]
        sig = signal.iloc[i]
        flow = 0.0
        step_cost = 0.0

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

        cash_flow.append(flow)
        holdings_series.append(holdings)
        cost_series.append(step_cost)

    cash_flow = pd.Series(cash_flow, index=df.index)
    holdings_series = pd.Series(holdings_series, index=df.index)
    cost_series = pd.Series(cost_series, index=df.index)

    realized_cash = cash_flow.cumsum()
    unrealized_value = holdings_series * df["close"]

    # 특정 시점의 주식과 현금을 포함한 총 금액(총잔고)
    equity_curve = realized_cash + unrealized_value 

    total_cost = cost_series.sum()

    # cash_flow에 비용(step_cost, 항상 양수)가 이미 들어가 있는데 왜 비용을 또 더하지? -> 비용 차감 전 수익 구하기
    gross_equity_curve = equity_curve + cost_series.cumsum()  # 비용 다시 더해서 복원

    max_book_size = (holdings_series * df["close"]).max()
    if pd.isna(max_book_size) or max_book_size == 0:
        max_book_size = df["close"].iloc[0]

    daily_pnl = equity_curve.diff().fillna(equity_curve.iloc[0])
    returns = daily_pnl / max_book_size

    # 벤치마크: 첫날 종가 매수 → 마지막날 종가 매도 (동일 슬리피지 적용)
    first_price = df["close"].iloc[0]
    last_price = df["close"].iloc[-1]
    entry_cost = first_price * (1 + buy_slippage)
    exit_proceeds = last_price * (1 - sell_slippage)
    benchmark_pnl = exit_proceeds - entry_cost
    benchmark_return_pct = benchmark_pnl / entry_cost

    benchmark_equity_curve = df["close"] - entry_cost
    benchmark_equity_curve.iloc[-1] = exit_proceeds - entry_cost  # 마지막 날만 매도 슬리피지 반영

    
    return BacktestResult(
        equity_curve=equity_curve,
        gross_equity_curve=gross_equity_curve,
        total_cost=total_cost,
        holdings=holdings_series,
        max_book_size=max_book_size,
        trade_count=len(trades),
        trades=pd.DataFrame(trades),
        returns=returns,
        benchmark_pnl=benchmark_pnl,
        benchmark_return_pct=benchmark_return_pct,
        benchmark_equity_curve=benchmark_equity_curve,
    )



