# -*- coding: utf-8 -*-
"""
시장미시구조 추정량. 호가창 없이 OHLCV만으로 스프레드·유동성·주문흐름을 근사한다.


── 이 패키지가 Citadel의 전략이 아닌 이유 ──

WorldQuant는 알파 101개를 논문으로 공개했다. Citadel은 수식을 하나도 공개한 적이
없다. 공개된 것은 **사업 구조**뿐이다.

  Citadel Securities (마켓메이커)
    미국 주식 거래량의 약 25%를 체결한다. 수익원은 매수·매도 호가차 포착, 주문흐름
    대가(PFOF), 거래소 리베이트이고, 방향성 순노출은 0에 가깝게 유지한다. 핵심
    난제는 역선택(adverse selection) — 정보를 가진 상대의 주문을 받으면 손해다.
    그래서 소매 주문흐름(정보가 거의 없다)에는 돈을 지불하고, 공정가 갱신 속도에
    수십억 달러를 쓴다.

  Citadel LLC (헤지펀드)
    Equities / Fixed Income & Macro / Commodities / Credit / Global Quantitative
    Strategies의 다섯 사업으로 나뉜 팟(pod) 구조다. 대부분의 주식 팟이 순노출을
    -20% ~ +20%로 묶는 **시장중립**이고 팩터 노출에 명시적 상한이 있다.

두 사업 모두 이 엔진과 구조가 맞지 않는다.

  - 마켓메이킹은 방향성 베팅이 아니다. 호가를 양쪽에 걸고 스프레드를 먹는 일이라
    호가창·큐 포지션·마이크로초 단위 지연이 필요하다. 이 리포에는 호가 이력이 없다
    (paper/feed.py가 `orderbook:kr`을 실시간으로 받지만 브라우저로 흘려보내고 버린다.
    market_data.db에는 candles 테이블 하나뿐이다).
  - 시장중립은 공매도가 필요하다. run_backtest에 공매도 경로가 없다(CLAUDE.md).

그래서 여기 있는 것은 **'유동성 공급자가 대가를 받는 그 양(量)'을 학술 문헌의
추정량으로 재고, 이 엔진이 표현할 수 있는 유일한 형태인 단일 종목 롱으로 옮긴
것**이다. 출처는 Citadel이 아니라 논문이다.

  Roll (1984)              수익률 자기공분산으로 실효 스프레드 역산
  Amihud (2002)            |수익률| / 거래대금 = 비유동성, 기대수익 프리미엄의 원천
  Cont-Kukanov-Stoikov (2014)  주문흐름 불균형(OFI)이 단기 가격을 민다

'Citadel이 이렇게 한다'가 아니라 'Citadel이 돈을 버는 그 현상을 공개된 방법으로
재면 이렇게 된다'로 읽어라.

    ── 이 패키지 전체의 검증 요약 (코스피 43종목 일봉, train ~2014 / test 2015~) ──
      기준은 '보유 중 봉당 수익 - 미보유 봉당 수익 - 비용'(순알파, bp/봉)이다.
      숫자 하나가 아니라 파라미터 격자 18조합 중 몇 %가 양수인지를 함께 본다.

        전략                    train양수  train중앙   test양수  test중앙
        Amihud                     83%     +0.96        33%     -0.72
        RollSpread                 22%     -1.29       100%     +6.91
        OrderFlowImbalance          6%     -1.03       100%     +1.40
        AdverseSelection            0%    -16.21        61%     +0.28
        --- 대조군(기존 전략) ---
        RsiReversion              100%     +6.11       100%     +6.91
        BollingerBand               0%     -0.37       100%     +2.26

      **test 구간이 좋은 것은 전략이 아니라 시기다.** 평균회귀 성격을 띤 것은 새로
      만든 것이든 원래 있던 것이든 전부 2015년 이후에 좋아진다. 아무것도 안 한
      BollingerBand조차 -0.37에서 +2.26으로 뒤집힌다. 그리고 이 패키지에서 test가
      가장 좋은 RollSpread(+6.91)는 원래 리포에 있던 RsiReversion(+6.91)과 같은
      값이다 — 새로 얻은 것이 없다는 뜻이다.


각 전략의 상세는 해당 파일에 적었다.
"""
import numpy as np
import pandas as pd


def close_location_value(df: pd.DataFrame) -> pd.Series:
    """
    한 봉 안에서 종가가 고가 쪽인지 저가 쪽인지. -1(저가 마감) ~ +1(고가 마감).

        ((close - low) - (high - close)) / (high - low)

    호가창이 없을 때 매수/매도 주도권을 근사하는 표준 대용치다. 체결마다 매수 주도인지
    매도 주도인지 알 수 있으면 그걸 세면 되지만(틱 룰), 봉 데이터에는 그 정보가 없다.
    대신 '고가 근처에서 닫았으면 매수가 밀어붙인 봉'이라고 본다.

    고가 == 저가인 봉(한 가격에서만 거래된 봉)은 주도권을 정의할 수 없어 NaN이다.
    """
    span = (df["high"] - df["low"]).replace(0, np.nan)
    return ((df["close"] - df["low"]) - (df["high"] - df["close"])) / span


def signed_volume(df: pd.DataFrame) -> pd.Series:
    """부호 있는 거래량 = CLV × 거래량. 양수면 매수 우위, 음수면 매도 우위."""
    return close_location_value(df) * df["volume"]


def amihud(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Amihud(2002) 비유동성. 최근 period봉의 |수익률| / 거래대금 평균.

    '거래대금 1원이 가격을 얼마나 움직이는가'다. 값이 클수록 얕은 시장이고, 얕은
    시장에서 유동성을 공급하는 대가로 더 높은 기대수익을 요구받는다는 것이 원 논문의
    주장이다. 원문은 이걸 **종목 간 횡단면**으로 쓴다(비유동 종목이 유동 종목보다
    장기적으로 더 번다). 여기서는 종목 하나의 시계열로 쓴다 — 다른 종목과 비교할 수
    없는 엔진이라 어쩔 수 없고, 같은 효과라는 보장은 없다.

    거래대금이 0인 봉(거래 없음)은 0으로 나누게 되므로 NaN으로 뺀다.
    """
    dollar_volume = (df["close"] * df["volume"]).replace(0, np.nan)
    return (df["close"].pct_change().abs() / dollar_volume).rolling(period).mean()


def roll_spread(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Roll(1984) 내재 실효 스프레드. 2 * sqrt(-cov(Δp_t, Δp_{t-1})).

    발상: 호가 스프레드가 s면 체결가는 매수·매도가 번갈아 오며 중간가 주변을 ±s/2로
    튄다. 그 튐이 가격 변화에 음의 1차 자기상관을 만들고, 그 공분산의 크기로 스프레드를
    역산할 수 있다. 호가 데이터 없이 체결가만으로 거래비용을 재는 고전적 방법이다.

    ※ 공분산이 양수면 정의되지 않는다(제곱근 안이 음수). 추세가 있는 구간에서는
      자기상관이 양수라 실제로 절반 가까이가 이렇게 된다 — 원 논문도 인정하는 한계다.
      여기서는 NaN으로 두고 신호를 내지 않는다. 0으로 채우면 '스프레드가 0'이라는
      거짓 정보가 되고, 백분위 계산에서 최하위로 잡혀 신호를 왜곡한다.
    """
    dp = df["close"].diff()
    cov = dp.rolling(period).cov(dp.shift(1))
    return 2 * np.sqrt((-cov).where(cov < 0))
