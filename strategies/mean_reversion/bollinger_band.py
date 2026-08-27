from ..base import Strategy
import pandas as pd


class BollingerBandStrategy(Strategy):
    """
    볼린저 밴드 기반 평균회귀 전략.
    종가가 하단 밴드를 이탈(터치)하면 매수하고,
    중심선(이동평균) 또는 상단 밴드로 회귀하면 매도한다.
    """

    def __init__(self, period=20, num_std=2.0, exit_at_middle=True):
        self.period = period
        self.num_std = num_std
        self.exit_at_middle = exit_at_middle  # True: 중심선에서 청산 / False: 상단 밴드에서 청산

        # rolling 창이 다 차기 전에는 밴드가 NaN이라 신호를 내면 안 된다.
        self.warmup = period

    def _bands(self, df: pd.DataFrame):
        """중심선/상단/하단을 한 번에 계산한다. entries와 exits가 같이 쓴다."""
        close = df["close"]
        mid = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        return mid, mid + self.num_std * std, mid - self.num_std * std

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 하단 밴드 이하로 하락 = 과매도, 평균 회귀를 기대
        _, _, lower = self._bands(df)
        return df["close"] <= lower

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 종가가 청산 기준선(중심선 또는 상단 밴드) 이상으로 회복
        mid, upper, _ = self._bands(df)
        target = mid if self.exit_at_middle else upper
        return df["close"] >= target
