from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class ObvTrendStrategy(Strategy):
    """
    OBV 추세 전환. 가격이 아니라 '누적 거래량 방향'에 이평선 크로스를 건다.

    OBV는 오른 봉의 거래량을 더하고 내린 봉의 거래량을 뺀 누적값이다. 가격은
    횡보하는데 OBV만 우상향이면 매집으로, 그 반대면 분산으로 읽는 게 통설이다.
    가격보다 먼저 움직인다는 주장은 검증이 갈리지만, 최소한 가격과 다른 정보를
    쓰는 축이라 다른 전략과 상관이 낮다는 실용적 가치가 있다.

    주의: OBV는 cumsum이라 절대 수준에 의미가 없다 (구간 시작점에 따라 통째로
    평행이동한다). 그래서 값 자체가 아니라 자기 이평선과의 관계만 본다.
    """

    def __init__(self, fast=20, slow=60):
        self.fast = fast
        self.slow = slow
        self.warmup = slow

    def _obv_mas(self, df: pd.DataFrame):
        o = ind.obv(df)
        return o.ewm(span=self.fast).mean(), o.ewm(span=self.slow).mean()

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] OBV 단기선이 장기선을 상향 돌파 = 매수 자금 유입 전환
        f, s = self._obv_mas(df)
        return (f > s) & (f.shift(1) <= s.shift(1))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        f, s = self._obv_mas(df)
        return f < s
