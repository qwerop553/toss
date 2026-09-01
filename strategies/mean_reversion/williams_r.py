from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class WilliamsRStrategy(Strategy):
    """
    Williams %R 반등.

    %R은 '최근 N봉 고점 대비 지금 얼마나 눌려 있나'를 -100~0으로 나타낸다.
    -100이면 구간 최저가, 0이면 구간 최고가다.

    -80 아래(과매도)에 들어갔다가 다시 위로 올라오는 그 봉에서 산다. 구간에
    '머무르는' 동안이 아니라 '탈출하는' 순간을 잡는 게 포인트다 — 과매도 상태는
    하락장에서 며칠도 지속되지만 탈출은 한 번뿐이다.
    """

    def __init__(self, period=14, oversold=-80, exit_level=-20):
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 직전 봉은 과매도였는데 이번 봉에 그 위로 올라옴
        r = ind.williams_r(df, self.period)
        return (r > self.oversold) & (r.shift(1) <= self.oversold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 과매수권 도달
        return ind.williams_r(df, self.period) >= self.exit_level
