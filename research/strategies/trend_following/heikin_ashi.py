from ..base import Strategy
import numpy as np
import pandas as pd


class HeikinAshiTrendStrategy(Strategy):
    """
    하이킨아시 연속 양봉 추세.

    하이킨아시는 종가를 OHLC 평균으로, 시가를 '직전 하이킨아시 봉의 시가·종가
    평균'으로 다시 그린 캔들이다. 노이즈가 뭉개져서 추세 구간이 한쪽 색으로
    길게 이어진다.

    양봉이 streak봉 연속으로 나오면 진입, 음봉이 나오면 청산. 원 캔들로 같은 걸
    하면 신호가 수십 배 많아진다 — 평활이 곧 필터인 셈이다.
    """

    def __init__(self, streak=3):
        self.streak = streak
        self.warmup = streak + 1

    def _bullish(self, df: pd.DataFrame) -> pd.Series:
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        o = df["open"].to_numpy()
        c = ha_close.to_numpy()

        # ponytail: ha_open은 직전 ha_open에 의존하는 재귀라 루프가 필요하다.
        ha_open = np.empty(len(c))
        ha_open[0] = (o[0] + c[0]) / 2
        for i in range(1, len(c)):
            ha_open[i] = (ha_open[i - 1] + c[i - 1]) / 2

        return ha_close > pd.Series(ha_open, index=df.index)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 하이킨아시 양봉이 streak봉 연속
        bull = self._bullish(df)
        return bull.rolling(self.streak).sum() == self.streak

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 음봉이 하나라도 나오면 즉시 이탈 (평활된 캔들의 색 전환은 무겁다)
        return ~self._bullish(df)
