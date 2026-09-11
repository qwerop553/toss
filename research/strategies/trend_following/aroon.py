from ..base import Strategy
from ..indicators import aroon
import pandas as pd


class AroonStrategy(Strategy):
    """
    Aroon 교차. '최근 고점이 저점보다 최근인가'로 추세 방향을 판정한다.

    다른 추세 전략과 재료가 다른 게 이 전략의 존재 이유다. EMA·MACD·TRIX는 전부
    가격의 크기를 평활해서 보는데, Aroon은 크기를 통째로 버리고 시간만 본다 —
    "창 안의 최고가가 몇 봉 전이었나". 그래서 가격이 거의 안 움직인 횡보 구간에서도
    고점 갱신이 시작되면 바로 100에 붙는다. 이동평균이 아직 꼬여 있을 때 먼저 켜지는
    대신, 크기를 무시한 만큼 잔파동에도 잘 켜진다.

    threshold를 두는 이유: Up > Down 교차만 쓰면 횡보장에서 두 선이 계속 자리를
    바꾸며 신호가 난사된다. 'Up이 충분히 높을 때만'이라는 조건을 하나 더 걸어
    고점 갱신이 실제로 최근일 때로 진입을 좁힌다.
    """

    def __init__(self, period=25, threshold=70):
        self.period = period
        self.threshold = threshold
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        up, down = aroon(df, self.period)
        # [매수] 상승 Aroon이 하락 Aroon을 이기고, 그 자체로도 충분히 높을 때
        return (up > down) & (up >= self.threshold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        up, down = aroon(df, self.period)
        # [매도] 주도권이 하락 쪽으로 넘어감. 청산은 문턱을 걸지 않는다 —
        # 진입보다 청산이 까다로우면 손실 구간에서 못 빠져나온다.
        return down > up
