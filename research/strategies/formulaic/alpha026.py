# -*- coding: utf-8 -*-
from .base import FormulaicAlpha, correlation, ts_rank, ts_max
import pandas as pd


class Alpha026Strategy(FormulaicAlpha):
    """
    WorldQuant Alpha#26:

        (-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))

    Alpha#6과 묻는 것은 같다 — 가격과 거래량이 동조하는가. 다른 점이 셋이다.

    1) 원값이 아니라 **순위끼리** 상관을 잰다. ts_rank(x, 5)는 '최근 5봉 중 지금이
       몇 번째로 큰가'라서 스피어만 상관에 가까워진다. 거래량은 분포 꼬리가 아주
       두꺼워서(평소의 30배가 흔하다) 원값으로 피어슨 상관을 내면 그 한 봉이 계수를
       통째로 끌고 간다. 순위로 바꾸면 그 지배력이 사라진다.

    2) 시가가 아니라 **고가**를 쓴다. 그 봉에서 매수측이 도달한 최고점이다.

    3) 상관을 낸 뒤 `ts_max(..., 3)`으로 **최근 3봉 중 최댓값**을 취하고 부호를 뒤집는다.
       즉 '지난 3봉 안에 한 번이라도 강하게 동조한 적이 있으면' 알파가 크게 마이너스다.
       한 봉의 동조는 우연일 수 있으니 최근 몇 봉의 최악(=가장 동조한) 값으로 벌점을
       매기는 구조다. 이 세 겹(ts_rank → correlation → ts_max) 중첩이 101 알파들의
       전형적인 형태다.

    lookback 13 = ts_rank 5봉 + correlation 5봉 + ts_max 3봉. 각 단계가 앞 단계의
    출력을 다시 rolling하므로 유효 워밍업은 셋의 합이다.

    ── 검증 (코스피 대형주 43종목 일봉, 1975~2026) ── out-of-sample에서 실패
        train(~2014)  초과 +2.94bp/봉 (t=+2.4)  비용 1.60  순 +1.34
        test (2015~)  초과 +0.77bp/봉 (t=+0.5)  비용 1.54  순 -0.77
        격자 18조합 중 순알파 양수: train 56% / test 39%

      ※ 이 판정은 한 번 틀렸다가 고친 것이다. 처음에는 '진입 69회, 신호가 거의 안
        나온다'로 적었는데, 그건 알파의 성질이 아니라 버그였다. correlation은 창
        안에서 분모가 0이면 NaN을 내는데(이 알파는 correlation을 두 번 겹친다),
        pandas의 rolling은 min_periods 기본값이 window라 창에 NaN이 하나만 있어도
        결과가 통째로 NaN이다. 그래서 백분위가 거의 전 구간에서 계산되지 않았다.
        score_base.py에 min_periods를 넣어 고치고 나니 진입이 6,256회로 늘었고,
        그 제대로 된 숫자로 다시 재니 위와 같이 out-of-sample에서 진다.
        **신호가 안 나오는 것과 신호가 나쁜 것은 다른 결론이고, 전자는 대개 버그다.**
    """

    lookback = 13

    def alpha(self, df: pd.DataFrame) -> pd.Series:
        return -1 * ts_max(
            correlation(ts_rank(df["volume"], 5), ts_rank(df["high"], 5), 5), 3)
