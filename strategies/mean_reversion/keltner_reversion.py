from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class KeltnerReversionStrategy(Strategy):
    """
    켈트너 채널 하단 이탈 후 중심선 회귀.

    볼린저와 모양은 같은데 폭을 표준편차가 아니라 ATR로 잡는다. 차이가 실전에서
    갈리는 지점은 이렇다: 표준편차는 종가만 보므로 장중에 크게 흔들려도 종가가
    제자리면 밴드가 안 벌어진다. ATR은 고가·저가·갭을 보므로 그 흔들림을 반영해
    밴드를 넓힌다. 즉 변동성이 튀는 구간에서 켈트너 쪽이 덜 속는다.
    """

    def __init__(self, ema_period=20, atr_period=10, mult=2.0):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.mult = mult
        self.warmup = max(ema_period, atr_period)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 하단 채널 아래로 이탈
        _, _, lower = ind.keltner(df, self.ema_period, self.atr_period, self.mult)
        return df["close"] <= lower

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 중심선(EMA) 회복
        mid, _, _ = ind.keltner(df, self.ema_period, self.atr_period, self.mult)
        return df["close"] >= mid
