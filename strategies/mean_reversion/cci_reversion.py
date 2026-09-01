from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class CciReversionStrategy(Strategy):
    """
    CCI 극단 되돌림.

    CCI는 전형가격이 이동평균에서 '평균편차의 몇 배' 떨어졌는지를 잰다. Z-Score와
    비슷하지만 분모가 표준편차가 아니라 평균절대편차라서 극단값에 덜 휘둘린다.
    급등락 한 번에 지표가 통째로 무뎌지는 일이 적다는 뜻이다.

    -100 아래로 내려갔다가 회복하는 봉에서 사고, 0(평균) 위로 올라오면 판다.
    """

    def __init__(self, period=20, oversold=-100, exit_level=0):
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 침체 구간을 벗어나는 봉 (구간 안에 머무는 동안은 사지 않는다)
        c = ind.cci(df, self.period)
        return (c > self.oversold) & (c.shift(1) <= self.oversold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 평균선 회귀
        return ind.cci(df, self.period) >= self.exit_level
