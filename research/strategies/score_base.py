# -*- coding: utf-8 -*-
"""
연속적인 점수를 내는 전략을 {-1, 0, 1} 신호로 바꾸는 공통 뼈대.

왜 따로 있나:
  지표 하나를 임계값과 비교하는 전략(EMA 크로스 등)과 달리, 점수형 전략은 '이 값이
  크면 좋다'만 알고 절대 수준이 뭘 뜻하는지는 모른다. WorldQuant 알파값도, Amihud
  비유동성도 가격 단위·거래량 단위에 의존해서 종목마다 스케일이 제각각이다.
  삼성전자의 0.7이 SK하이닉스의 0.7과 다른 것을 뜻하면 임계값 하나를 전 종목에
  걸 수 없다.

  그래서 점수를 **자기 과거 분포의 백분위**로 바꾼 뒤 문턱을 건다. 이러면 임계값이
  '상위 몇 %'라는 종목 무관한 뜻을 갖는다. rolling이라 미래 봉을 보지 않는다.

진입 문턱과 청산 문턱을 따로 두는 이유(히스테리시스):
  하나로 두면 점수가 문턱 근처에서 떨 때마다 진입·청산이 반복되어 왕복비용(23bp)만
  나간다. 진입은 상위 20%, 청산은 하위 50% 식으로 벌려 두면 한 번 들어간 포지션이
  어지간해서는 유지된다.

이 클래스 자체는 @abstractmethod가 있어 전략으로 자동 등록되지 않는다
(strategies/__init__.py의 isabstract 필터).
"""
from abc import abstractmethod

import pandas as pd

from .base import Strategy, to_signals


class PercentileScoreStrategy(Strategy):
    """
    서브클래스는 score()만 구현한다.

        class MyStrategy(PercentileScoreStrategy):
            lookback = 20
            def score(self, df):
                return df["volume"].rolling(20).mean()

    lookback은 점수식이 참조하는 과거 봉 수다. window와 합쳐 warmup이 되고,
    그만큼은 베이스가 신호를 0으로 눌러 준다(rolling 초기 구간은 신뢰할 수 없다).

    window/entry_q/exit_q는 클래스 속성이라 서브클래스가 자기 기본값을 덮어쓸 수 있다
    (`entry_q = 0.95` 한 줄). 점수마다 엣지가 몰려 있는 분위가 다르기 때문이다.
    """

    lookback: int = 0
    window: int = 250       # 자기 과거와 비교할 구간 길이
    entry_q: float = 0.8    # 이 백분위 이상이면 진입
    exit_q: float = 0.5     # 이 백분위 이하면 청산

    def __init__(self, window=None, entry_q=None, exit_q=None):
        # None이면 클래스 기본값을 그대로 둔다. 그리드서치는 값을 넘겨 덮어쓴다.
        if window is not None:
            self.window = window
        if entry_q is not None:
            self.entry_q = entry_q
        if exit_q is not None:
            self.exit_q = exit_q
        self.warmup = self.lookback + self.window

    @abstractmethod
    def score(self, df: pd.DataFrame) -> pd.Series:
        """클수록 매수에 유리한 점수. df와 같은 인덱스를 가진 실수 Series."""

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        # entries/exits를 따로 노출하지 않고 여기서 한 번에 만든다. 그렇게 하지 않으면
        # 무거운 score()가 진입용·청산용으로 두 번 계산된다.
        #
        # min_periods가 반드시 필요하다. pandas의 rolling은 min_periods 기본값이
        # window라서, 창 안에 NaN이 하나라도 있으면 결과가 NaN이다. 점수가 드문드문
        # 정의되는 전략(RollSpreadStrategy는 정의 비율이 44%다)은 이러면 모든 창이
        # NaN에 걸려 신호가 **하나도** 안 난다 — 터지지 않고 조용히 0회 거래로 끝나서
        # 알아채기 어렵다. 창의 1/4만 유효해도 백분위를 내되, 20개 미만이면 분포를
        # 말할 수 없으니 그때는 포기한다.
        min_periods = max(20, self.window // 4)
        pct = self.score(df).rolling(self.window, min_periods=min_periods).rank(pct=True)
        return to_signals(pct >= self.entry_q, pct <= self.exit_q, self.warmup)
