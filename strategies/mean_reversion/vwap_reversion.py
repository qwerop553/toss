from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class VwapReversionStrategy(Strategy):
    """
    당일 VWAP 회귀 (장중 전용).

    VWAP(거래량가중평균가)은 그날 시장 전체의 평균 체결가다. 기관 집행 성과를
    이 선으로 평가하기 때문에 '싸게 사서 VWAP에 파는' 흐름이 실제로 존재하고,
    가격이 VWAP에서 크게 벌어지면 되돌아오는 경향이 분봉에서 관측된다.

    VWAP은 매일 장 시작에 리셋되므로 이 전략은 오버나잇을 하지 않는다.
    그날의 마지막 봉에서 무조건 청산한다.

    ※ 전제조건: 분봉 데이터. 일봉에서는 봉 하나가 하루라 VWAP이 그냥 전형가격이다.
    """

    def __init__(self, band_pct=0.003, exit_at_vwap=True):
        self.band_pct = band_pct          # VWAP 대비 몇 % 아래에서 진입할지
        self.exit_at_vwap = exit_at_vwap  # False면 장 마감까지 들고 간다

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 종가가 당일 VWAP보다 band_pct 이상 싸다
        vwap = ind.session_vwap(df)
        return df["close"] <= vwap * (1 - self.band_pct)

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] VWAP 회복, 또는 그날 마지막 봉(오버나잇 금지)
        last_bar = ind.is_last_bar_of_day(df)
        if not self.exit_at_vwap:
            return last_bar
        return (df["close"] >= ind.session_vwap(df)) | last_bar
