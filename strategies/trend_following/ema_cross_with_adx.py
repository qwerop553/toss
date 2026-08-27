from ..base import Strategy
import pandas as pd


class EmaCrossStrategyWithADX(Strategy):
    """
    EMA 크로스에 변동성 필터를 얹은 전략.
    ATR 백분위가 그동안의 평균 이상일 때(= 시장이 충분히 움직일 때)만 매매한다.
    """

    def __init__(self, fast=6, slow=12, atr_period=20):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period

        # EMA와 ATR 둘 다 익어야 신호를 낼 수 있다.
        self.warmup = max(slow, atr_period)

    def _indicators(self, df: pd.DataFrame):
        """크로스 전환과 변동성 필터를 한 번에 계산한다."""
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()

        # 정배열이면 +1, 역배열이면 -1. 그 값의 diff가 0이 아닌 지점이 크로스다.
        raw_state = pd.Series(0, index=df.index)
        raw_state[ema_fast > ema_slow] = 1
        raw_state[ema_fast < ema_slow] = -1
        transition = raw_state.diff().fillna(0)

        tr = (df["high"] - df["low"]).shift(1).fillna(0)
        atr = tr.ewm(span=self.atr_period).mean()

        # patr: '지금까지 본 ATR 중 현재 ATR이 상위 몇 %인가'.
        #   expanding()을 쓰는 이유는 미래를 보지 않기 위해서다. 전체 구간에
        #   rank(pct=True)를 걸면 아직 오지 않은 봉의 ATR까지 순위에 반영되어
        #   lookahead bias가 생긴다.
        #
        #   예전 구현은 매 봉마다 atr.iloc[:i+1].rank()를 새로 계산하는 O(n^2)
        #   중첩 루프였다. expanding().rank()가 정확히 같은 값을 한 번에 낸다.
        patr = atr.expanding().rank(pct=True)

        # 기준선은 '직전 봉까지의 patr 평균'. shift(1)로 현재 봉을 제외한다
        # (예전 구현의 patr.iloc[:i].mean()과 동일). 첫 봉은 비교 대상이 없어 0.
        patr_mean = patr.expanding().mean().shift(1).fillna(0.0)

        return transition, patr, patr_mean

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 변동성이 평균 이상인 상태에서 골든크로스
        transition, patr, patr_mean = self._indicators(df)
        return (patr >= patr_mean) & (transition > 0)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 변동성이 평균 이상인 상태에서 데드크로스
        transition, patr, patr_mean = self._indicators(df)
        return (patr >= patr_mean) & (transition < 0)
