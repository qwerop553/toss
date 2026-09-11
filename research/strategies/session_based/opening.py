from ..base import Strategy
import pandas as pd


class OpeningRangeStrategy(Strategy):
    """
    정규장 시작 직전 매수 -> 개장 N분 후 매도 전략.

    실제로는 09:00 이전(동시호가)에 주문을 넣어도 체결은 09:00 시가에 이루어지므로,
    '개장 캔들'을 매수 신호, '개장 + hold_minutes 캔들'을 매도 신호로 표시하는
    방식으로 구현했다.

    ※ 전제조건: 분봉 데이터 필요. 일봉으로는 의미 있는 백테스트가 불가능하다.
    """

    def __init__(self, market_open_time="09:30", hold_minutes=30, match_tolerance_minutes=5):
        self.market_open_time = pd.to_datetime(market_open_time).time()
        self.hold_minutes = hold_minutes
        self.match_tolerance_minutes = match_tolerance_minutes  # 목표 시각 캔들이 없을 때 허용 오차

    def _marks(self, df: pd.DataFrame):
        """
        날짜별로 진입/청산 봉을 찾아 두 개의 불리언 Series로 만든다.

        예전 구현은 df를 DatetimeIndex로 갈아끼운 뒤 그 인덱스를 가진 Series를
        반환했다. 그런데 엔진에 들어가는 df는 정수 인덱스라 인덱스가 어긋난 채였고,
        run_backtest가 .iloc으로 접근한 덕분에 우연히 동작하고 있었을 뿐이다.
        여기서는 df의 원래 인덱스를 그대로 유지한다.
        """
        if "timestamp" not in df.columns:
            raise ValueError("df에 'timestamp' 컬럼이 필요합니다.")

        ts = pd.to_datetime(df["timestamp"])
        entry_flags = pd.Series(False, index=df.index)
        exit_flags = pd.Series(False, index=df.index)
        tolerance = pd.Timedelta(minutes=self.match_tolerance_minutes)

        for trade_date, positions in ts.groupby(ts.dt.date).groups.items():
            day_ts = ts.loc[positions].sort_values()

            open_target = pd.Timestamp.combine(trade_date, self.market_open_time)
            exit_target = open_target + pd.Timedelta(minutes=self.hold_minutes)

            # 인덱스가 tz-aware면 target도 동일 타임존으로 맞춰준다 (tz_convert 아님!)
            tz = day_ts.dt.tz
            if tz is not None:
                open_target = open_target.tz_localize(tz)
                exit_target = exit_target.tz_localize(tz)

            entry_at = self._first_at_or_after(day_ts, open_target, tolerance)
            exit_at = self._first_at_or_after(day_ts, exit_target, tolerance)

            # 둘 중 하나라도 못 찾았거나 순서가 뒤집혔으면 그날은 거래하지 않는다
            if entry_at is None or exit_at is None or exit_at <= entry_at:
                continue

            entry_flags.loc[entry_at] = True
            exit_flags.loc[exit_at] = True

        return entry_flags, exit_flags

    @staticmethod
    def _first_at_or_after(day_ts: pd.Series, target: pd.Timestamp, tolerance: pd.Timedelta):
        """target 시각 이후 가장 가까운 봉의 '인덱스 라벨'을 tolerance 이내에서 찾는다."""
        candidates = day_ts[day_ts >= target]
        if candidates.empty:
            return None
        if candidates.iloc[0] - target <= tolerance:
            return candidates.index[0]
        return None

    def entries(self, df: pd.DataFrame) -> pd.Series:
        return self._marks(df)[0]

    def exits(self, df: pd.DataFrame) -> pd.Series:
        return self._marks(df)[1]
