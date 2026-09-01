from ..base import Strategy
import pandas as pd


class TripleMaStrategy(Strategy):
    """
    삼중 이동평균 정배열.

    단기 > 중기 > 장기로 줄을 서면(정배열) 사고, 단기가 중기 아래로 내려오면 판다.
    선 두 개짜리 크로스보다 신호가 훨씬 적게 나온다 — 세 개가 모두 같은 방향을
    가리키기를 기다리기 때문이다. 횡보장에서 크로스가 난무하는 문제를 줄이려는
    가장 싼 방법이다. 대신 진입이 늦다.
    """

    def __init__(self, short=5, mid=20, long=60):
        self.short = short
        self.mid = mid
        self.long = long
        self.warmup = long

    def _mas(self, df: pd.DataFrame):
        close = df["close"]
        return (close.rolling(self.short).mean(),
                close.rolling(self.mid).mean(),
                close.rolling(self.long).mean())

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 완전 정배열
        s, m, l = self._mas(df)
        return (s > m) & (m > l)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 단기선이 중기선을 하향 이탈 = 정배열의 첫 균열
        s, m, _ = self._mas(df)
        return s < m
