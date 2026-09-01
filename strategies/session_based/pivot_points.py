from ..base import Strategy
from ..indicators import prev_day_ohlc, is_last_bar_of_day
import pandas as pd


class PivotPointStrategy(Strategy):
    """
    전일 피봇 기준 지지 반등. S1까지 밀리면 사서 피봇에서 판다.

    다른 평균회귀 전략과 기준선의 성격이 다르다. 볼린저·Z-Score·켈트너는 전부
    '최근 N봉'이라는 굴러가는 창에서 기준선을 뽑는데, 여기서는 전일 고가·저가·종가
    딱 세 숫자로 오늘 하루치 기준선을 고정한다. 장중 내내 움직이지 않는 선이라
    실제로 그 가격에 주문이 쌓이고, 그 자기실현이 이 지표의 근거다.

        PP = (전일고 + 전일저 + 전일종) / 3
        S1 = 2*PP - 전일고     (1차 지지)
        R1 = 2*PP - 전일저     (1차 저항)

    lookahead 주의: 오늘 봉들이 오늘 고가를 보면 안 된다. prev_day_ohlc가 일별
    집계 후 하루 shift로 그걸 막는다 — groupby.transform("max")를 그냥 쓰면
    아침 9시 봉이 그날 장 마감 고가를 아는 사태가 된다.

    마감 청산을 넣은 이유: 기준선이 '전일' 값이라 다음 날이 되면 선 자체가 통째로
    바뀐다. 오버나잇으로 넘기면 진입 근거가 사라진 포지션을 들고 있게 된다.
    """

    def __init__(self, entry_ratio=1.0, exit_at="pivot"):
        # entry_ratio: 1.0이면 S1, 0.5면 PP와 S1의 중간. 문턱을 PP 쪽으로 당기면
        # 진입 기회가 늘고 되돌림 폭은 줄어든다.
        self.entry_ratio = entry_ratio
        if exit_at not in ("pivot", "r1"):
            raise ValueError("exit_at은 'pivot' 또는 'r1'이어야 합니다.")
        self.exit_at = exit_at
        self.warmup = 0  # 전일 데이터가 없는 첫날은 NaN이라 자연히 신호가 죽는다

    def _levels(self, df: pd.DataFrame):
        prev_high, prev_low, prev_close = prev_day_ohlc(df)
        pivot = (prev_high + prev_low + prev_close) / 3
        s1 = 2 * pivot - prev_high
        r1 = 2 * pivot - prev_low
        return pivot, s1, r1

    def entries(self, df: pd.DataFrame) -> pd.Series:
        pivot, s1, _ = self._levels(df)
        entry_line = pivot - self.entry_ratio * (pivot - s1)
        # [매수] 지지선까지 눌림
        return df["close"] <= entry_line

    def exits(self, df: pd.DataFrame) -> pd.Series:
        pivot, _, r1 = self._levels(df)
        target = pivot if self.exit_at == "pivot" else r1
        # [매도] 목표선 도달, 또는 그날 마지막 봉 (오버나잇 금지)
        return (df["close"] >= target) | is_last_bar_of_day(df)
