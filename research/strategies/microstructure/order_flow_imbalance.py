# -*- coding: utf-8 -*-
from ..score_base import PercentileScoreStrategy
from .base import signed_volume
import numpy as np
import pandas as pd


class OrderFlowImbalanceStrategy(PercentileScoreStrategy):
    """
    주문흐름 불균형의 반대편에 선다 (Cont-Kukanov-Stoikov 2014의 발상).

        OFI = sum(CLV × volume, period) / sum(volume, period)
        score = -OFI

    OFI는 최근 period봉 동안 매수와 매도 중 어느 쪽이 밀어붙였는지를 -1~+1로 잰다
    (CLV는 봉 안에서 종가가 고가 쪽이면 +1, 저가 쪽이면 -1). 원 논문은 호가창 이벤트로
    이걸 계산해 단기 가격 변화의 상당 부분을 설명한다. 호가 이력이 없으니 봉 모양으로
    근사했다.

    **부호를 뒤집는 것이 이 전략의 전부다.** 방향성 트레이더는 흐름을 따라간다. 유동성
    공급자는 흐름의 반대편에 선다 — 모두가 팔 때 사 주고, 그 불균형이 해소될 때 스프레드
    만큼을 받는다. Citadel Securities가 방향성 순노출을 0에 가깝게 유지한다는 것은
    이 반대편 서기를 양방향으로 한다는 뜻이다. 롱 온리 엔진에서는 절반만 표현할 수
    있어서, 매도 압력이 극단적인 구간을 사는 쪽만 남는다.

    거래량 합으로 나누는 이유: 정규화하지 않으면 거래가 많은 날의 OFI가 무조건 크게
    나와 '불균형'이 아니라 '거래량'을 재게 된다.

    ── 검증 ── RollSpreadStrategy와 같은 이유로 기각
        train  초과 +1.36bp/봉 (t=+0.8)  비용 0.93  순 +0.43
        test   초과 +4.31bp/봉 (t=+2.2)  비용 0.96  순 +3.35
        격자 18조합 중 순알파 양수: train 6% / test 100%

      train에서 18조합 중 1개만 양수다. test 100%는 2015년 이후 평균회귀 레짐이지
      이 신호의 공이 아니다 — 대조군 BollingerBandStrategy도 같은 구간에서 부호가
      뒤집힌다. 봉 모양으로 근사한 OFI는 결국 '최근 봉들이 저가 마감이었나'라서
      일반적인 역추세 지표와 크게 다르지 않았다.

      원 논문의 OFI는 호가창 이벤트(주문 추가·취소·체결)를 세서 만든다. 봉의
      종가 위치로는 그 정보의 극히 일부만 잡힌다. 제대로 하려면 호가 이력이
      필요하고, 이 리포에는 없다(base.py 참고).
    """

    def __init__(self, period=20, **kw):
        self.period = period
        self.lookback = period
        super().__init__(**kw)

    def score(self, df: pd.DataFrame) -> pd.Series:
        sv = signed_volume(df).rolling(self.period).sum()
        vol = df["volume"].rolling(self.period).sum().replace(0, np.nan)
        return -(sv / vol)
