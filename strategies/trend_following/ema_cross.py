from ..base import Strategy
import pandas as pd

class EmaCrossStrategy(Strategy):
    """
    init(fast=N, slow=M)
    지수평균선의 Golden Cross 전략
    긴 기간 동안의 지수평균선을 짧은 기간의 이동평균선이 돌파하면 매수
    긴 기간 동안의 지수평균선을 짧은 기간의 이동평균선이 하락하면 매도
    """
    
    def __init__(self, fast: int = 60, slow: int =  120):

        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()

        raw_state = pd.Series(0, index=df.index)
        raw_state[ema_fast > ema_slow] = 1
        raw_state[ema_fast < ema_slow] = -1

        transition = raw_state.diff().fillna(0)
        signal = pd.Series(0, index=df.index)
        signal[transition > 0] = 1 # 매수 
        signal[transition < 0] = -1 # 매도

        # 초기 구간 보정. 
        # ema는 초기값을 그대로 쓰기 때문에, 앞부분의 신뢰도가 낮다.
        warmup = self.slow
        signal.iloc[:warmup] = 0

        return signal

