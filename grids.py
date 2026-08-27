"""
전략별 파라미터 탐색 범위.

run.py --optimize가 여기를 보고 그리드서치를 돌린다. 전략 코드는 순수하게
유지하고 '어디를 뒤질지'는 이 파일 한 곳에 모은다.

여기에 없는 전략은 --optimize를 줘도 조용히 기본 파라미터 1회 실행으로
넘어간다. 탐색할 게 없는 전략(예: 시간 기반)은 그게 맞는 동작이다.

범위를 넓힐수록 조합 수가 곱셈으로 늘어난다. fast 11개 x slow 10개 =
110회 백테스트인데, 여기에 세 번째 축을 곱하면 금방 수천 회가 된다.
"""

GRIDS: dict[str, dict] = {
    "EmaCrossStrategy": {
        "fast": range(5, 60, 5),
        "slow": range(20, 120, 10),
    },
    "EmaCrossStrategyWithADX": {
        "fast": range(5, 30, 5),
        "slow": range(20, 80, 10),
        "atr_period": [10, 20, 30],
    },
    "BollingerBandStrategy": {
        "period": [10, 20, 30, 40],
        "num_std": [1.5, 2.0, 2.5, 3.0],
    },
    "RsiReversionStrategy": {
        "period": [7, 14, 21],
        "oversold": [20, 25, 30, 35],
        "exit_level": [45, 50, 55, 60],
    },
}

# 무효한 조합을 걸러내는 함수. 여기 없는 전략은 모든 조합을 다 시도한다.
VALID: dict[str, callable] = {
    # 단기선이 장기선보다 짧아야 크로스가 의미를 갖는다
    "EmaCrossStrategy": lambda p: p["fast"] < p["slow"],
    "EmaCrossStrategyWithADX": lambda p: p["fast"] < p["slow"],
    # 과매도 기준이 청산 기준보다 낮아야 왕복이 성립한다
    "RsiReversionStrategy": lambda p: p["oversold"] < p["exit_level"],
}
