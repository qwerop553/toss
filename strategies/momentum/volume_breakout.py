from ..base import Strategy
import pandas as pd


class VolumeSpikeBreakoutStrategy(Strategy):
    """
    거래량 급증 + 양봉 돌파.

    분봉에서 의미 있는 움직임은 거의 항상 거래량을 동반한다. 거래량 없이 오른
    봉은 호가 공백에 몇 주가 체결된 것일 뿐이라 되돌림이 크다. 그래서
    '평소 거래량의 mult배 이상' + '종가가 직전 고가 돌파'를 동시에 요구한다.

    청산은 추세선(EMA) 이탈. 급등 후 눌림에서 오래 버티지 않는 편이 낫다.
    """

    def __init__(self, volume_period=20, mult=3.0, exit_period=20):
        self.volume_period = volume_period
        self.mult = mult
        self.exit_period = exit_period
        self.warmup = max(volume_period, exit_period)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # 기준 거래량은 shift(1) — 현재 봉의 거래량이 자기 기준선에 섞이면
        # 급증 판정이 스스로를 희석한다.
        avg_volume = df["volume"].rolling(self.volume_period).mean().shift(1)
        spike = df["volume"] >= self.mult * avg_volume
        # [매수] 거래량 급증 + 직전 봉 고가 돌파 (방향 확인)
        return spike & (df["close"] > df["high"].shift(1))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 단기 EMA 이탈
        return df["close"] < df["close"].ewm(span=self.exit_period).mean()
