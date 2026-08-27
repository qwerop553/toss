from ..base import Strategy
import pandas as pd
import numpy as np

class EmaCrossStrategyWithADX(Strategy):

    def __init__(self, fast=6, slow=12, atr_period=20):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()

        tr = (df["high"] - df["low"]).shift(1).fillna(0)
        atr = tr.ewm(span=self.atr_period).mean() 
        #percentile atr
        patr = pd.Series(0.0, index=df.index)
        patr_mean = pd.Series(0.0, index=df.index)
        for i in range(len(df)):
            window = atr.iloc[:i+1]
            patr.iloc[i] = window.rank(pct=True).iloc[-1]
            patr_mean.iloc[i] = patr.iloc[:i].mean() if i > 0 else 0.0

        raw_state = pd.Series(0, index=df.index)
        raw_state[ema_fast > ema_slow] = 1
        raw_state[ema_fast < ema_slow] = -1

        transition = raw_state.diff().fillna(0)

        signal = pd.Series(0, index=df.index)
        holding = False

        for i in range(len(df)):
            # 워밍업 기간 동안은 신호를 생성하지 않음
            if i < max(self.slow, self.atr_period):
                continue

            # 조건: ATR 백분위수가 평균 이상일 때만 매매 시도
            if patr.iloc[i] >= patr_mean[i]:

                # [매수 조건] 주식이 없고(0주), 매수 신호(골든크로스 등)가 발생한 경우
                if not holding and transition.iloc[i] > 0:
                    signal.iloc[i] = 1
                    holding = True  # 보유 상태로 변경 (1주)

                # [매도 조건] 주식을 가지고 있고(1주), 매도 신호(데드크로스 등)가 발생한 경우
                elif holding and transition.iloc[i] < 0:
                    signal.iloc[i] = -1
                    holding = False  # 미보유 상태로 변경 (0주)

        return signal
    