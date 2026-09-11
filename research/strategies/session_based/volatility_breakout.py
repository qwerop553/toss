from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class VolatilityBreakoutStrategy(Strategy):
    """
    래리 윌리엄스 변동성 돌파. 한국 개인투자자 자동매매의 사실상 표준 레시피다.

        목표가 = 오늘 시가 + k x (어제 고가 - 어제 저가)

    장중에 종가가 목표가를 넘으면 매수하고 그날 마감에 청산한다. 발상은
    '어제 움직인 폭의 k배만큼 오늘 한 방향으로 밀어붙였다면 그건 노이즈가 아니다'
    이다. k는 보통 0.5 — 어제 변동폭의 절반을 뚫는 순간이 기준이 된다.

    lookahead 주의: 목표가에 들어가는 값은 '어제의 확정된 고저'와 '오늘의 시가'
    뿐이다. 오늘 고가를 쓰면 미래를 보는 것이 되어 백테스트가 환상적으로 나온다.

    ※ 전제조건: 분봉 데이터. 일봉이면 진입과 청산이 같은 봉이라 의미가 없다.
    """

    def __init__(self, k=0.5):
        self.k = k

    def _target(self, df: pd.DataFrame) -> pd.Series:
        d = ind.bar_dates(df)
        daily = df.groupby(d).agg(
            day_open=("open", "first"),
            day_high=("high", "max"),
            day_low=("low", "min"),
        )
        # shift(1) = 전 거래일. 오늘 데이터는 시가만 쓴다.
        prev_range = (daily["day_high"] - daily["day_low"]).shift(1)
        target = daily["day_open"] + self.k * prev_range
        # 날짜별 목표가를 봉 단위로 펼친다. 첫날은 전일이 없어 NaN -> 비교가 False.
        return d.map(target)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 목표가 돌파
        return df["close"] >= self._target(df)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 그날 마지막 봉에서 무조건 청산 (원 전략은 당일 종가 청산이다)
        return ind.is_last_bar_of_day(df)
