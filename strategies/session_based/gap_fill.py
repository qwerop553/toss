from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class GapFillStrategy(Strategy):
    """
    갭 하락 되메움.

    전일 종가보다 gap_pct 이상 낮게 시작한 날, 장중에 그 갭을 메우러 올라가는
    경향에 베팅한다. 악재 없이 수급으로만 벌어진 갭은 상당 부분 당일에 메워진다는
    관찰에 기댄 전략이고, 반대로 진짜 악재로 벌어진 갭에서는 하루 종일 더 빠진다 —
    승률은 높고 한 방이 큰 전형적인 형태라 손익비를 꼭 같이 봐야 한다.

    청산은 전일 종가 회복(갭 메움) 또는 그날 마감. 오버나잇은 하지 않는다.

    ※ 전제조건: 분봉 데이터.
    """

    def __init__(self, gap_pct=0.005):
        self.gap_pct = gap_pct

    def _prev_close(self, df: pd.DataFrame):
        """(전일 종가, 오늘 갭 비율)을 봉 단위로 펼쳐서 돌려준다."""
        d = ind.bar_dates(df)
        daily = df.groupby(d).agg(day_open=("open", "first"), day_close=("close", "last"))
        prev_close = daily["day_close"].shift(1)
        gap = daily["day_open"] / prev_close - 1
        return d.map(prev_close), d.map(gap)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 갭 하락으로 시작했고, 아직 전일 종가를 회복하지 못한 구간
        prev_close, gap = self._prev_close(df)
        return (gap <= -self.gap_pct) & (df["close"] < prev_close)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 갭을 메웠거나(전일 종가 회복) 그날 마지막 봉
        prev_close, _ = self._prev_close(df)
        return (df["close"] >= prev_close) | ind.is_last_bar_of_day(df)
