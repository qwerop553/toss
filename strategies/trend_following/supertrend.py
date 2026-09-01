from ..base import Strategy
from .. import indicators as ind
import numpy as np
import pandas as pd


class SupertrendStrategy(Strategy):
    """
    슈퍼트렌드. ATR 폭의 추적 밴드가 가격 아래에 붙으면 상승 추세, 위에 붙으면 하락 추세.

    핵심은 밴드가 '한 방향으로만 조여진다'는 점이다. 상승 추세 동안 하단 밴드는
    올라가기만 하고 절대 내려가지 않는다. 그래서 트레일링 스톱과 추세 판정이
    한 지표로 합쳐진다. 밴드가 뚫리는 순간에만 방향이 뒤집힌다.

    이 재귀 때문에 벡터화가 안 된다. 지표 계산에만 루프를 쓰고, 진입/청산 자체는
    베이스의 상태머신에 맡긴다 (ema_cross_with_atr처럼 generate_signals를
    통째로 오버라이드할 필요가 없다).
    """

    def __init__(self, period=10, mult=3.0):
        self.period = period
        self.mult = mult
        self.warmup = period

    def _trend(self, df: pd.DataFrame) -> pd.Series:
        """상승 추세면 +1, 하락 추세면 -1인 Series."""
        hl2 = (df["high"] + df["low"]) / 2
        band = self.mult * ind.atr(df, self.period)
        upper = (hl2 + band).to_numpy()
        lower = (hl2 - band).to_numpy()
        close = df["close"].to_numpy()

        # ponytail: 파이썬 루프. 밴드가 직전 밴드에 의존하는 재귀라 벡터화가
        # 자명하지 않다. 2만 봉에 수십 ms 수준이라 그리드서치도 견딘다.
        # 조합 수가 수천으로 커져 체감상 느려지면 numba로 올린다.
        n = len(close)
        trend = np.ones(n, dtype=np.int8)
        fu, fl = upper.copy(), lower.copy()

        for i in range(1, n):
            if np.isnan(fu[i - 1]):
                continue
            # 상단 밴드는 내려가기만, 하단 밴드는 올라가기만 (직전 종가가 밴드를
            # 지키고 있는 동안에는 그렇다). 이게 트레일링 효과를 만든다.
            if upper[i] > fu[i - 1] and close[i - 1] <= fu[i - 1]:
                fu[i] = fu[i - 1]
            if lower[i] < fl[i - 1] and close[i - 1] >= fl[i - 1]:
                fl[i] = fl[i - 1]

            if trend[i - 1] > 0:
                trend[i] = -1 if close[i] < fl[i] else 1
            else:
                trend[i] = 1 if close[i] > fu[i] else -1

        return pd.Series(trend, index=df.index)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 추세가 하락에서 상승으로 뒤집힌 봉
        trend = self._trend(df)
        return (trend > 0) & (trend.shift(1) < 0)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 추세가 상승에서 하락으로 뒤집힌 봉
        trend = self._trend(df)
        return (trend < 0) & (trend.shift(1) > 0)
