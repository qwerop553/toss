from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class MfiStrategy(Strategy):
    """
    MFI(Money Flow Index) 과매도 반등.

    RSI에 거래량을 곱한 지표다. RSI는 '얼마나 올랐나'만 보지만 MFI는 '얼마의 돈이
    실려서 올랐나'까지 본다. 거래량 없이 흘러내린 하락(= 팔 사람이 없어서 빠진 것)과
    대량 투매를 구분할 수 있다는 게 차이다.

    과매도 구간을 벗어나는 봉에서 진입하고 중립선 위에서 청산한다.
    """

    def __init__(self, period=14, oversold=20, exit_level=60):
        self.period = period
        self.oversold = oversold
        self.exit_level = exit_level
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 직전 봉까지 과매도였다가 이번 봉에 탈출
        m = ind.mfi(df, self.period)
        return (m > self.oversold) & (m.shift(1) <= self.oversold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        return ind.mfi(df, self.period) >= self.exit_level
