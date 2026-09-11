from ..base import Strategy
import pandas as pd


class RocMomentumStrategy(Strategy):
    """
    변화율(Rate of Change) 모멘텀. '오른 게 더 오른다'에 그대로 베팅한다.

    period봉 전 대비 수익률이 threshold를 넘으면 진입한다. 이동평균 교차와 달리
    선이 꼬일 때까지 기다리지 않고 가격 변화 자체를 직접 본다 — 그래서 가장 빠르고
    가장 시끄럽다. threshold가 유일한 방어선이라 이 값이 전략의 전부다.

    분봉에서 threshold=0.002(0.2%)면 하루에도 수십 번 걸린다. 슬리피지가 왕복
    0.23%인 걸 감안하면 문턱을 후하게 잡아야 실전에서 남는다.
    """

    def __init__(self, period=20, threshold=0.003, exit_threshold=0.0):
        self.period = period
        self.threshold = threshold
        self.exit_threshold = exit_threshold
        self.warmup = period

    def _roc(self, df: pd.DataFrame) -> pd.Series:
        return df["close"].pct_change(self.period)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 최근 period봉 수익률이 문턱 돌파
        return self._roc(df) >= self.threshold

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 모멘텀 소멸 (기본값 0 = 상승분을 다 반납한 시점)
        return self._roc(df) <= self.exit_threshold
