# -*- coding: utf-8 -*-
"""
WorldQuant 101 Formulaic Alphas를 이 리포의 엔진에 얹기 위한 연산자와 베이스 클래스.

출처: Zura Kakushadze, "101 Formulaic Alphas" (2016), arXiv:1601.00991.
      Appendix A의 수식은 WorldQuant LLC의 명시적 허가 하에 공개된 것이고
      저작권은 WorldQuant LLC에 있다. 여기서는 연구·검증 목적으로 옮겨 적었다.


── 101개 중 14개만 옮길 수 있는 이유 ──

WorldQuant의 알파는 '한 종목의 매매 규칙'이 아니라 '2000종목 포트폴리오의 가중치'다.
논문의 alpha 값 자체가 그 종목에 실을 비중이고, 전체 합이 0인 달러 중립 롱숏이다.
그래서 수식에 다음 연산자가 들어가면 종목 하나만 보고는 계산 자체가 불가능하다.

  rank(x)              그날 전 종목 중 이 종목이 몇 등인가 (횡단면)
  indneutralize(x, g)  같은 섹터 종목들의 평균을 뺀 값 (횡단면)
  scale(x, a)          전 종목 |가중치| 합이 a가 되도록 재조정 (횡단면)
  adv{d}, cap          유동성·시총 기준의 상대 비교에 쓰이는 값

101개 중 87개가 이 중 하나 이상을 쓴다. 남는 14개가 순수 시계열 알파이고,
이 패키지는 그중 다섯 개를 구현한다 (#6, #12, #26, #35, #101).

나머지 87개를 하려면 엔진을 종목별 루프에서 '날짜별 × 종목 매트릭스'로 바꾸고
공매도 경로를 넣어야 한다. CLAUDE.md에 적힌 대로 run_backtest에는 공매도가 없다.


── 연속 알파값을 {-1, 0, 1}로 바꾸는 방법 ──

WorldQuant는 알파값을 그대로 비중으로 쓴다. 이 엔진은 이벤트({-1,0,1})만 먹는다.
그래서 FormulaicAlpha가 **횡단면 rank를 시계열 rank로 갈음한다**:

  원본:  오늘 전 종목 중 상위 20%면 롱
  여기:  오늘 알파값이 최근 window봉의 자기 분포에서 상위 20%면 롱

같은 '상대적으로 높은가'를 묻되 비교 대상을 '다른 종목'에서 '자기 과거'로 바꾼 것이다.
알파값의 절대 수준이 종목마다 제각각(가격 단위에 의존)이라 이 정규화 없이는 임계값
하나를 종목 전체에 걸 수 없다. rolling 백분위라 미래 봉을 보지 않는다.

진입 문턱과 청산 문턱을 따로 두어(0.8 / 0.5) 히스테리시스를 만든다. 하나로 두면
문턱 근처에서 신호가 떨었다 붙었다 하며 왕복비용(23bp)만 나간다.


── 연산자 ──

논문 Appendix A.1의 정의를 그대로 옮겼다. 지금 쓰는 다섯 알파에 필요한 것만 있고,
delay·ts_min·ts_argmax·decay_linear·signedpower 같은 나머지는 필요해질 때 추가하라
(전부 rolling 한 줄이다). 횡단면 연산자(rank/indneutralize/scale)는 위 이유로 없다.
"""
from abc import abstractmethod

import numpy as np
import pandas as pd

from ..score_base import PercentileScoreStrategy


def delta(x: pd.Series, d: int) -> pd.Series:
    """오늘 값에서 d봉 전 값을 뺀 것. 논문: delta(x, d)"""
    return x - x.shift(d)


def correlation(x: pd.Series, y: pd.Series, d: int) -> pd.Series:
    """최근 d봉 구간의 x와 y의 시계열 상관계수. 논문: correlation(x, y, d)"""
    return x.rolling(d).corr(y)


def ts_rank(x: pd.Series, d: int) -> pd.Series:
    """
    최근 d봉 안에서 현재 값의 시계열 순위. 논문: ts_rank(x, d)

    0~1로 정규화해 돌려준다. 논문의 알파들이 `(1 - Ts_Rank(...))` 형태로 쓰는 걸 보면
    원본도 [0,1] 스케일을 전제한다 — 그렇지 않으면 그 뺄셈이 의미가 없다.
    """
    return x.rolling(d).rank(pct=True)


def ts_max(x: pd.Series, d: int) -> pd.Series:
    """최근 d봉 구간의 최댓값. 논문: ts_max(x, d) = max(x, d)"""
    return x.rolling(d).max()


class FormulaicAlpha(PercentileScoreStrategy):
    """
    알파 수식 하나를 매매 신호로 바꾸는 껍데기. 서브클래스는 alpha()만 쓴다.

        class Alpha101Strategy(FormulaicAlpha):
            lookback = 0
            def alpha(self, df):
                return (df["close"] - df["open"]) / ((df["high"] - df["low"]) + .001)

    점수를 자기 백분위로 바꿔 신호를 만드는 기계 부분은 PercentileScoreStrategy에
    있다(strategies/score_base.py). microstructure 패키지도 같은 것을 쓴다 —
    '연속 점수를 문턱으로 자른다'는 문제는 논문 알파에만 있는 게 아니다.
    여기 남은 것은 확장점 이름을 alpha()로 바꾸는 것뿐이고, 논문 어휘를 코드에
    그대로 남겨 두려고 그렇게 했다.
    """

    @abstractmethod
    def alpha(self, df: pd.DataFrame) -> pd.Series:
        """논문의 알파 수식. df와 같은 인덱스를 가진 실수 Series를 돌려준다."""

    def score(self, df: pd.DataFrame) -> pd.Series:
        return self.alpha(df)
