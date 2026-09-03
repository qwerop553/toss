from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class GapDownOpenFadeStrategy(Strategy):
    """
    갭 하락일의 개장 약세 → 30분 반등.

    같은 폴더의 GapFillStrategy와 재료가 같고(갭 하락) 결론이 다르다. 그쪽은
    '전일 종가를 회복할 때까지' 들고 가는 종일 전략이라 갭이 안 메워지는 날 하루
    종일 물린다. 이쪽은 개장 직후 30분 안에서만 놀고, 청산도 전일 종가가 아니라
    시각으로 끊는다.

    발굴 근거 (1분봉, 8종목 × 52거래일):
      전일 종가 대비 -30bp 이상 갭 하락으로 시작한 날, 개장 후 5~35번째 봉 구간에서
      시가마저 밑돌고 있는 지점의 30분 forward return이 +29.9bp(t=+10.2), 60분은
      +32.0bp다. 이 데이터셋에서 30분 forward가 비용(23bp)을 넘는 조건은 사실상
      이것뿐이었다. 갭 임계값을 -100bp로 올리면 +25.6bp로 오히려 약해진다 —
      진짜 악재로 벌어진 큰 갭은 되돌리지 않는다는 통상적인 해석과 맞는다.

    검증 (코스피50 전 종목, 거래당 비용 전 총수익 / 왕복비용 23bp) — 살아남지 못했다:
      파라미터를 고를 때 쓴 30종목  +37.7bp(t=+3.2) 왕복282회 → 비용 후 +14.6bp
      그때 존재하지도 않던 20종목  +25.6bp(t=+1.8) 왕복161회 → 비용 후  +2.5bp
      out-of-sample에서 t가 1.8로 떨어지고, 종목 단위로 플러스인 비율이 45%다.
      절반 이하라는 건 전체 평균을 몇 종목이 끌고 있다는 뜻이라 종목을 가로질러
      재현되는 성질이 아니다. 이 전략은 지금 상태로 쓰면 안 된다.

      원인으로 의심하는 것: exit_bar가 애초에 뾰족했다. 65봉에서 +29bp인데
      50봉 +18bp, 90봉 +18bp로 양쪽 다 떨어진다. '진입 상한 35봉 + 관측 지평
      30봉'이라는 사전 근거에서 나온 값이긴 하지만, 이렇게 한 점에 몰린 값은
      표본이 늘면 사라진다 — 실제로 사라졌다.

    왜 '시가 아래'를 요구하나:
      갭 하락으로 열렸어도 개장 직후 바로 위로 뜬 날은 이미 반등이 시작된 자리라
      진입 가격이 나쁘다. 되돌림의 대부분을 남에게 준 뒤 붙게 된다.

    청산이 시각(exit_bar)인 이유:
      알파가 '개장 직후 30분'이라는 구간 자체에 붙어 있다. 목표가를 걸면 못 닿은
      날 종일 들고 있게 되고, 그 구간(10:30~13:00)은 이 데이터에서 60분 forward가
      -9.5bp로 오히려 마이너스다. 시각으로 끊는 편이 알파에 정확히 대응한다.
      exit_bar 65는 진입 상한(35봉) + 관측 지평(30봉)에서 나온 값이다.

    ※ 전제조건: 분봉 데이터.
    """

    def __init__(self, gap_pct=0.002, entry_from=5, entry_to=35, exit_bar=65):
        self.gap_pct = gap_pct        # 이만큼 이상 갭 하락한 날만 대상
        self.entry_from = entry_from  # 개장 직후 몇 봉은 건너뛴다 (시가 근처 변동성 회피)
        self.entry_to = entry_to
        self.exit_bar = exit_bar

    def _gap(self, df: pd.DataFrame) -> pd.Series:
        """전일 종가 대비 당일 시가의 갭 비율을 봉 단위로 펼친다."""
        _, _, prev_close = ind.prev_day_ohlc(df)
        return ind.day_open(df) / prev_close - 1

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 갭 하락일 + 개장 직후 구간 + 아직 시가 아래
        bar_no = ind.bar_of_day(df)
        return ((self._gap(df) <= -self.gap_pct)
                & bar_no.between(self.entry_from, self.entry_to)
                & (df["close"] < ind.day_open(df)))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 정해진 순번을 지났거나 그날 마지막 봉(반나절 장 대비)
        return (ind.bar_of_day(df) >= self.exit_bar) | ind.is_last_bar_of_day(df)
