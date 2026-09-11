from ..base import Strategy
from ..indicators import awesome_oscillator
import pandas as pd


class AwesomeOscillatorStrategy(Strategy):
    """
    Awesome Oscillator. 중간가 SMA(5) - SMA(34)의 0선 교차.

    MacdStrategy와 식이 닮았지만 두 군데가 다르다.
      - 종가가 아니라 중간가((고+저)/2)를 쓴다. 장중에 크게 흔들렸다가 제자리로
        돌아온 봉을 MACD는 '아무 일 없음'으로 보지만 AO는 그 진폭을 반영한다.
      - EMA가 아니라 SMA다. 최근 봉에 가중치를 더 주지 않아 반응이 둔한 대신
        한두 봉의 튐에 신호가 뒤집히지 않는다.

    'saucer'(연속 상승 3봉) 같은 원 저자의 추가 규칙은 넣지 않았다. 순차 상태가
    필요해 generate_signals를 직접 짜야 하는데, 0선 교차만으로도 MACD와의 비교라는
    이 전략의 목적은 달성된다.
    """

    def __init__(self, fast=5, slow=34):
        self.fast = fast
        self.slow = slow
        self.warmup = slow

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 단기 중간가 평균이 중기를 넘어섬
        return awesome_oscillator(df, self.fast, self.slow) > 0

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 0선 아래로 복귀
        return awesome_oscillator(df, self.fast, self.slow) < 0
