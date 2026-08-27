from ..base import Strategy
import pandas as pd


class BollingerBandStrategy(Strategy):
    """
    볼린저 밴드 기반 평균회귀 전략.
    종가가 하단 밴드를 이탈(터치)하면 매수하고,
    중심선(이동평균) 또는 상단 밴드로 회귀하면 매도한다.
    """

    def __init__(self, period=20, num_std=2.0, exit_at_middle=True):
        self.period = period
        self.num_std = num_std
        self.exit_at_middle = exit_at_middle  # True: 중심선에서 청산 / False: 상단 밴드에서 청산

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        mid = close.rolling(self.period).mean()
        std = close.rolling(self.period).std()
        upper = mid + self.num_std * std
        lower = mid - self.num_std * std

        signal = pd.Series(0, index=df.index)
        holding = False

        for i in range(len(df)):
            # 워밍업 기간(rolling window 미충족) 동안은 신호를 생성하지 않음
            if i < self.period:
                continue

            # [매수 조건] 미보유 상태에서 종가가 하단 밴드 이하로 하락
            if not holding and close.iloc[i] <= lower.iloc[i]:
                signal.iloc[i] = 1
                holding = True

            # [매도 조건] 보유 중 종가가 청산 기준선(중심선 또는 상단 밴드) 이상으로 회복
            elif holding:
                exit_price = mid.iloc[i] if self.exit_at_middle else upper.iloc[i]
                if close.iloc[i] >= exit_price:
                    signal.iloc[i] = -1
                    holding = False

        return signal