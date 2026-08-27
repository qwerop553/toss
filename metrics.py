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

def max_drawdown(equity_curve: pd.Series, capital: float) -> float:
    """
    최고점 대비 최악의 낙폭을 투입원금 대비 비율로 낸다. 음수로 나온다.

    분모가 왜 running_max가 아니라 capital인가:
      equity_curve는 자본 잔고가 아니라 0에서 시작하는 '누적 손익'이다.
      그래서 running_max로 나누면 초반에 분모가 0을 지나가며 -inf가 나온다.
      투입원금(보통 result.max_book_size)으로 나눠야 '최대로 물렸던 금액 대비
      최악의 낙폭'이라는 읽히는 수치가 되고, 가격대가 다른 종목끼리도 비교된다.
      result.returns가 이미 같은 분모를 쓰므로 샤프와도 기준이 맞는다.
    """
    if capital <= 0:
        return 0.0
    running_max = equity_curve.cummax()
    return float(((equity_curve - running_max) / capital).min())

def calmar_ratio(returns: pd.Series, equity_curve: pd.Series, capital: float,
                 periods_per_year: int = 252) -> float:
    """
    연율화 수익률 / 최대낙폭. 낙폭 1단위당 수익을 얼마나 뽑았나.

    예전 구현은 원화 손익(equity_curve.iloc[-1])을 그대로 거듭제곱했는데,
    손실이 나면 음수의 분수 거듭제곱이라 nan이 됐다. 원금 대비 수익률로
    바꾼 뒤 연율화해야 한다.
    """
    if capital <= 0:
        return 0.0

    total_return = equity_curve.iloc[-1] / capital
    if total_return <= -1:      # 원금을 통째로 날린 경우, 연율화가 의미 없다
        return 0.0

    annual_return = (1 + total_return) ** (periods_per_year / len(returns)) - 1
    mdd = abs(max_drawdown(equity_curve, capital))
    return float(annual_return / mdd) if mdd != 0 else 0.0

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
