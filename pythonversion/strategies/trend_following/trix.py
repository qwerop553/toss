from ..base import Strategy
from ..indicators import trix
import pandas as pd


class TrixStrategy(Strategy):
    """
    TRIX 신호선 교차. EMA를 세 번 겹쳐 건 선의 기울기로 매매한다.

    MacdStrategy와 구조는 같다(선 하나 + 신호선 하나). 차이는 평활 횟수다. MACD는
    EMA 두 개의 '차이'를 보고, TRIX는 EMA 세 겹을 통과한 선의 '변화율'을 본다.
    세 번 걸면 분봉의 톱니가 거의 다 지워져서 신호 수가 MACD의 몇 분의 일로 준다.
    왕복 0.23%를 무는 이 하네스에서는 신호가 적은 게 그 자체로 장점이 될 수 있다.
    물론 반대급부는 명확하다 — 전환점을 늦게 잡는다.

    0선 조건을 함께 거는 이유: 신호선 교차만 쓰면 하락 추세 한복판의 잠깐 반등에도
    매수가 걸린다. TRIX > 0(세 겹 EMA가 상승 중)을 같이 요구해 방향을 맞춘다.
    """

    def __init__(self, period=15, signal_period=9, require_positive=True):
        self.period = period
        self.signal_period = signal_period
        self.require_positive = require_positive
        # EMA 3겹 + 신호선. min_periods가 겹쳐 쌓이므로 넉넉히 잡는다.
        self.warmup = period * 3 + signal_period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        line, signal = trix(df["close"], self.period, self.signal_period)
        cond = line > signal
        if self.require_positive:
            cond &= line > 0
        # [매수] TRIX가 신호선 위 (+ 옵션으로 0선 위)
        return cond

    def exits(self, df: pd.DataFrame) -> pd.Series:
        line, signal = trix(df["close"], self.period, self.signal_period)
        # [매도] 신호선 아래로 복귀
        return line < signal
