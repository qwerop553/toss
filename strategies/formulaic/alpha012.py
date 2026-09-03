# -*- coding: utf-8 -*-
from .base import FormulaicAlpha, delta
import numpy as np
import pandas as pd


class Alpha012Strategy(FormulaicAlpha):
    """
    WorldQuant Alpha#12:

        (sign(delta(volume, 1)) * (-1 * delta(close, 1)))

    한 봉짜리 역추세인데, **거래량이 늘었는지 줄었는지로 부호를 뒤집는다**.

      거래량 증가 + 가격 하락  →  +  (되돌림을 산다)
      거래량 증가 + 가격 상승  →  -  (과열로 본다)
      거래량 감소 + 가격 하락  →  -  (관심이 식은 하락은 안 산다)
      거래량 감소 + 가격 상승  →  +

    즉 거래량이 늘어난 봉에서는 역추세, 줄어든 봉에서는 순추세다. 단순한 1봉 반전
    (`-delta(close,1)`)은 이 데이터에서 그냥 노이즈인데, 거래량 부호를 곱하면
    '사람들이 실제로 붙은 움직임'만 남는다는 것이 이 수식의 주장이다.

    리포의 VolumeSpikeBreakoutStrategy와 재료는 같고 방향이 반대다. 그쪽은 거래량이
    터진 상승을 따라가고, 이쪽은 거래량이 터진 하락을 산다.

    부호가 셋(-1/0/+1) 중 하나를 곱한 값이라 알파값이 사실상 -delta·0·+delta의
    세 덩어리로 갈린다. 백분위를 매기면 '거래량 증가 + 큰 하락'이 상위에 몰린다.

    ── 검증 (코스피 대형주 43종목 일봉, 1975~2026) ── 신호는 진짜인데 비용에 죽는다
        train(~2014)  초과 +14.07bp/봉 (t=+5.9)  비용 10.72  순 +3.35
        test (2015~)  초과 +10.20bp/봉 (t=+3.6)  비용 10.54  순 -0.34

      **예측력 자체는 out-of-sample에서 살아남았다** (t=3.6). 그런데 평균 보유가
      2.1봉이라 왕복 23bp가 봉당 10.5bp로 환산되고, 초과수익 10.2bp를 거의 정확히
      상쇄한다. 논문의 알파가 2000종목 포트폴리오 안에서 서로 반대 주문을 상계하며
      (paper 본문: "automatic internal crossing of trades") 비용을 아끼는 구조라는
      점을 감안하면, 단일 종목 롱 온리로 옮긴 순간 이 결과는 예정된 것이었다.

      엣지가 상위 5%에만 있다: entry_q를 0.8로 낮추면 초과수익이 +3.7bp로 주저앉고
      0.95에서만 두 자릿수가 나온다. 그래도 비용을 못 넘어 기본값은 중립(0.8)으로 뒀다 —
      0.95로 바꿔도 train에서만 양수라 기본값으로 삼을 근거가 없다.
    """

    lookback = 1

    def alpha(self, df: pd.DataFrame) -> pd.Series:
        return np.sign(delta(df["volume"], 1)) * (-1 * delta(df["close"], 1))
