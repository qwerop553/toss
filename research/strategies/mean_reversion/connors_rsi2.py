from ..base import Strategy
from ..indicators import rsi
import pandas as pd


class ConnorsRsi2Strategy(Strategy):
    """
    Larry Connors의 RSI(2). '추세 안에서의 눌림목만 산다'는 규칙.

    RsiReversionStrategy와 결정적으로 다른 점이 둘 있다.

    1) 기간이 2다. 14가 아니라. RSI(2)는 거의 매 봉 0~100을 오가는 극단적인 지표라
       단독으로는 쓸 수 없다 — 그게 의도다. '아주 짧은 과매도'만 집어내려고 일부러
       민감하게 만든 것이다.
    2) 장기 이동평균 위에서만 산다. 평균회귀 전략이 하락 추세에서 계속 물타기하다
       죽는 걸 이 필터 하나가 막는다. Connors의 원 규칙은 일봉 200일선인데, 여기서는
       분봉이므로 trend_period로 열어 뒀다.

    청산이 특이하다. RSI가 중립으로 돌아오길 기다리지 않고 '단기 이동평균 위로
    올라오면' 바로 나온다. 눌림목 반등의 첫 구간만 먹고 빠지는 설계라 보유 기간이
    아주 짧다 — 그만큼 왕복 슬리피지 0.23%가 성과를 크게 갉아먹는 구조이기도 하다.
    """

    def __init__(self, rsi_period=2, oversold=10, trend_period=200, exit_ma=5):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.trend_period = trend_period
        self.exit_ma = exit_ma
        self.warmup = trend_period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        trend_ok = close > close.rolling(self.trend_period).mean()
        # [매수] 상승 추세 안에서 아주 짧은 과매도가 나왔을 때
        return trend_ok & (rsi(close, self.rsi_period) <= self.oversold)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        # [매도] 단기 평균 위로 복귀 = 눌림목 반등이 일어났다
        return close > close.rolling(self.exit_ma).mean()
