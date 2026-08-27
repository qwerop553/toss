# ABC : Abstract Base Class, 상속해서 사용하지 않으면 오류를 낸다.
# abstractmethod를 붙이면 이 메서드를 구현하지 않은 자식 클래스는 아예 인스턴스를 만들지 못한다.
from abc import ABC
import numpy as np
import pandas as pd


def to_signals(entries: pd.Series, exits: pd.Series, warmup: int = 0) -> pd.Series:
    """
    진입/청산 조건(불리언 Series)을 엔진이 먹는 신호 {-1, 0, 1}로 바꾼다.

    왜 이 함수가 따로 있나:
      엔진(run_backtest)은 신호를 '상태'가 아니라 '이벤트'로 읽는다. 1이 나올 때마다
      조건 없이 1주를 더 산다. 그래서 예전에는 전략마다 holding 불리언을 들고 도는
      for 루프를 복붙해야 했다. 그 루프를 여기 한 번만 구현하고, 전략은 조건식만
      쓰게 하는 것이 목적이다.

    규칙:
      - warmup 미만 구간은 무조건 0 (지표가 아직 신뢰할 수 없는 구간)
      - 미보유 + entries -> 1 (보유로 전환)
      - 보유   + exits   -> -1 (미보유로 전환)
      - 최대 1주. 중복 진입이 원천적으로 불가능하다.

    동시 신호(설계 결정 1):
      한 봉에서 진입·청산이 모두 참이면, 미보유 상태에서는 진입이 이기고 보유
      상태에서는 청산이 이긴다. 아래 if/elif 순서에서 자연히 따라온다. 평균회귀
      전략은 두 조건이 동시에 참일 수 없고, 가능한 전략이라도 다음 봉에서 반대
      신호가 다시 뜨므로 손실될 정보가 없다.
    """
    if not entries.index.equals(exits.index):
        raise ValueError("entries와 exits의 인덱스가 다릅니다. 같은 df에서 파생되어야 합니다.")

    # NaN을 False로 눌러 둔다. 지표 워밍업 구간에서 NaN이 나오는 건 정상이고,
    # 그게 신호로 새 나가면 안 된다. object dtype으로 들어오는 경우까지 감안해
    # fillna 후 bool로 캐스팅한다.
    entry_flags = entries.fillna(False).to_numpy(dtype=bool)
    exit_flags = exits.fillna(False).to_numpy(dtype=bool)

    # ponytail: 순수 파이썬 루프. 보유 상태가 이전 봉에 의존하는 순차 로직이라
    # 벡터화가 자명하지 않다. 10만 봉에 약 50ms 수준이고 지금도 전략마다 같은
    # 루프를 돌고 있어 손해가 없다. 그리드 조합이 수천 개로 커져 그리드서치가
    # 체감상 느려지면 그때 numpy 누적 트릭이나 numba로 올린다.
    out = np.zeros(len(entry_flags), dtype=np.int8)
    holding = False

    for i in range(warmup, len(entry_flags)):
        if not holding and entry_flags[i]:
            out[i] = 1
            holding = True
        elif holding and exit_flags[i]:
            out[i] = -1
            holding = False

    return pd.Series(out, index=entries.index)


class Strategy(ABC):
    """
    모든 전략의 베이스 클래스.

    전략을 쓰는 방법은 두 가지다.

    1) 선언형 (권장) — entries()와 exits()에 조건식만 쓴다.
       보유 상태 관리, 중복 진입 차단, 워밍업 절단은 베이스가 알아서 한다.

           class MyStrategy(Strategy):
               def __init__(self, period=20):
                   self.period = period
                   self.warmup = period          # 지표가 익을 때까지 신호 없음
               def entries(self, df):
                   return df["close"] < df["close"].rolling(self.period).mean()
               def exits(self, df):
                   return df["close"] > df["close"].rolling(self.period).mean()

    2) 직접 구현 — generate_signals()를 오버라이드한다.
       쿨다운, 트레일링 스톱처럼 진짜 순차 상태가 필요할 때만 쓴다.
       (예: EmaCrossStrategyWithATR)
    """

    # 서브클래스가 __init__에서 self.warmup = self.slow 처럼 덮어쓴다.
    # 인스턴스 속성이 클래스 속성을 가리므로 둘 다 동작한다.
    warmup: int = 0

    def entries(self, df: pd.DataFrame) -> pd.Series:
        """매수 조건. df와 같은 인덱스를 가진 불리언 Series를 반환한다."""
        raise NotImplementedError(
            f"{type(self).__name__}는 entries()/exits()를 구현하거나 "
            "generate_signals()를 직접 오버라이드해야 합니다."
        )

    def exits(self, df: pd.DataFrame) -> pd.Series:
        """매도 조건. df와 같은 인덱스를 가진 불리언 Series를 반환한다."""
        raise NotImplementedError(
            f"{type(self).__name__}는 entries()/exits()를 구현하거나 "
            "generate_signals()를 직접 오버라이드해야 합니다."
        )

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        df: scrap.load_candles()가 반환하는 OHLCV 데이터프레임
        반환값: index가 df와 같고 값이 {-1, 0, 1}(매도, 유지, 매수)인 Series

        엔진은 이 인터페이스만 본다. 기본 구현은 entries/exits를 상태머신에
        태우는 것이고, 필요하면 서브클래스가 통째로 오버라이드해도 된다.
        """
        entries = self.entries(df)
        exits = self.exits(df)

        # 인덱스가 어긋나면 엔진이 .iloc으로 접근하는 탓에 조용히 엉뚱한 봉과
        # 짝지어진다. 여기서 미리 끊는 편이 디버깅이 훨씬 쉽다.
        if not entries.index.equals(df.index):
            raise ValueError(
                f"{type(self).__name__}.entries()의 인덱스가 df와 다릅니다. "
                "df의 인덱스를 그대로 쓰세요."
            )

        return to_signals(entries, exits, self.warmup)
