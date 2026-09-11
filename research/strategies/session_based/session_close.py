from ..base import Strategy
import pandas as pd


class SessionCloseStrategy(Strategy):
    """
    정규장 마감(15:30) 종가 매수 -> 연장세션(20:00) 종가 매도.
    당일 청산, 오버나잇 보유 없음.
    """

    def __init__(self, entry_time="15:30:00", exit_time="20:00:00"):
        self.entry_time = pd.to_datetime(entry_time).time()
        self.exit_time = pd.to_datetime(exit_time).time()

    def _times(self, df: pd.DataFrame):
        if "timestamp" not in df.columns:
            raise ValueError("df에 'timestamp' 컬럼이 필요합니다.")
        ts = pd.to_datetime(df["timestamp"])
        return ts.dt.time, ts.dt.date

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 15:30 봉
        t, _ = self._times(df)
        return t == self.entry_time

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 20:00 봉.
        #
        # 여기에 '그날의 마지막 봉'을 OR로 더한 것은 안전장치다. 어떤 이유로든
        # 20:00 봉이 그날 데이터에 없으면 포지션이 다음 날로 넘어가 버리는데,
        # 이 전략은 오버나잇을 하지 않기로 되어 있다.
        #
        # 미보유 상태의 청산 조건은 to_signals가 어차피 무시하므로, 예전 코드처럼
        # holding 여부를 여기서 따질 필요가 없다.
        t, date = self._times(df)
        is_last_bar_of_day = date != date.shift(-1)   # 다음 행의 날짜가 다르면 그날 마지막 봉
        is_last_bar_of_day.iloc[-1] = True            # 데이터 전체의 마지막 봉도 포함
        return (t == self.exit_time) | is_last_bar_of_day
