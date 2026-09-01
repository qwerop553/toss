from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class StochasticStrategy(Strategy):
    """
    스토캐스틱 과매도 + %K/%D 골든크로스.

    %K가 과매도 구간에 있다는 것만으로는 사지 않는다. 떨어지는 칼날에서는 %K가
    바닥에 오래 눌어붙어 있기 때문이다. %K가 신호선 %D를 위로 뚫어 '되돌기
    시작했다'는 확인이 붙어야 진입한다.

    청산은 %K가 exit_level(기본 80, 과매수)에 닿을 때. 평균회귀 전략이지만
    목표를 중립이 아니라 반대쪽 끝에 두는 편이 분봉에서는 비용을 이긴다.
    """

    def __init__(self, k_period=14, d_period=3, oversold=20, exit_level=80):
        self.k_period = k_period
        self.d_period = d_period
        self.oversold = oversold
        self.exit_level = exit_level
        self.warmup = k_period + d_period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 과매도 구간에서 %K가 %D를 상향 돌파
        k, d = ind.stochastic(df, self.k_period, self.d_period)
        return (k < self.oversold) & (k > d) & (k.shift(1) <= d.shift(1))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] %K가 과매수 구간 도달
        k, _ = ind.stochastic(df, self.k_period, self.d_period)
        return k >= self.exit_level
