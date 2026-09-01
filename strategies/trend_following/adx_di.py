from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class AdxDiStrategy(Strategy):
    """
    +DI/-DI 크로스 + ADX 추세 강도 필터 (Wilder의 원래 DMI 시스템).

    주의: 이 리포의 EmaCrossStrategyWithADX는 이름과 달리 ADX가 아니라 ATR
    백분위를 필터로 쓴다. 여기가 진짜 ADX를 쓰는 쪽이다.

    ADX는 방향이 아니라 세기만 말한다. 그래서 방향은 +DI/-DI로 잡고, ADX가
    threshold 아래(= 추세가 없는 횡보장)면 크로스가 나도 무시한다. 추세추종
    전략이 횡보장에서 돈을 잃는 것이 기본값이라 이 필터가 존재한다.
    """

    def __init__(self, period=14, threshold=25):
        self.period = period
        self.threshold = threshold
        self.warmup = period * 3  # ADX는 DI를 평활한 뒤 한 번 더 평활한다

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 추세가 충분히 강한 상태에서 +DI가 -DI를 상향 돌파
        adx, plus_di, minus_di = ind.adx(df, self.period)
        crossed = (plus_di > minus_di) & (plus_di.shift(1) <= minus_di.shift(1))
        return crossed & (adx >= self.threshold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 방향이 뒤집히면 ADX와 무관하게 나온다.
        #        청산에까지 강도 필터를 걸면 추세가 죽는 구간에 갇힌다.
        _, plus_di, minus_di = ind.adx(df, self.period)
        return minus_di > plus_di
