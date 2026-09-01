from ..base import Strategy
import pandas as pd


class ZScoreReversionStrategy(Strategy):
    """
    Z-Score 평균회귀. 종가가 이동평균에서 표준편차 몇 배나 벗어났는지로 매매한다.

    볼린저 밴드와 수식은 같지만 관점이 다르다. 볼린저는 '밴드를 건드렸나'를 보고,
    이쪽은 z값 자체를 연속량으로 두고 진입 문턱과 청산 문턱을 따로 준다.
    entry_z=-2, exit_z=0이면 '2시그마 아래에서 사서 평균에서 판다'가 된다.
    exit_z를 양수로 두면 평균을 지나 반대편까지 끌고 가는 공격적 버전이 된다.

    주의: 기본값(period=20, entry_z=-2, exit_z=0)은 BollingerBandStrategy의
    기본값과 수학적으로 같은 조건이라 신호가 완전히 일치한다. 둘을 같이 돌리는
    의미는 --optimize를 걸었을 때 생긴다 (이쪽만 진입·청산 문턱을 따로 움직인다).
    """

    def __init__(self, period=20, entry_z=-2.0, exit_z=0.0):
        self.period = period
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.warmup = period

    def _z(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        ma = close.rolling(self.period).mean()
        # 표준편차 0(가격이 창 내내 고정)은 0으로 나누기가 되므로 NaN 처리.
        # NaN은 비교에서 False가 되어 자연히 신호가 죽는다.
        sd = close.rolling(self.period).std().replace(0, pd.NA)
        return (close - ma) / sd

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 평균에서 아래로 entry_z 이상 벌어짐 = 과매도
        return self._z(df) <= self.entry_z

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 평균(또는 지정한 상단)까지 회귀
        return self._z(df) >= self.exit_z
