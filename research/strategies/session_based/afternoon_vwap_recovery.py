from ..base import Strategy
from .. import indicators as ind
import pandas as pd


class AfternoonVwapRecoveryStrategy(Strategy):
    """
    오후 VWAP 위 + 전일 종가 미회복 → 종가 랠리.

    두 기준선이 엇갈린 자리를 노린다. VWAP 위는 '오늘 산 사람들의 평균보다 지금이
    비싸다'는 뜻이라 당일 수급은 이미 매수 우위다. 그런데 전일 종가 아래라는 건
    어제 마감가는 아직 못 넘었다는 뜻이다 — 오늘 올라오는 중인데 갈 길이 남은
    자리다. 둘 중 하나만 보면 신호가 아니다.

    발굴 근거 (1분봉, 8종목 × 52거래일):
      13시 이후 이 조건에서 종가까지 +25.3bp(t=+18.7). 같은 시간대 전체는 +4.4bp,
      VWAP 조건만 걸면 +7.0bp, 전일 종가 조건만 걸면 +28.6bp지만 t가 낮고 표본이
      두 배 넓다. 두 조건을 함께 걸었을 때 t가 가장 높다.

    검증 (코스피50 전 종목, 거래당 비용 전 총수익 / 왕복비용 23bp) — 살아남지 못했다:
      파라미터를 고를 때 쓴 30종목  +32.9bp(t=+4.0) 왕복271회 → 비용 후  +9.8bp
      그때 존재하지도 않던 20종목  +12.1bp(t=+1.5) 왕복176회 → 비용 후 -11.0bp
      out-of-sample에서 총수익이 절반 아래로 주저앉아 왕복비용을 못 넘고, 종목
      단위로 플러스인 비율은 35%다. 다섯 중 IS→OOS 낙폭이 가장 크다. 이벤트
      스터디의 t=+18.7은 '조건을 만족한 모든 봉'을 센 값이었고, 실제로 살 수 있는
      '그날의 첫 봉'만 놓고 보면 남는 게 별로 없었다는 뜻이다.

      after_bar를 240/270으로 늦추면 IS에서 +28.7/+20.7bp로 줄어든다. 다른 오후
      전략들과 방향이 반대인데, 이쪽은 '눌린 자리'가 아니라 '회복 중인 자리'를
      사는 것이라 일찍 붙을수록 회복 구간을 많이 먹기 때문으로 읽었다.

    VWAP 이탈 손절이 기본값에서 꺼져 있는 이유 (stop_below_vwap=False):
      설계할 때는 켜 두는 게 맞다고 봤다. 진입 전제가 '당일 수급 매수 우위'이니
      VWAP 아래로 되밀리면 근거가 사라진다는 논리였다. 실측은 정반대였다.
      손절을 켜면 총수익이 +33.3bp에서 -5.4bp(t=-2.6)로 뒤집히고, 왕복이 174회에서
      878회로 다섯 배가 된다. 평균 보유가 20봉까지 짧아지고 승률은 10%대다.
      VWAP 위아래를 오가는 톱질에 그대로 썰린 것이다.

      즉 이 알파는 '진입 시점의 조건'이 아니라 '진입부터 종가까지'라는 구간에
      붙어 있다. 구간을 중간에 끊는 순간 알파가 아니라 비용만 남는다. 옵션은
      남겨 두었지만 켜려면 이 숫자를 다시 확인하고 켜라.

    ※ 전제조건: 분봉 데이터.
    """

    def __init__(self, after_bar=180, max_entry_bar=375, stop_below_vwap=False):
        self.after_bar = after_bar
        self.max_entry_bar = max_entry_bar      # 375 ≈ 15:15. 마감 직전 진입 차단
        self.stop_below_vwap = stop_below_vwap  # True면 VWAP 이탈에 손절 (기본은 끔)

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 오후 + VWAP 위 + 전일 종가 아래
        _, _, prev_close = ind.prev_day_ohlc(df)
        bar_no = ind.bar_of_day(df)
        return ((bar_no >= self.after_bar)
                & (bar_no <= self.max_entry_bar)
                & (df["close"] > ind.session_vwap(df))
                & (df["close"] < prev_close))

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] VWAP 이탈(전제 붕괴) 또는 그날 마지막 봉
        last_bar = ind.is_last_bar_of_day(df)
        if not self.stop_below_vwap:
            return last_bar
        return last_bar | (df["close"] < ind.session_vwap(df))
