from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class AfternoonRangeBottomStrategy(Strategy):
    """
    오후 일중 레인지 하단 → 종가 회귀.

    AfternoonOversoldStrategy와 같은 '오후 되돌림' 가족이지만 재료가 다르다.
    저쪽은 RSI(속도)로 눌림을 재고, 이쪽은 당일 고저 레인지 안에서의 위치(수준)로
    잰다. RSI는 천천히 오래 빠진 날을 못 잡고, 레인지 위치는 하루 종일 좁게 움직인
    날에도 하단을 만들어 낸다 — 겹치는 날이 많지만 같은 날은 아니다.

    발굴 근거 (1분봉, 8종목 × 52거래일):
      pos = (종가 - 당일 누적 저가) / (당일 누적 고가 - 당일 누적 저가)
      13시 이후 pos < 0.1 지점에서 종가까지 +24.7bp(t=+12.6). 전 구간 평균은
      -6.7bp다. 임계값을 0.2로 풀면 +15.6bp, 0.3이면 +10.0bp로 단조롭게 약해진다 —
      하단에 붙을수록 강해지는 형태라 임계값 하나를 우연히 맞춘 결과가 아니다.

    검증 (코스피50 전 종목, 거래당 비용 전 총수익 / 왕복비용 23bp):
      파라미터를 고를 때 쓴 30종목  +49.5bp(t=+4.8) 왕복287회 → 비용 후 +26.4bp
      그때 존재하지도 않던 20종목  +46.9bp(t=+4.3) 왕복177회 → 비용 후 +23.8bp
      out-of-sample에서 크기가 거의 그대로 남았고 20종목 중 85%가 플러스다.
      GapUpFadeRecoveryStrategy와 함께 이 다섯 중 살아남은 둘이다.

      진입 시각이 전부다: pos 임계값을 0.03~0.2로 바꿔도 after_bar=270이면 전부
      +38~+54bp인데, after_bar=180이면 같은 임계값 전부가 +2~+7bp로 죽는다.
      '레인지 하단'은 오전에는 신호가 아니고 오후 늦게만 신호다. 그래서 임계값보다
      after_bar를 기본값에서 함부로 낮추는 쪽이 훨씬 위험하다.

    lookahead 주의:
      고가·저가는 반드시 cummax/cummin(현재 봉까지의 누적)이어야 한다. groupby에
      transform("max")를 쓰면 장 마감까지의 고가가 오전 봉에 들어가 '오늘 어디까지
      오를지'를 미리 아는 셈이 된다. CLAUDE.md의 expanding() 규약과 같은 함정이다.

    청산은 그날 마지막 봉뿐이다 — 이유는 AfternoonOversoldStrategy와 같다.

    ※ 전제조건: 분봉 데이터.
    """

    def __init__(self, pos_threshold=0.1, after_bar=270, max_entry_bar=375):
        self.pos_threshold = pos_threshold
        self.after_bar = after_bar
        self.max_entry_bar = max_entry_bar  # 375 ≈ 15:15. 마감 직전 진입 차단

    def _range_pos(self, df: pd.DataFrame) -> pd.Series:
        """당일 누적 고저 레인지 안에서 현재 종가의 위치(0=저가, 1=고가)."""
        d = ind.bar_dates(df)
        lo = df["low"].groupby(d).cummin()
        hi = df["high"].groupby(d).cummax()
        width = (hi - lo).replace(0, pd.NA)  # 첫 봉처럼 폭이 0이면 위치를 정의할 수 없다
        return (df["close"] - lo) / width

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 오후 구간 + 당일 레인지 하단
        bar_no = ind.bar_of_day(df)
        return ((bar_no >= self.after_bar)
                & (bar_no <= self.max_entry_bar)
                & (self._range_pos(df) < self.pos_threshold))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 그날 마지막 봉
        return ind.is_last_bar_of_day(df)
