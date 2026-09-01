from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class BollingerSqueezeStrategy(Strategy):
    """
    볼린저 스퀴즈 후 상단 돌파.

    변동성은 수축과 팽창을 번갈아 한다. 밴드 폭이 역사적으로 좁아진 구간(스퀴즈)은
    에너지가 응축된 상태로 보고, 그 직후의 방향성 돌파를 추종한다. 스퀴즈 없이
    나오는 돌파는 이미 진행 중인 움직임의 꼬리인 경우가 많아 걸러 낸다.

    '얼마나 좁아야 좁은 건가'는 expanding().rank(pct=True)로 판단한다. 전체 구간에
    rank를 걸면 아직 오지 않은 봉의 밴드 폭이 지금의 순위에 반영되어 lookahead
    bias가 된다 (CLAUDE.md의 expanding() 규약). 여기서는 '지금까지 본 폭 중
    하위 squeeze_q 이내'만 스퀴즈로 친다.
    """

    def __init__(self, period=20, num_std=2.0, squeeze_q=0.2, lookback=10):
        self.period = period
        self.num_std = num_std
        self.squeeze_q = squeeze_q    # 하위 몇 %를 스퀴즈로 볼지
        self.lookback = lookback      # 스퀴즈가 몇 봉 이내에 있었어야 하는지
        self.warmup = period + lookback

    def _bands(self, df: pd.DataFrame):
        return ind.bollinger(df["close"], self.period, self.num_std)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        mid, upper, lower = self._bands(df)
        width = (upper - lower) / mid            # 가격 수준에 무관하게 비교하려고 정규화
        rank = width.expanding().rank(pct=True)  # 미래를 보지 않는 백분위
        # 최근 lookback봉 안에 스퀴즈가 한 번이라도 있었나
        was_squeezed = (rank <= self.squeeze_q).rolling(self.lookback).max() > 0
        # [매수] 응축 직후 상단 밴드 돌파
        return was_squeezed & (df["close"] > upper)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 중심선 이탈 = 팽창이 끝났다고 본다
        mid, _, _ = self._bands(df)
        return df["close"] < mid
