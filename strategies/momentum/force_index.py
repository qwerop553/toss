from ..base import Strategy
from ..indicators import force_index
import pandas as pd


class ForceIndexStrategy(Strategy):
    """
    Elder 강도지수의 0선 교차. (종가 변화 x 거래량)을 EMA로 다듬은 값을 본다.

    ObvTrendStrategy와의 차이가 이 전략의 전부다. OBV는 봉의 방향(+1/-1)에만
    거래량을 곱하므로 1원 오른 봉과 5% 오른 봉이 똑같이 취급된다. 강도지수는 변화폭
    자체를 곱해서 '얼마나, 얼마의 물량으로' 움직였는지를 한 숫자에 담는다. 거래량
    없이 슬금슬금 오르는 구간을 걸러내는 게 목적이다.

    분봉에서는 거래량이 개장·마감에 몰려 값의 스케일이 하루 안에서도 크게 요동친다.
    그래서 절대값 문턱을 두지 않고 0선 교차만 쓴다 — 부호는 스케일과 무관하다.

    slow_period 조건: 짧은 강도지수는 진입 타이밍용, 긴 쪽은 추세 필터용이라는 게
    Elder의 원래 용법이다. 긴 쪽이 음수면 큰 흐름이 하락이라 매수를 막는다.
    """

    def __init__(self, period=13, slow_period=100, use_trend_filter=True):
        self.period = period
        self.slow_period = slow_period
        self.use_trend_filter = use_trend_filter
        self.warmup = max(period, slow_period if use_trend_filter else 0)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        fast = force_index(df, self.period)
        cond = fast > 0
        if self.use_trend_filter:
            cond &= force_index(df, self.slow_period) > 0
        # [매수] 단기 매수 압력이 양수 (+ 옵션으로 장기 흐름도 양수)
        return cond

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 단기 압력이 매도 쪽으로 반전. 장기 필터는 청산에 걸지 않는다.
        return force_index(df, self.period) < 0
