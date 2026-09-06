from ..base import Strategy
from ..indicators import cmf
import pandas as pd


class ChaikinMoneyFlowStrategy(Strategy):
    """
    Chaikin Money Flow. 봉 '내부'의 매집/분산을 누적해서 본다.

    MfiStrategy와 재료가 겹치는 듯하지만 보는 층위가 다르다. MFI는 전형가격이 전
    봉보다 올랐는지(봉과 봉 사이)를 보고, CMF는 종가가 그 봉의 고저 범위 어디에서
    끝났는지(봉 하나 안)를 본다. 장중 내내 밀리다가 종가만 겨우 올린 봉을 MFI는
    매수로, CMF는 매도로 읽는다. 그 해석 차이가 이 전략을 따로 두는 이유다.

    ±0.05를 기본 문턱으로 쓴다. CMF는 -1~+1 범위지만 실제로는 대부분 ±0.25 안에서
    놀아서, 0.05만 넘어도 한쪽 압력이 뚜렷한 편이다.
    """

    def __init__(self, period=20, entry_level=0.05, exit_level=-0.05):
        self.period = period
        self.entry_level = entry_level
        self.exit_level = exit_level
        self.warmup = period

    def entries(self, df: pd.DataFrame) -> pd.Series:
        # [매수] 매집 우위. 종가가 봉의 위쪽에서 끝나는 봉에 거래량이 실리고 있다
        return cmf(df, self.period) >= self.entry_level

    def exits(self, df: pd.DataFrame) -> pd.Series:
        # [매도] 분산 우위로 전환. 0이 아니라 음수 문턱을 쓰는 건 0 근처의
        # 잔떨림으로 들락거리지 않기 위해서다 (진입/청산 사이에 완충대를 둔다).
        return cmf(df, self.period) <= self.exit_level
