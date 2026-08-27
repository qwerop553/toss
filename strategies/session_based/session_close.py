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

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "timestamp" not in df.columns:
            raise ValueError("df에 'timestamp' 컬럼이 필요합니다.")

        ts = pd.to_datetime(df["timestamp"])
        t = ts.dt.time
        date = ts.dt.date

        signal = pd.Series(0, index=df.index)
        holding = False
        n = len(df)

        for i in range(n):
            cur_t = t.iloc[i]
            is_last_bar_of_day = (i == n - 1) or (date.iloc[i] != date.iloc[i + 1])

            # [매수] 미보유 상태에서 15:30 봉 도달
            if not holding and cur_t == self.entry_time:
                signal.iloc[i] = 1
                holding = True

            # [매도] 보유 상태에서 20:00 봉 도달
            elif holding and cur_t == self.exit_time:
                signal.iloc[i] = -1
                holding = False

            # [안전장치] 어떤 이유로든 20:00 봉이 그날 없었는데 아직 보유 중이면
            # 당일 마지막 봉에서 강제 청산 (오버나잇 리스크로 새는 것 방지)
            elif holding and is_last_bar_of_day:
                signal.iloc[i] = -1
                holding = False

        return signal