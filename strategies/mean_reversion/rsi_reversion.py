from ..base import Strategy
import pandas as pd
import numpy as np


class RsiReversionStrategy(Strategy):
    """
    RSI 기반 평균회귀(mean reversion) 전략.
    RSI가 과매도(oversold) 구간에 진입하면 매수하고,
    exit_level(기본 50, 중립선)까지 회복하면 매도한다.
    """

    def __init__(self, period=14, oversold=30, exit_level=50):
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level

        # RSI가 익기 전(min_periods 미충족) 구간은 신호를 내지 않는다.
        self.warmup = period

    def _rsi(self, close: pd.Series) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / self.period, min_periods=self.period).mean()
        avg_loss = loss.ewm(alpha=1 / self.period, min_periods=self.period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)  # 워밍업 구간(분모 0 등)은 중립값 50으로 채움

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] RSI가 과매도 구간에 진입
        return self._rsi(df["close"]) <= self.oversold

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] RSI가 중립선(exit_level)까지 회복
        return self._rsi(df["close"]) >= self.exit_level