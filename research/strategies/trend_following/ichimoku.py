from ..base import Strategy
import pandas as pd


class IchimokuStrategy(Strategy):
    """
    일목균형표. 전환선/기준선 크로스를 구름(선행스팬 A·B) 위에서만 받는다.

    구름은 26봉 앞으로 밀어 그린 과거 값이다 (shift(+26)). 미래 데이터를 당겨
    쓰는 게 아니라 과거 데이터를 미래 자리에 놓는 것이라 lookahead가 아니다 —
    헷갈리기 쉬운 지점이라 적어 둔다.

    구름 위 = 매수세 우위 구간. 그 안에서만 전환선(단기) > 기준선(중기)을 받으면
    '추세 방향으로만 크로스를 따르는' 필터가 공짜로 생긴다.
    """

    def __init__(self, tenkan=9, kijun=26, senkou_b=52):
        self.tenkan = tenkan
        self.kijun = kijun
        self.senkou_b = senkou_b
        self.warmup = senkou_b + kijun  # 구름을 kijun만큼 밀어 그리므로 그만큼 더

    @staticmethod
    def _mid(df: pd.DataFrame, period: int) -> pd.Series:
        """해당 기간의 (최고가 + 최저가) / 2. 일목균형표의 모든 선이 이 형태다."""
        return (df["high"].rolling(period).max() + df["low"].rolling(period).min()) / 2

    def _lines(self, df: pd.DataFrame):
        tenkan = self._mid(df, self.tenkan)
        kijun = self._mid(df, self.kijun)
        span_a = ((tenkan + kijun) / 2).shift(self.kijun)
        span_b = self._mid(df, self.senkou_b).shift(self.kijun)
        cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
        return tenkan, kijun, cloud_top

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 구름 위에서 전환선이 기준선을 상향 돌파
        tenkan, kijun, cloud_top = self._lines(df)
        crossed = (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
        return crossed & (df["close"] > cloud_top)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 전환선이 기준선 아래로 내려가거나, 구름 위 구간을 잃음
        tenkan, kijun, cloud_top = self._lines(df)
        return (tenkan < kijun) | (df["close"] < cloud_top)
