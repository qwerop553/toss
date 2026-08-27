import numpy as np
import pandas as pd 

def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    if returns.std() == 0:
        return 0.0
    return (returns.mean() / returns.std()) * np.sqrt(periods_per_year)

def sortino_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    downside = returns[returns < 0]
    if downside.std() == 0:
        return 0.0
    return (returns.mean() / downside.std()) * np.sqrt(periods_per_year)

def max_drawdown(equity_curve: pd.Series) -> float:
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return drawdown.min()

def calmar_ratio(returns: pd.Series, equity_curve: pd.Series, periods_per_year: int = 252) -> float:
    annual_return = (equity_curve.iloc[-1] ** (periods_per_year / len(returns))) - 1
    mdd = abs(max_drawdown(equity_curve))
    return annual_return / mdd if mdd != 0 else 0.0

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
