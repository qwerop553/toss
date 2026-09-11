from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class GapUpFadeRecoveryStrategy(Strategy):
    """
    갭 상승 후 시가 하회 → 오후 종가 회복.

    아침에 갭을 띄우고 열었는데 장중에 시가마저 내준 날을 산다. 언뜻 '실패한 갭'
    이라 피해야 할 것 같지만, 이 데이터에서는 정반대다. 갭을 띄울 만한 재료가
    있었는데 차익실현으로 눌린 것이라면 오후에 되사는 손이 남아 있다는 해석이
    가능하다.

    발굴 근거 (1분봉, 8종목 × 52거래일):
      전일 종가 대비 +30bp 이상 갭 상승한 날, 13시 이후 종가가 시가 아래인 지점에서
      종가까지 +38.4bp(t=+30.0). 이 스캔에서 관측한 조건 중 t가 가장 컸다.
      비교군: 같은 시간대 전체 +4.4bp, 갭 하락일의 오후 전체 +4.5bp — 방향을
      만들어 내는 건 '갭 상승'과 '시가 하회'의 조합이지 오후 시간대 자체가 아니다.

    검증 (코스피50 전 종목, 거래당 비용 전 총수익 / 왕복비용 23bp):
      파라미터를 고를 때 쓴 30종목  +51.6bp(t=+4.7) 왕복244회 → 비용 후 +28.5bp
      그때 존재하지도 않던 20종목  +65.9bp(t=+5.1) 왕복151회 → 비용 후 +42.8bp
      후자는 순수 out-of-sample이고, 그 20종목 중 90%가 종목 단위로도 플러스다.
      다섯 전략 중 유일하게 OOS가 IS보다 좋게 나왔다.

      갭 임계값에 둔감하다: 0.2%/0.3%/0.5% 어느 쪽이든 after_bar=270이면
      +43.7/+46.6/+46.1bp로 거의 같다. 반대로 after_bar는 180→270으로 갈수록
      +22 → +28 → +47bp로 크게 벌어진다. 조여야 할 손잡이는 갭이 아니라 시각이다.

    다른 오후 전략들과의 관계:
      AfternoonOversold / AfternoonRangeBottom은 당일 가격 위치만 보고, 이쪽은
      전일 대비 갭이라는 일 단위 필터를 하나 더 얹는다. 그래서 대상 종목-일이
      훨씬 적고(전체의 약 1/5), 겹치는 날에도 진입 사유가 다르다.

    청산은 그날 마지막 봉뿐이다. 오버나잇 없음.

    ※ 전제조건: 분봉 데이터.
    """

    def __init__(self, gap_pct=0.003, after_bar=270, max_entry_bar=375):
        self.gap_pct = gap_pct
        self.after_bar = after_bar
        self.max_entry_bar = max_entry_bar  # 375 ≈ 15:15. 마감 직전 진입 차단

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 갭 상승일 + 오후 + 시가 아래로 밀린 상태
        _, _, prev_close = ind.prev_day_ohlc(df)
        open_ = ind.day_open(df)
        bar_no = ind.bar_of_day(df)
        return ((open_ / prev_close - 1 >= self.gap_pct)
                & (bar_no >= self.after_bar)
                & (bar_no <= self.max_entry_bar)
                & (df["close"] < open_))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 그날 마지막 봉
        return ind.is_last_bar_of_day(df)
