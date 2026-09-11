from ..base import Strategy
import numpy as np
import pandas as pd


class Nr7BreakoutStrategy(Strategy):
    """
    NR7 돌파. '최근 7봉 중 진폭이 가장 좁은 봉'을 셋업으로 잡고 그 고가를 돌파하면 산다.

    BollingerSqueezeStrategy와 발상은 같다 — 변동성이 수축하면 팽창이 뒤따른다.
    다른 점은 측정 방식이다. 스퀴즈는 밴드 폭이라는 '통계량'이 좁아졌는지를 보고,
    NR7은 봉 하나의 고저 진폭이 최근 7봉 중 최소인지를 본다. 통계량은 여러 봉에
    걸쳐 천천히 좁아지지만 NR7은 특정 한 봉을 딱 집어낸다. 그래서 돌파 기준선이
    '밴드'가 아니라 '그 봉의 고가'라는 구체적인 가격이 된다.

    lookahead를 막는 지점이 두 군데다.
      - 셋업 판정 자체는 현재 봉까지만 본다 (rolling min).
      - 기준선은 shift(1) 후 ffill이다. 현재 봉이 NR7이라고 해서 그 봉의 고가를
        같은 봉에서 돌파 기준으로 쓰면, 아직 확정되지 않은 고가를 보는 셈이 된다.

    valid_bars가 있는 이유: ffill만 하면 사흘 전 셋업의 고가를 아직도 기준선으로
    들고 있게 된다. 수축-팽창 논리는 셋업 직후 몇 봉 안에서만 유효하므로 유효기간을
    둔다. 이 값이 없으면 사실상 '아무 옛날 고가 돌파' 전략이 되어버린다.
    """

    def __init__(self, period=7, valid_bars=20):
        self.period = period
        self.valid_bars = valid_bars
        self.warmup = period + 1

    def _setup(self, df: pd.DataFrame):
        """(돌파 기준 고가, 이탈 기준 저가, 셋업 이후 경과 봉 수)."""
        rng = df["high"] - df["low"]
        is_narrow = rng <= rng.rolling(self.period).min()

        # shift(1)로 '직전 봉까지 확정된 셋업'만 남긴 뒤 ffill로 끌고 온다.
        setup_high = df["high"].where(is_narrow).shift(1).ffill()
        setup_low = df["low"].where(is_narrow).shift(1).ffill()

        pos = pd.Series(np.arange(len(df)), index=df.index)
        age = pos - pos.where(is_narrow).shift(1).ffill()
        return setup_high, setup_low, age

    def entries(self, df: pd.DataFrame) -> pd.Series:
        setup_high, _, age = self._setup(df)
        # [매수] 유효기간 안에서 셋업 봉의 고가를 위로 돌파
        return (df["close"] > setup_high) & (age <= self.valid_bars)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        _, setup_low, _ = self._setup(df)
        # [매도] 셋업 봉의 저가마저 깨짐 = 돌파가 가짜였다. 유효기간을 걸지 않는 건
        # 셋업이 낡았다는 이유로 청산을 막으면 포지션이 갇히기 때문이다.
        return df["close"] < setup_low
