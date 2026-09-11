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
    "EmaCrossStrategyWithATR": {
        "fast": [5, 10, 20],
        "slow": [20, 40, 60],
        "atr_period": [10, 20, 30],
    },
    "MacdStrategy": {
        "fast": [6, 12, 24],
        "slow": [26, 52],
        "signal": [5, 9],
    },
    "DonchianBreakoutStrategy": {
        "entry_period": [20, 40, 60, 120],
        "exit_period": [10, 20, 40],
    },
    "TripleMaStrategy": {
        "short": [5, 10],
        "mid": [20, 40],
        "long": [60, 120],
    },
    "AdxDiStrategy": {
        "period": [7, 14, 21],
        "threshold": [15, 20, 25, 30],
    },
    "SupertrendStrategy": {
        "period": [7, 10, 14, 20],
        "mult": [2.0, 3.0, 4.0],
    },
    "ParabolicSarStrategy": {
        "af_step": [0.01, 0.02, 0.04],
        "af_max": [0.1, 0.2],
    },
    "HeikinAshiTrendStrategy": {
        "streak": [2, 3, 4, 5],
    },
    "IchimokuStrategy": {
        "tenkan": [9, 18],
        "kijun": [26, 52],
    },
    "ZScoreReversionStrategy": {
        "period": [20, 40, 60],
        "entry_z": [-1.5, -2.0, -2.5, -3.0],
        "exit_z": [-0.5, 0.0, 0.5],
    },
    "StochasticStrategy": {
        "k_period": [9, 14, 21],
        "oversold": [10, 20, 30],
        "exit_level": [60, 70, 80],
    },
    "WilliamsRStrategy": {
        "period": [7, 14, 28],
        "oversold": [-90, -80, -70],
        "exit_level": [-40, -30, -20],
    },
    "CciReversionStrategy": {
        "period": [14, 20, 40],
        "oversold": [-200, -150, -100],
        "exit_level": [-50, 0, 50],
    },
    "KeltnerReversionStrategy": {
        "ema_period": [10, 20, 40],
        "atr_period": [10, 20],
        "mult": [1.5, 2.0, 3.0],
    },
    "VwapReversionStrategy": {
        "band_pct": [0.001, 0.002, 0.003, 0.005],
    },
    "RocMomentumStrategy": {
        "period": [10, 20, 60],
        "threshold": [0.002, 0.003, 0.005, 0.01],
    },
    "MfiStrategy": {
        "period": [7, 14, 21],
        "oversold": [10, 20, 30],
        "exit_level": [50, 60, 70],
    },
    "ObvTrendStrategy": {
        "fast": [10, 20, 40],
        "slow": [60, 120],
    },
    "VolumeSpikeBreakoutStrategy": {
        "volume_period": [20, 60],
        "mult": [2.0, 3.0, 5.0],
        "exit_period": [10, 20, 40],
    },
    "AtrChannelBreakoutStrategy": {
        "ema_period": [10, 20, 40],
        "atr_period": [10, 20],
        "mult": [1.0, 1.5, 2.0],
    },
    "BollingerSqueezeStrategy": {
        "period": [20, 40],
        "num_std": [1.5, 2.0, 2.5],
        "squeeze_q": [0.1, 0.2, 0.3],
    },
    "OpeningRangeBreakoutStrategy": {
        "range_bars": [10, 20, 30, 60],
    },
    "VolatilityBreakoutStrategy": {
        "k": [0.3, 0.4, 0.5, 0.6, 0.8],
    },
    "GapFillStrategy": {
        "gap_pct": [0.002, 0.005, 0.01, 0.02],
    },
    "AroonStrategy": {
        "period": [14, 25, 40, 60],
        "threshold": [50, 60, 70, 80],
    },
    "VortexStrategy": {
        "period": [7, 14, 21, 30],
        "min_spread": [0.0, 0.03, 0.05, 0.1],
    },
    "TrixStrategy": {
        "period": [9, 15, 25],
        "signal_period": [5, 9],
        "require_positive": [True, False],
    },
    "ForceIndexStrategy": {
        "period": [5, 13, 25],
        "slow_period": [60, 100, 200],
        "use_trend_filter": [True, False],
    },
    "ChaikinMoneyFlowStrategy": {
        "period": [10, 20, 40],
        "entry_level": [0.02, 0.05, 0.1],
        "exit_level": [-0.1, -0.05, 0.0],
    },
    "AwesomeOscillatorStrategy": {
        "fast": [3, 5, 10],
        "slow": [21, 34, 55],
    },
    "ConnorsRsi2Strategy": {
        "rsi_period": [2, 3, 4],
        "oversold": [5, 10, 15, 20],
        "trend_period": [100, 200, 400],
    },
    "FisherTransformStrategy": {
        "period": [5, 10, 20],
        "entry_level": [-2.5, -2.0, -1.5, -1.0],
        "exit_level": [-0.5, 0.0, 0.5],
    },
    "UltimateOscillatorStrategy": {
        "oversold": [25, 30, 35, 40],
        "exit_level": [50, 55, 60, 65],
    },
    "Nr7BreakoutStrategy": {
        "period": [4, 7, 10, 14],
        "valid_bars": [5, 10, 20, 40],
    },
    "PivotPointStrategy": {
        "entry_ratio": [0.5, 0.75, 1.0, 1.25],
        "exit_at": ["pivot", "r1"],
    },
    # 오후 전략 넷은 after_bar(진입 허용 시각)가 가장 민감한 축이다. 실측에서
    # 임계값을 바꾸는 것보다 시각을 바꾸는 쪽이 결과를 훨씬 크게 흔들었다.
    "AfternoonOversoldStrategy": {
        "period": [7, 14, 21],
        "oversold": [20, 25, 30, 35],
        "after_bar": [240, 270, 300],
    },
    "AfternoonRangeBottomStrategy": {
        "pos_threshold": [0.05, 0.1, 0.2, 0.3],
        "after_bar": [240, 270, 300],
    },
    "GapDownOpenFadeStrategy": {
        "gap_pct": [0.002, 0.003, 0.005],
        "entry_to": [20, 35, 50],
        "exit_bar": [50, 65, 90],
    },
    # stop_below_vwap은 실측에서 켜는 순간 알파가 통째로 뒤집혔다. 그리드에
    # 남겨 둔 이유는 '왜 껐는지'를 다시 재현해 볼 수 있게 하려는 것뿐이다.
    "AfternoonVwapRecoveryStrategy": {
        "after_bar": [120, 180, 240],
        "stop_below_vwap": [True, False],
    },
    "GapUpFadeRecoveryStrategy": {
        "gap_pct": [0.002, 0.003, 0.005],
        "after_bar": [240, 270, 300],
    },
    # 정식(formulaic) 알파는 수식 자체에 손댈 파라미터가 없다. 논문 상수를 바꾸면
    # 그건 더 이상 그 알파가 아니다. 그래서 탐색 축은 알파값을 신호로 바꾸는
    # 껍데기 쪽(백분위 문턱과 비교 구간)뿐이다.
    "Alpha006Strategy": {"window": [250, 500], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3, 0.1]},
    "Alpha012Strategy": {"window": [250, 500], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3, 0.1]},
    "Alpha026Strategy": {"window": [250, 500], "entry_q": [0.6, 0.7, 0.8], "exit_q": [0.5, 0.3]},
    "Alpha035Strategy": {"window": [250, 500], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3, 0.1]},
    "Alpha101Strategy": {"window": [250, 500], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3, 0.1]},
    # 미시구조 전략도 수식이 아니라 껍데기(백분위 문턱)만 탐색한다.
    # period는 추정량의 창이라 바꾸면 다른 추정량이 되므로 좁게 둔다.
    "AmihudIlliquidityStrategy": {"period": [10, 20, 40], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3]},
    "RollSpreadStrategy": {"period": [10, 20, 40], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3]},
    "OrderFlowImbalanceStrategy": {"period": [5, 10, 20], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3]},
    "AdverseSelectionStrategy": {"period": [10, 20, 40], "entry_q": [0.8, 0.9, 0.95], "exit_q": [0.5, 0.3]},
    # OvernightInventoryStrategy는 시각 규칙이라 탐색할 파라미터가 없다.
}


# 무효한 조합을 걸러내는 함수. 여기 없는 전략은 모든 조합을 다 시도한다.
VALID: dict[str, callable] = {
    # 단기선이 장기선보다 짧아야 크로스가 의미를 갖는다
    "EmaCrossStrategy": lambda p: p["fast"] < p["slow"],
    "EmaCrossStrategyWithADX": lambda p: p["fast"] < p["slow"],
    # 과매도 기준이 청산 기준보다 낮아야 왕복이 성립한다
    "RsiReversionStrategy": lambda p: p["oversold"] < p["exit_level"],
    "EmaCrossStrategyWithATR": lambda p: p["fast"] < p["slow"],
    "MacdStrategy": lambda p: p["fast"] < p["slow"],
    # 청산 채널이 진입 채널보다 짧아야 추세가 꺾일 때 빨리 나온다
    "DonchianBreakoutStrategy": lambda p: p["exit_period"] <= p["entry_period"],
    "TripleMaStrategy": lambda p: p["short"] < p["mid"] < p["long"],
    "ZScoreReversionStrategy": lambda p: p["entry_z"] < p["exit_z"],
    "StochasticStrategy": lambda p: p["oversold"] < p["exit_level"],
    "WilliamsRStrategy": lambda p: p["oversold"] < p["exit_level"],
    "CciReversionStrategy": lambda p: p["oversold"] < p["exit_level"],
    "MfiStrategy": lambda p: p["oversold"] < p["exit_level"],
    "ObvTrendStrategy": lambda p: p["fast"] < p["slow"],
    "IchimokuStrategy": lambda p: p["tenkan"] < p["kijun"],
    # 단기 강도지수가 추세 필터보다 짧아야 '타이밍 + 필터' 조합이 된다
    "ForceIndexStrategy": lambda p: p["period"] < p["slow_period"],
    # 매집 문턱이 분산 문턱보다 위에 있어야 완충대가 생긴다
    "ChaikinMoneyFlowStrategy": lambda p: p["exit_level"] < p["entry_level"],
    "AwesomeOscillatorStrategy": lambda p: p["fast"] < p["slow"],
    "FisherTransformStrategy": lambda p: p["entry_level"] < p["exit_level"],
    "UltimateOscillatorStrategy": lambda p: p["oversold"] < p["exit_level"],
}
