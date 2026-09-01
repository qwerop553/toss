from ..base import Strategy
from ..indicators import ultimate_oscillator
import pandas as pd


class UltimateOscillatorStrategy(Strategy):
    """
    궁극 오실레이터. 7/14/28봉을 4:2:1로 섞은 과매도 반전.

    StochasticStrategy나 RsiReversionStrategy를 돌려 본 사람이 반드시 만나는 문제가
    '기간을 뭘로 잡을까'다. 짧게 잡으면 시끄럽고 길게 잡으면 늦는데, 최적값은 구간마다
    바뀐다. Larry Williams의 답은 고르지 말고 세 개를 한 번에 섞으라는 것이다.
    가중치 4:2:1은 짧은 쪽에 비중을 더 주되 긴 쪽이 방향을 붙잡게 한 배분이다.

    --optimize의 관점에서 보면 이 전략은 '기간 축을 하나 지운 스토캐스틱'이다.
    탐색할 파라미터가 사실상 문턱 두 개뿐이라 과최적화 여지가 작다.
    """

    def __init__(self, short=7, mid=14, long=28, oversold=30, exit_level=55):
        self.short = short
        self.mid = mid
        self.long = long
        self.oversold = oversold
        self.exit_level = exit_level
        self.warmup = long + 1  # 내부에서 전 봉 종가를 쓰므로 한 봉 더

    def _uo(self, df: pd.DataFrame) -> pd.Series:
        return ultimate_oscillator(df, self.short, self.mid, self.long)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 세 기간이 모두 매수 압력 부족을 가리킴 = 과매도
        return self._uo(df) <= self.oversold

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 중립 위로 회복. 50이 아니라 55를 기본값으로 둔 건 중립선 근처의
        # 잔떨림으로 진입/청산이 붙어버리는 걸 피하기 위해서다.
        return self._uo(df) >= self.exit_level
