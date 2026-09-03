# -*- coding: utf-8 -*-
from ..score_base import PercentileScoreStrategy
from .base import amihud
import pandas as pd


class AmihudIlliquidityStrategy(PercentileScoreStrategy):
    """
    비유동성 프리미엄 (Amihud 2002).

        ILLIQ = mean(|수익률| / 거래대금, period)

    거래대금 1원이 가격을 얼마나 미는가. 값이 크면 얕은 시장이고, 얕은 시장에
    자본을 대는 쪽은 그 대가로 더 높은 기대수익을 요구한다. Citadel Securities가
    미국 거래량의 25%를 체결하며 버는 돈의 이론적 뿌리가 이것이다 — 남들이 급하게
    사고팔아야 할 때 반대편에 서 주는 대가.

    다만 원 논문의 효과는 **횡단면**이다. 비유동 종목이 유동 종목보다 장기적으로 더
    번다는 것이지, 한 종목이 평소보다 얕아진 순간을 사라는 말이 아니다. 이 엔진은
    종목을 가로질러 비교할 수 없어서 시계열로 옮겼고, 그 치환이 성립한다는 보장은
    없다. WorldQuant 알파에서 횡단면 rank를 시계열 rank로 갈음한 것과 같은 종류의
    타협이고, 거기서는 다섯 중 하나만 살아남았다.

    ── 검증 ── train에서만 통한다
        train  초과 +3.76bp/봉 (t=+2.3)  비용 0.39  순 +3.37   보유 59봉
        test   초과 +1.45bp/봉 (t=+0.8)  비용 0.42  순 +1.03
        격자 18조합 중 순알파 양수: train 83% / test 33%

      **이 패키지에서 유일하게 train이 test보다 좋다.** 나머지 셋은 전부 반대인데,
      그건 2015년 이후 평균회귀 레짐을 타고 있다는 뜻이다(아래 요약표). Amihud만
      그 레짐에 올라타지 않았고, 그래서 정직하게 실패했다 — test에서 격자의 1/3만
      양수다.

      회전율은 다섯 중 가장 낮다(보유 59봉, 비용 0.4bp/봉). 비용이 문제가 아니라
      신호가 없다. 원 논문의 효과가 횡단면인 것을 시계열로 옮긴 대가라고 본다.

    ※ 대상이 코스피50 대형주라 애초에 비유동 종목이 없다. 이 표본에서 ILLIQ가 높다는
      것은 '유동성이 낮은 종목'이 아니라 '평소보다 거래가 마른 구간'을 뜻한다.
      원 논문이 비교하는 '비유동 종목 vs 유동 종목'과는 다른 것을 재고 있다.
    """

    def __init__(self, period=20, **kw):
        self.period = period
        self.lookback = period
        super().__init__(**kw)

    def score(self, df: pd.DataFrame) -> pd.Series:
        return amihud(df, self.period)
