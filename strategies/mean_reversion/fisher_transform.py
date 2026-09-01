from ..base import Strategy
from ..indicators import fisher_transform
import pandas as pd


class FisherTransformStrategy(Strategy):
    """
    Fisher Transform 반전. 가격 분포를 정규분포 쪽으로 편 뒤 극단값을 노린다.

    ZScoreReversionStrategy와 목적은 같고 전처리가 다르다. Z-Score는 가격이
    정규분포라고 가정하고 표준편차로 나누는데, 실제 가격은 꼬리가 두꺼워서
    '2시그마 이탈'이 생각보다 자주 나온다. Fisher는 0.5*ln((1+x)/(1-x))를 걸어
    ±1 근처를 무한대 쪽으로 늘려버린다 — 진짜 극단만 큰 값으로 남고 어중간한
    이탈은 0 근처로 눌린다. 그래서 같은 문턱을 써도 신호가 훨씬 적고 선명하다.

    entry_level=-1.5는 z=-1.5와 다른 의미다. Fisher 값은 대체로 ±2 안에서 놀고
    ±1.5는 꽤 드문 구간이다. 문턱 감각을 Z-Score에서 그대로 옮겨오면 안 된다.
    """

    def __init__(self, period=10, entry_level=-1.5, exit_level=0.0):
        self.period = period
        self.entry_level = entry_level
        self.exit_level = exit_level
        self.warmup = period * 2  # 정규화 창 + ewm 두 겹

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 변환값이 아래쪽 극단 = 최근 범위의 바닥에 오래 눌려 있었다
        return fisher_transform(df, self.period) <= self.entry_level

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 중립 복귀
        return fisher_transform(df, self.period) >= self.exit_level
