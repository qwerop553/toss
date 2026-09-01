from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class AtrChannelBreakoutStrategy(Strategy):
    """
    ATR 채널(켈트너) 상단 돌파 추종.

    같은 켈트너 채널을 쓰지만 KeltnerReversionStrategy와 방향이 정반대다.
    회귀 전략은 '하단 이탈 = 싸다'로 읽고 사고, 이쪽은 '상단 돌파 = 추세 시작'으로
    읽고 산다. 어느 쪽이 맞는지는 종목·시간대의 성격(추세장이냐 횡보장이냐)이
    결정한다. 그래서 둘 다 등록해 두고 비교하는 것이 이 하네스의 용법에 맞는다.

    청산은 중심선 이탈. 상단에서 사서 중심선에서 나오면 추세가 살아 있는 동안만
    보유하게 된다.
    """

    def __init__(self, ema_period=20, atr_period=10, mult=1.5):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.mult = mult
        self.warmup = max(ema_period, atr_period)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 상단 채널 돌파
        _, upper, _ = ind.keltner(df, self.ema_period, self.atr_period, self.mult)
        return df["close"] > upper

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 중심선 하향 이탈
        mid, _, _ = ind.keltner(df, self.ema_period, self.atr_period, self.mult)
        return df["close"] < mid
