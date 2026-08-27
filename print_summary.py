import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# BacktestResult를 실제로 임포트한다. 지금까지는 임포트 없이 타입 힌트로만
# 써 왔는데, Python 3.14의 지연 annotation 평가(PEP 649) 덕에 우연히 동작했을
# 뿐이라 하위 버전에서는 NameError가 난다.
from backtest_engine import BacktestResult
from metrics import sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio, trade_stats

def print_summary(result: BacktestResult) -> None:
    """
    백테스트 결과를 받아 주요 성과 지표 및 요약 정보를 출력합니다.
    """
    print("=" * 50)
    print("           [ BACKTEST SUMMARY REPORT ]           ")
    print("=" * 50)
    
    # Risk / Return Metrics
    print(f"Sharpe Ratio     : {sharpe_ratio(result.returns):.2f}")
    print(f"Sortino Ratio    : {sortino_ratio(result.returns):.2f}")
    # MDD/Calmar는 투입원금(최대로 물렸던 금액) 대비로 낸다.
    print(f"MDD              : {max_drawdown(result.equity_curve, result.max_book_size):.2%}")
    print(f"Calmar Ratio     : {calmar_ratio(result.returns, result.equity_curve, result.max_book_size):.2f}")
    print("-" * 50)
    
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
    
    # PnL Summary
    final_equity = result.equity_curve.iloc[-1]
    final_gross = result.gross_equity_curve.iloc[-1]
    
    print(f"순손익 (Net PnL)   : {final_equity:,.0f}원")
    print(f"비용 전 손익(Gross): {final_gross:,.0f}원 (총 비용: {result.total_cost:,.0f}원)")
    print(f"벤치마크 손익      : {result.benchmark_pnl:,.0f}원 ({result.benchmark_return_pct:.2%})")
    print("=" * 50)


def plot_backtest(df: pd.DataFrame, result: BacktestResult, title: str = "Backtest") -> plt.Figure:
    x = df.index  # 리셋된 정수 인덱스 (0, 1, 2, ...) — 봉 개수 기준, 갭 없음

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                              gridspec_kw={"height_ratios": [3, 1]})
    holding_mask = result.holdings > 0
    # mask는 False인 곳은 NaN이 되고, matplotlib은 NaN인 구간은 그래프를 그리지 않는다.
    price_when_holding = df["close"].where(holding_mask)
    axes[0].plot(x, price_when_holding, color="orange", linewidth=2.5, label="보유 중", zorder=3)
    axes[0].plot(x, df["close"], color="black", linewidth=1, label="Close")
    if not result.trades.empty:
        buys = result.trades[result.trades["side"] == "buy"]
        sells = result.trades[result.trades["side"] == "sell"]
        axes[0].scatter(buys["position"], buys["price"], marker="^", color="red", label="Buy", zorder=5)
        axes[0].scatter(sells["position"], sells["price"], marker="v", color="blue", label="Sell", zorder=5)
    axes[0].set_ylabel("Price")
    axes[0].set_title(f"{title} (max book: {result.max_book_size:,.0f}원, trades: {result.trade_count})")
    axes[0].legend(loc="upper left")

    axes[1].plot(x, result.equity_curve, color="green", label="전략 (순손익)")
    axes[1].plot(x, result.gross_equity_curve, color="green", linestyle="--", alpha=0.6, label="전략 (비용 전)")
    axes[1].plot(x, result.benchmark_equity_curve, color="gray", label="벤치마크 (단순보유)")
    axes[1].axhline(0, color="gray", linewidth=0.8, linestyle=":")
    axes[1].set_ylabel("Equity (원)")
    axes[1].legend(loc="upper left")

    # x축을 봉 개수 대신 실제 날짜/시간으로 라벨링
    if "timestamp" in df.columns:
        n_ticks = min(10, len(df))
        tick_pos = np.linspace(0, len(df) - 1, n_ticks).astype(int)
        tick_labels = df["timestamp"].iloc[tick_pos].dt.strftime("%m-%d %H:%M")
        axes[-1].set_xticks(tick_pos)
        axes[-1].set_xticklabels(tick_labels, rotation=45, ha="right")
    axes[-1].set_xlabel("시간")

    plt.tight_layout()
    return fig

def to_daily_summary(df: pd.DataFrame, result: BacktestResult) -> pd.DataFrame:
    """
    분봉/일봉 상관없이 날짜(캘린더 일자) 기준으로 집계.
    분봉이면 하루치 여러 행을 하나로 압축, 일봉이면 원래 하루 1행이라 그대로 통과.
    """
    if "timestamp" not in df.columns:
        raise ValueError("df에 timestamp 컬럼이 필요합니다")

    calendar_date = df["timestamp"].dt.date
    book_value = result.holdings * df["close"]

    daily = pd.DataFrame({
        "date": calendar_date,
        "book_value": book_value,
        "holdings": result.holdings,
        "equity": result.equity_curve,
    }).groupby("date").agg(
        max_book_size=("book_value", "max"),      # 그날 최대로 물려있던 금액
        max_holdings=("holdings", "max"),           # 그날 최대 보유 주식 수
        end_of_day_equity=("equity", "last"),        # 그날 마감 시점 누적 손익
    )

    # 그날 '번 돈'. end_of_day_equity는 누적이라 하루 성과가 안 보인다.
    # 첫날은 이전 날이 없으므로 마감 누적을 그대로 그날의 손익으로 본다.
    daily["daily_pnl"] = daily["end_of_day_equity"].diff().fillna(
        daily["end_of_day_equity"].iloc[0]
    )

    if not result.trades.empty:
        trade_dates = pd.to_datetime(result.trades["date"]).dt.date
        daily["trade_count"] = trade_dates.value_counts()
        daily["trade_count"] = daily["trade_count"].fillna(0).astype(int)
    else:
        daily["trade_count"] = 0

    return daily


