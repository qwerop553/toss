from ..base import Strategy
import pandas as pd
import numpy as np

class EmaCrossStrategyWithATR(Strategy):
    """
    변동성이 죽으면 바로 매도하자
    """

    def __init__(self, fast=6, slow=12, atr_period=20):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period

    def generate_signals(
        self, df: pd.DataFrame, min_diff_pct: float = 0.002, cooldown: int = 3
    ) -> pd.Series:
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()

        # 정배열 조건용 이동평균선
        ma5 = df["close"].rolling(window=5).mean()
        ma20 = df["close"].rolling(window=20).mean()

        # ATR 계산
        tr = df["high"] - df["low"]
        atr = tr.ewm(span=self.atr_period).mean()
        patr = atr.rank(pct=True)

        # 단순 크로스가 아닌 '이평선 간격 비율' 계산 (노이즈 매매 방지)
        ema_diff_pct = (ema_fast - ema_slow) / df["close"]

        signal = pd.Series(0, index=df.index)
        holding = False
        last_trade_idx = -cooldown  # 쿨다운 추적용
        patr_threshold = patr.mean()
        warmup = max(self.slow, self.atr_period, 20)

        for i in range(len(df)):
            if i < warmup:
                continue

            current_patr = patr.iloc[i]
            is_aligned = ma5.iloc[i] > ma20.iloc[i]

            # 1. 변동성 축소 시 강제 청산 (단, 정배열 시 예외 유지)
            if holding and (current_patr < patr_threshold):
                if not is_aligned:
                    signal.iloc[i] = -1
                    holding = False
                    last_trade_idx = i
                    continue

            # 2. 진입/청산 로직 (최소 매매 간격 쿨다운 적용)
            if (i - last_trade_idx) >= cooldown:

                # [매수] 0주 + 변동성 조건 + 이평선 간격이 일정 수준 이상 벌어지며 골든크로스
                if (
                    not holding
                    and current_patr >= patr_threshold
                    and ema_diff_pct.iloc[i] > min_diff_pct
                ):
                    signal.iloc[i] = 1
                    holding = True
                    last_trade_idx = i

                # [매도] 1주 + 데드크로스 확실화 (단기선이 장기선 아래로 일정 수준 이상 하락)
                elif holding and ema_diff_pct.iloc[i] < -min_diff_pct:
                    signal.iloc[i] = -1
                    holding = False
                    last_trade_idx = i

        return signal