from ..base import Strategy
import pandas as pd


class MacdStrategy(Strategy):
    """
    MACD 시그널 크로스.

    MACD선(단기EMA - 장기EMA)은 '두 이평선이 벌어지는 속도'다. 그 값의 EMA인
    시그널선을 MACD선이 위로 뚫으면 상승 가속의 시작으로 보고 매수한다.

    EMA 크로스와 뭐가 다른가: EMA 크로스는 두 선이 실제로 교차해야 신호가 나서
    항상 늦다. MACD는 아직 교차 전이라도 간격이 벌어지기 시작하면 먼저 반응한다.
    대신 그만큼 속임수 신호도 많다.
    """

    def __init__(self, fast=12, slow=26, signal=9):
        self.fast = fast
        self.slow = slow
        self.signal = signal
        # MACD선 자체가 slow만큼 익어야 하고, 그 위에 signal EMA가 또 얹힌다.
        self.warmup = slow + signal

    def _macd(self, df: pd.DataFrame):
        macd = df["close"].ewm(span=self.fast).mean() - df["close"].ewm(span=self.slow).mean()
        return macd, macd.ewm(span=self.signal).mean()

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] MACD선이 시그널선을 아래에서 위로 통과한 그 봉
        macd, sig = self._macd(df)
        return (macd > sig) & (macd.shift(1) <= sig.shift(1))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 반대 크로스
        macd, sig = self._macd(df)
        return (macd < sig) & (macd.shift(1) >= sig.shift(1))
