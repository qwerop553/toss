# -*- coding: utf-8 -*-
from ..score_base import PercentileScoreStrategy
from .. import indicators as ind
import pandas as pd


class AdverseSelectionStrategy(PercentileScoreStrategy):
    """
    정보 없는 하락에만 유동성을 공급한다 (역선택 회피).

        score = (-수익률) × (1 - ts_rank(거래량, period))

    마켓메이커의 유일한 실존적 위협은 역선택이다. 반대편이 나보다 많이 알면, 스프레드
    몇 틱을 먹는 대신 가격이 간 만큼을 잃는다. Citadel Securities가 소매 주문흐름에
    돈을 지불하는 이유가 정확히 이것이다 — 소매 주문은 가격에 이미 반영되지 않은 정보를
    거의 담고 있지 않아서, 그 반대편에 서는 것이 안전하다.

    호가창도 주문 출처도 없이 '정보가 실린 주문'을 어떻게 구분하나. 표준 대용치는
    **거래량**이다. 정보를 가진 쪽은 크게 거래한다. 그래서

      가격 하락 + 거래량 많음  →  정보일 가능성. 사면 안 된다.
      가격 하락 + 거래량 적음  →  잡음일 가능성. 사 주고 되돌림을 받는다.

    두 항의 곱이라 둘 다 만족해야 점수가 커진다. 하락이 커도 거래량이 많으면 (1-rank)가
    0에 가까워 죽고, 거래량이 적어도 안 빠졌으면 첫 항이 0이다.

    ── WorldQuant Alpha#12와 정면으로 반대되는 예측 ──
      Alpha#12는 `sign(Δvolume) × (-Δclose)`라 **거래량이 늘어난** 하락을 산다.
      이 전략은 **거래량이 줄어든** 하락을 산다. 같은 데이터에 대해 반대 방향을
      주장하는 것이다. 앞선 검증에서 Alpha#12의 초과수익은 out-of-sample에서도
      +10.2bp/봉(t=3.6)으로 살아남았다 — 즉 이 표본에서는 역선택 가설 쪽이 불리하다는
      사전 증거가 이미 있다. 그래도 구현한 이유는 그 대립이 이 패키지의 전제(마켓메이커
      논리)를 직접 시험하기 때문이다.

    ── 검증 ── 대립은 Alpha#12의 승리로 끝났다
        train  초과 +0.94bp/봉 (t=+0.6)  비용 3.10  순 -2.16
        test   초과 +4.11bp/봉 (t=+2.4)  비용 3.29  순 +0.83
        격자 18조합 중 순알파 양수: train 0% / test 61%

      **train에서 18조합 전부 음수다.** 중앙값이 -16.21bp/봉으로 이 패키지에서 가장
      나쁘다. 즉 '거래량이 적은 하락을 사라'는 역선택 가설은 이 표본에서 지지되지
      않고, 반대 방향인 Alpha#12(거래량이 늘어난 하락을 산다)가 out-of-sample에서도
      +10.2bp/봉(t=3.6)으로 살아남은 것과 일관된다.

      해석: 한국 대형주 일봉에서 거래량이 실린 하락은 정보 거래가 아니라 과잉반응에
      가까웠다. 마켓메이커의 역선택 논리가 틀렸다는 뜻은 아니다 — 역선택은 초 단위
      호가 갱신의 문제이고, 일봉의 거래량은 그걸 재는 도구가 아니다. **대용치가
      원래 재려던 것을 못 재는 사례**로 남겨 둔다.
    """

    def __init__(self, period=20, **kw):
        self.period = period
        self.lookback = period
        super().__init__(**kw)

    def score(self, df: pd.DataFrame) -> pd.Series:
        drop = -df["close"].pct_change()
        quiet = 1 - df["volume"].rolling(self.period).rank(pct=True)
        return drop * quiet
