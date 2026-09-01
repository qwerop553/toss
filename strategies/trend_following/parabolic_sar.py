from ..base import Strategy
import numpy as np
import pandas as pd


class ParabolicSarStrategy(Strategy):
    """
    파라볼릭 SAR (Stop And Reverse).

    점(SAR)이 가격을 따라 붙는데, 추세가 이어질수록 가속계수 AF가 커져서 점이
    점점 빨리 따라온다. 즉 오래 끌수록 손절선이 공격적으로 조여진다. 가격이 점을
    건드리면 방향을 뒤집는다.

    '추세는 시간이 지날수록 되돌림 여지를 줄여야 한다'는 발상을 구현한 몇 안 되는
    지표다. 대신 횡보장에서는 뒤집기를 반복하며 수수료만 먹는다.
    """

    def __init__(self, af_step=0.02, af_max=0.2):
        self.af_step = af_step
        self.af_max = af_max
        self.warmup = 2  # 첫 봉은 방향을 정할 근거가 없다

    def _trend(self, df: pd.DataFrame) -> pd.Series:
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        n = len(high)

        # ponytail: 파이썬 루프. SAR은 정의 자체가 순차 재귀(직전 SAR·EP·AF)라
        # 벡터화가 불가능에 가깝다. 2만 봉에 수십 ms.
        trend = np.ones(n, dtype=np.int8)
        sar = low[0]
        ep = high[0]          # extreme point: 현재 추세에서 본 최고가(또는 최저가)
        af = self.af_step     # acceleration factor

        for i in range(1, n):
            up = trend[i - 1] > 0
            sar = sar + af * (ep - sar)

            if up:
                # 상승 추세의 SAR은 직전 두 봉의 저가를 넘어설 수 없다 (원 정의)
                sar = min(sar, low[i - 1], low[max(i - 2, 0)])
                if low[i] < sar:                     # 점이 뚫렸다 -> 하락으로 반전
                    trend[i], sar, ep, af = -1, ep, low[i], self.af_step
                    continue
                trend[i] = 1
                if high[i] > ep:                     # 신고가 -> 가속
                    ep, af = high[i], min(af + self.af_step, self.af_max)
            else:
                sar = max(sar, high[i - 1], high[max(i - 2, 0)])
                if high[i] > sar:                    # 반전 -> 상승
                    trend[i], sar, ep, af = 1, ep, high[i], self.af_step
                    continue
                trend[i] = -1
                if low[i] < ep:
                    ep, af = low[i], min(af + self.af_step, self.af_max)

        return pd.Series(trend, index=df.index)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] SAR이 가격 아래로 내려온 순간 (상승 반전)
        trend = self._trend(df)
        return (trend > 0) & (trend.shift(1) < 0)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] SAR이 가격 위로 올라온 순간 (하락 반전)
        trend = self._trend(df)
        return (trend < 0) & (trend.shift(1) > 0)
