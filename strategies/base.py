# ABC : Abstract Base Class, 상속해서 사용하지 않으면 오류를 낸다.
# asbtractmethod를 붙이면 이 메서드를 구현 하지 않은 자식 클래스는 아예 인스턴스를 만들지 못한다.
from abc import ABC, abstractmethod
import pandas as pd

class Strategy(ABC):
    """ 모든 전략의 베이스 클래스"""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        df: scrap.load_candles()가 반환하는 OHLCV(Open, High, Low, Close, Volume) 데이터프레임
        반환값: index가 df와 같고, 값은 {-1, 0, 1} (매도, 유지, 매수) 인 Series
        각 전략은 이 인터페이스만 지키면 된다.
        """
        pass


