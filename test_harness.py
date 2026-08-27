"""
하네스 자체 검사. 프레임워크 없이 `python test_harness.py`로 실행한다.
전략의 수익성을 검증하는 게 아니라, 하네스 배관(상태머신·FIFO 짝짓기)이
깨졌는지를 잡는 것이 목적이다.
"""
import pandas as pd

import strategies
from backtest_engine import run_backtest
from grids import GRIDS, VALID
from metrics import trade_stats
from print_summary import to_daily_summary
from strategies.base import to_signals


def _s(values):
    """불리언 리스트를 Series로. 인덱스는 0부터의 정수."""
    return pd.Series(values, dtype=bool)


def test_to_signals_기본_왕복():
    # 진입 신호가 두 번 연속 떠도 이미 보유 중이면 두 번째는 무시되어야 한다.
    entries = _s([True, True, False, False])
    exits = _s([False, False, True, False])
    assert list(to_signals(entries, exits)) == [1, 0, -1, 0]


def test_to_signals_중복_진입_차단():
    # 진입 조건이 계속 참이어도 청산 전까지는 추가 매수가 나가면 안 된다.
    # (이 규칙이 깨지면 포지션이 무한히 쌓인다 — 구 엔진의 대표적 함정)
    entries = _s([True] * 5)
    exits = _s([False] * 5)
    assert list(to_signals(entries, exits)) == [1, 0, 0, 0, 0]


def test_to_signals_미보유_청산_무시():
    # 보유하지 않은 상태의 청산 조건은 아무 일도 일으키지 않는다.
    entries = _s([False] * 3)
    exits = _s([True] * 3)
    assert list(to_signals(entries, exits)) == [0, 0, 0]


def test_to_signals_워밍업_구간은_전부_0():
    # 지표가 아직 신뢰할 수 없는 구간은 통째로 0이어야 한다.
    entries = _s([True] * 5)
    exits = _s([False] * 5)
    assert list(to_signals(entries, exits, warmup=3)) == [0, 0, 0, 1, 0]


def test_to_signals_동시신호_결정1():
    # 설계 결정 1: 미보유면 진입이 이기고, 보유 중이면 청산이 이긴다.
    entries = _s([True, True])
    exits = _s([True, True])
    #  i=0: 미보유 + 둘 다 참 -> 진입
    #  i=1: 보유   + 둘 다 참 -> 청산
    assert list(to_signals(entries, exits)) == [1, -1]


def test_to_signals_NaN은_False로_취급():
    # 지표 워밍업 구간에서 NaN이 나오는 건 정상. 신호로 새면 안 된다.
    entries = pd.Series([None, True, None], dtype=object)
    exits = pd.Series([None, None, True], dtype=object)
    assert list(to_signals(entries, exits)) == [0, 1, -1]


def test_to_signals_인덱스_보존():
    # 반환 Series는 입력 인덱스를 그대로 유지해야 한다
    # (엔진이 df와 나란히 쓰기 때문).
    idx = pd.date_range("2026-01-01", periods=3, freq="min")
    entries = pd.Series([True, False, False], index=idx)
    exits = pd.Series([False, False, True], index=idx)
    assert to_signals(entries, exits).index.equals(idx)


def test_to_signals_인덱스_불일치는_에러():
    entries = pd.Series([True], index=[0])
    exits = pd.Series([False], index=[1])
    try:
        to_signals(entries, exits)
    except ValueError:
        pass
    else:
        raise AssertionError("인덱스가 다른데 ValueError가 나지 않았다")


def _candles(closes):
    """종가만 지정해서 최소한의 OHLCV df를 만든다. 고가/저가는 종가와 동일."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01 09:00", periods=len(closes), freq="min"),
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume": [1.0] * len(closes),
    })


def test_engine_fill_price_슬리피지_반영():
    # 매수 체결가는 원가격보다 비싸고, 매도 체결가는 원가격보다 싸야 한다.
    df = _candles([100.0, 110.0])
    signal = pd.Series([1, -1], index=df.index)
    result = run_backtest(df, signal, buy_slippage=0.01, sell_slippage=0.02)

    buy = result.trades[result.trades["side"] == "buy"].iloc[0]
    sell = result.trades[result.trades["side"] == "sell"].iloc[0]
    assert buy["fill_price"] == 101.0   # 100 + 100*0.01
    assert sell["fill_price"] == 107.8  # 110 - 110*0.02


def test_trade_stats_손으로_계산한_값과_일치():
    # 왕복 2건: 하나는 이기고 하나는 진다.
    #   1) 100에 사서 110에 팜 -> +10, 수익률 +10%
    #   2) 200에 사서 180에 팜 -> -20, 수익률 -10%
    trades = pd.DataFrame([
        {"position": 0, "date": None, "side": "buy",  "price": 100.0, "fill_price": 100.0},
        {"position": 2, "date": None, "side": "sell", "price": 110.0, "fill_price": 110.0},
        {"position": 5, "date": None, "side": "buy",  "price": 200.0, "fill_price": 200.0},
        {"position": 9, "date": None, "side": "sell", "price": 180.0, "fill_price": 180.0},
    ])
    stats = trade_stats(trades)

    assert stats["round_trips"] == 2
    assert stats["win_rate"] == 0.5
    assert abs(stats["avg_return"] - 0.0) < 1e-12       # (+0.10 + -0.10) / 2
    assert abs(stats["avg_win"] - 0.10) < 1e-12
    assert abs(stats["avg_loss"] - (-0.10)) < 1e-12
    assert abs(stats["profit_factor"] - 0.5) < 1e-12    # 총이익 10 / 총손실 20
    assert stats["avg_holding_bars"] == 3.0             # (2-0)과 (9-5)의 평균
    assert stats["open_position"] == 0


def test_trade_stats_미청산_포지션_분리():
    # 마지막 매수가 청산되지 않았다면 왕복으로 세지 않고 따로 보고한다
    # (설계 결정 2: 마지막 봉에서 강제 청산하지 않는다).
    trades = pd.DataFrame([
        {"position": 0, "date": None, "side": "buy",  "price": 100.0, "fill_price": 100.0},
        {"position": 2, "date": None, "side": "sell", "price": 110.0, "fill_price": 110.0},
        {"position": 5, "date": None, "side": "buy",  "price": 200.0, "fill_price": 200.0},
    ])
    stats = trade_stats(trades)
    assert stats["round_trips"] == 1
    assert stats["open_position"] == 1
    assert stats["win_rate"] == 1.0


def test_trade_stats_거래_없음():
    # 신호가 하나도 안 나온 전략에서 ZeroDivisionError가 나면 안 된다.
    stats = trade_stats(pd.DataFrame())
    assert stats["round_trips"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["profit_factor"] == 0.0


def test_daily_summary_일별_손익():
    # 이틀치 데이터. 하루가 넘어갈 때 그날의 손익이 누적이 아니라
    # '그날 번 돈'으로 나와야 한다.
    df = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01 09:00", "2026-01-01 09:01",
            "2026-01-02 09:00", "2026-01-02 09:01",
        ]),
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [100.0, 110.0, 110.0, 130.0],
        "low":  [100.0, 110.0, 110.0, 130.0],
        "close": [100.0, 110.0, 110.0, 130.0],
        "volume": [1.0] * 4,
    })
    # 첫 봉에 매수하고 계속 보유 -> 평가손익만 움직인다.
    signal = pd.Series([1, 0, 0, 0], index=df.index)
    result = run_backtest(df, signal, buy_slippage=0.0, sell_slippage=0.0)

    daily = to_daily_summary(df, result)
    assert "daily_pnl" in daily.columns
    # 1일차 마감 누적 +10, 2일차 마감 누적 +30 -> 2일차의 그날 손익은 +20
    assert abs(daily["daily_pnl"].iloc[0] - 10.0) < 1e-9
    assert abs(daily["daily_pnl"].iloc[1] - 20.0) < 1e-9
    # 누적 컬럼은 그대로 살아 있어야 한다
    assert abs(daily["end_of_day_equity"].iloc[1] - 30.0) < 1e-9


def test_registry_전략을_이름으로_찾을_수_있다():
    # CLI가 "EmaCrossStrategy" 같은 문자열로 클래스를 찾아야 한다.
    assert "EmaCrossStrategy" in strategies.REGISTRY
    assert "BollingerBandStrategy" in strategies.REGISTRY
    # 베이스 클래스 자체는 실행 대상이 아니므로 들어 있으면 안 된다.
    assert "Strategy" not in strategies.REGISTRY
    # 레지스트리에 담긴 건 인스턴스가 아니라 클래스여야 한다.
    assert isinstance(strategies.REGISTRY["EmaCrossStrategy"], type)


def test_grids_키는_전부_실재하는_전략():
    # 오타난 클래스명이 grids.py에 남아 있으면 --optimize가 조용히 건너뛴다.
    for name in GRIDS:
        assert name in strategies.REGISTRY, f"REGISTRY에 없는 전략: {name}"
    for name in VALID:
        assert name in GRIDS, f"VALID에만 있고 GRIDS에 없는 전략: {name}"


def test_grids_파라미터명이_생성자와_일치():
    # 그리드 키가 __init__ 인자와 다르면 grid_search가 TypeError로 죽는다.
    import inspect
    for name, grid in GRIDS.items():
        params = inspect.signature(strategies.REGISTRY[name].__init__).parameters
        for key in grid:
            assert key in params, f"{name}에 없는 파라미터: {key}"


def _run_all():
    """이 모듈의 test_로 시작하는 함수를 전부 실행한다."""
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        fn()
        print(f"  PASS  {name}")
    print(f"\n{len(tests)}개 통과")


if __name__ == "__main__":
    _run_all()
