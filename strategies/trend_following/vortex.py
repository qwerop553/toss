from ..base import Strategy
from ..indicators import vortex
import pandas as pd


class VortexStrategy(Strategy):
    """
    Vortex 지표(VI+ / VI-) 교차.

    AdxDiStrategy와 목적이 같아 보이지만 측정하는 거리가 다르다. DI는 '이번 고가 -
    전 봉 고가'처럼 같은 종류끼리 비교하고, Vortex는 '이번 고가 - 전 봉 저가'라는
    대각선을 본다. 추세가 뒤집힐 때는 고가끼리의 차이보다 이 대각선이 먼저 벌어지기
    때문에 교차가 DI보다 이르게 나온다. 둘을 같이 돌려서 어느 쪽 반응 속도가 이
    종목·이 시간대에 맞는지 보는 게 이 전략의 쓸모다.

    문턱(min_spread)을 두는 이유: 두 선이 1.0 근처에 붙어 있는 횡보장에서는 교차가
    끝없이 일어난다. 왕복 슬리피지 0.23%를 감당하려면 그 정도 교차는 버려야 한다.
    """

    def __init__(self, period=14, min_spread=0.05):
        self.period = period
        self.min_spread = min_spread
        self.warmup = period + 1  # vortex 내부에 shift(1)이 한 겹 더 있다

    def entries(self, df: pd.DataFrame) -> pd.Series:
        vi_plus, vi_minus = vortex(df, self.period)
        # [매수] 상승 소용돌이가 하락 소용돌이를 min_spread만큼 확실히 앞설 때
        return vi_plus - vi_minus >= self.min_spread

    def exits(self, df: pd.DataFrame) -> pd.Series:
        vi_plus, vi_minus = vortex(df, self.period)
        # [매도] 우위가 사라진 시점. 문턱을 대칭으로 걸면 중간 구간에 갇힌다.
        return vi_plus < vi_minus
