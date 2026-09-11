from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class DonchianBreakoutStrategy(Strategy):
    """
    돈치안 채널 돌파 (터틀 트레이딩의 뼈대).

    '직전 entry_period봉의 최고가를 넘으면 산다. 직전 exit_period봉의 최저가를
    깨면 판다.' 지표라고 부르기도 민망할 만큼 단순한데, 추세추종의 원형이고
    파라미터가 두 개뿐이라 과최적화가 잘 안 된다는 게 장점이다.

    청산 기간을 진입 기간보다 짧게 두는 게 관례다 (예: 20봉 돌파 진입 / 10봉 청산).
    빨리 나와야 추세가 꺾였을 때 되돌림을 덜 맞는다.
    """

    def __init__(self, entry_period=20, exit_period=10):
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.warmup = max(entry_period, exit_period) + 1  # shift(1) 한 칸 더

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 직전 N봉 최고가를 넘어섬 (채널은 현재 봉을 제외하고 계산됨)
        upper, _ = ind.donchian(df, self.entry_period)
        return df["close"] > upper

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 종가가 직전 M봉 최저가를 이탈
        _, lower = ind.donchian(df, self.exit_period)
        return df["close"] < lower
