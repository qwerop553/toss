from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class OpeningRangeBreakoutStrategy(Strategy):
    """
    오프닝 레인지 돌파 (ORB).

    개장 후 range_bars분의 고가·저가를 그날의 기준 박스로 잡는다. 그 박스 위를
    뚫으면 그날의 방향이 정해진 것으로 보고 따라붙고, 박스 아래로 빠지면 손절한다.
    오버나잇은 하지 않고 그날 마지막 봉에서 반드시 청산한다.

    같은 폴더의 OpeningRangeStrategy와 이름이 비슷하지만 완전히 다른 전략이다.
    그쪽은 '개장에 사서 N분 뒤 무조건 판다'는 시간 규칙이고, 이쪽은 '박스를 뚫을
    때까지 기다렸다가 산다'는 조건부 진입이다.

    ※ 전제조건: 분봉 데이터. 일봉에서는 박스를 만들 수 없다.
    """

    def __init__(self, range_bars=30, stop_at_range_low=True):
        self.range_bars = range_bars
        self.stop_at_range_low = stop_at_range_low  # False면 손절 없이 마감까지 보유

    def _range(self, df: pd.DataFrame):
        """(박스 고가, 박스 저가, 박스 형성 구간 여부)를 봉 단위로 펼쳐서 돌려준다."""
        d = ind.bar_dates(df)
        # 그날 몇 번째 봉인가. 09:00 같은 벽시계 시각이 아니라 순번으로 세는 이유는
        # 결측 봉(거래 없는 분)이 있어도 박스 길이가 흔들리지 않게 하려는 것이다.
        bar_no = df.groupby(d).cumcount()
        forming = bar_no < self.range_bars

        # 박스 구간의 고가/저가만 남기고 누적 최대·최소를 취한 뒤, 그 값을 그날의
        # 나머지 봉으로 끌고 간다(ffill). groupby를 걸어야 전날 값이 새 나가지 않는다.
        high = df["high"].where(forming).groupby(d).cummax().groupby(d).ffill()
        low = df["low"].where(forming).groupby(d).cummin().groupby(d).ffill()
        return high, low, forming

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 박스 형성이 끝난 뒤, 종가가 박스 고가를 돌파
        high, _, forming = self._range(df)
        return (~forming) & (df["close"] > high)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 박스 저가 이탈(손절) 또는 그날 마지막 봉(오버나잇 금지)
        _, low, forming = self._range(df)
        last_bar = ind.is_last_bar_of_day(df)
        if not self.stop_at_range_low:
            return last_bar
        return last_bar | ((~forming) & (df["close"] < low))
