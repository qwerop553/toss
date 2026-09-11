# -*- coding: utf-8 -*-
from ..score_base import PercentileScoreStrategy
from .base import roll_spread
import pandas as pd


class RollSpreadStrategy(PercentileScoreStrategy):
    """
    내재 스프레드가 벌어진 구간에서 유동성을 공급한다 (Roll 1984).

        s = 2 * sqrt(-cov(Δp_t, Δp_{t-1}))

    스프레드는 마켓메이커가 받는 보수 그 자체다. 호가창이 없어도 체결가의 음의
    자기상관에서 역산할 수 있다는 것이 Roll의 발견이고, 이 전략은 그 값이 자기
    과거 대비 높은 구간을 산다 — '지금 유동성 공급의 대가가 비싸다'는 뜻이기 때문이다.

    AmihudIlliquidityStrategy와 재는 대상이 겹치지만 재료가 완전히 다르다. Amihud는
    거래량을 쓰고(가격이 거래대금당 얼마나 움직이나), Roll은 거래량을 아예 안 본다
    (가격이 얼마나 튕기나). 둘이 갈리는 구간이 있어야 둘 다 둘 가치가 있다.

    ※ 이 추정량은 자주 정의되지 않는다. 공분산이 양수면 제곱근 안이 음수가 되는데,
      추세 구간에서는 자기상관이 양수라 실제로 자주 그렇게 된다. 원 논문도 인정하는
      한계다. base.py의 roll_spread가 그 구간을 NaN으로 두고, to_signals가 NaN을
      False로 눌러 신호를 내지 않는다. 즉 이 전략은 **'평균회귀적인 잡음이 지배하는
      구간에서만 작동하고 추세 구간에서는 아예 잠자는'** 성질을 갖는다. 그게 결함이
      아니라 마켓메이킹의 성질과 맞는다 — 추세가 붙은 시장은 마켓메이커가 지는
      시장이다(역선택).

    ── 검증 ── 숫자는 좋은데 전략의 공이 아니다
        train  초과 +2.41bp/봉 (t=+1.2)  비용 1.02  순 +1.39
        test   초과 +9.05bp/봉 (t=+3.9)  비용 1.02  순 +8.04
        격자 18조합 중 순알파 양수: train 22% / test 100%

      test 숫자만 보면 이 리포에서 만든 것 중 최고다. 두 가지가 그 해석을 막는다.

      1) train에서 격자의 22%만 양수다. 파라미터를 train에서 골랐다면 이 전략을
         고르지 않았을 것이다. test가 좋은 것을 사후에 발견한 것뿐이다.
      2) 같은 기간 기존 RsiReversionStrategy의 test 순알파가 +6.91bp로 사실상
         같은데, 그쪽은 train에서도 +6.11로 양수다. 즉 2015년 이후 한국 대형주가
         평균회귀적으로 변한 것이고, 내재 스프레드는 그 평균회귀를 재는 여러 방법
         중 하나일 뿐 새로 얻은 정보가 아니다.

      Roll 추정량 자체는 제대로 작동한다(정의 비율 44%, 문헌과 일치). 문제는
      추정량이 아니라 '이 값이 높을 때 사면 돈이 되는가'라는 가설이다.
    """

    def __init__(self, period=20, **kw):
        self.period = period
        self.lookback = period + 1   # cov가 shift(1)을 물어 한 봉 더 본다
        super().__init__(**kw)

    def score(self, df: pd.DataFrame) -> pd.Series:
        return roll_spread(df, self.period)
