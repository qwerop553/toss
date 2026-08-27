"""
전략 신호의 골든 스냅샷 도구.

리팩터링(예: holding 루프를 entries/exits로 옮기기) 전에 현재 신호를 실데이터로
떠 두고, 리팩터링 후 완전히 동일한지 비교한다. 수익성을 검증하는 게 아니라
'행동이 바뀌지 않았음'을 보장하는 것이 목적이다.

사용법:
    python snapshot_signals.py capture    # 리팩터링 전에 실행
    python snapshot_signals.py verify     # 리팩터링 후에 실행
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import scrap

SNAPSHOT_DIR = Path(__file__).parent / "tests_golden"
TICKER = "005930"
INTERVAL = "1m"


def _load():
    """스냅샷 기준 데이터. 매번 같은 구간을 써야 비교가 의미 있다."""
    df = scrap.load_candles(TICKER, INTERVAL)
    if df.empty:
        raise RuntimeError(
            f"{TICKER} {INTERVAL} 데이터가 없습니다. "
            f"먼저 `python scrap.py {TICKER} --interval {INTERVAL}`를 실행하세요."
        )
    return df.reset_index(drop=True)


def _path(name: str) -> Path:
    return SNAPSHOT_DIR / f"{name}.npy"


def capture(name: str, strategy, df: pd.DataFrame) -> None:
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    signal = strategy.generate_signals(df)
    np.save(_path(name), signal.to_numpy(dtype=np.int8))
    nonzero = int((signal != 0).sum())
    print(f"  저장  {name}: {len(signal)}봉, 신호 {nonzero}개")


def verify(name: str, strategy, df: pd.DataFrame) -> bool:
    expected = np.load(_path(name))
    actual = strategy.generate_signals(df).to_numpy(dtype=np.int8)

    if len(expected) != len(actual):
        print(f"  실패  {name}: 길이가 다름 {len(expected)} -> {len(actual)}")
        return False

    diff = np.flatnonzero(expected != actual)
    if len(diff):
        print(f"  실패  {name}: {len(diff)}개 봉에서 신호가 다름 (첫 위치 {diff[0]}, "
              f"기대 {expected[diff[0]]} 실제 {actual[diff[0]]})")
        return False

    print(f"  통과  {name}: {len(actual)}봉 완전 일치")
    return True


def _cases():
    """스냅샷을 뜰 (이름, 전략 인스턴스) 목록. 마이그레이션 대상 전부."""
    from strategies.mean_reversion.bollinger_band import BollingerBandStrategy
    from strategies.mean_reversion.rsi_reversion import RsiReversionStrategy
    from strategies.session_based.session_close import SessionCloseStrategy
    from strategies.session_based.opening import OpeningRangeStrategy
    from strategies.trend_following.ema_cross_with_adx import EmaCrossStrategyWithADX

    return [
        ("bollinger", BollingerBandStrategy(period=20, num_std=2.0)),
        ("rsi", RsiReversionStrategy(period=14, oversold=30, exit_level=50)),
        ("session_close", SessionCloseStrategy()),
        ("opening", OpeningRangeStrategy(market_open_time="09:29")),
        ("adx", EmaCrossStrategyWithADX(fast=6, slow=12, atr_period=20)),
    ]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    df = _load()
    print(f"{TICKER} {INTERVAL}, {len(df)}봉 기준\n")

    if mode == "capture":
        for name, strategy in _cases():
            capture(name, strategy, df)
        print("\n스냅샷 저장 완료. 리팩터링 후 `python snapshot_signals.py verify`로 확인하세요.")
        return 0

    ok = all([verify(name, strategy, df) for name, strategy in _cases()])
    print("\n전부 일치" if ok else "\n불일치 발생 — 리팩터링이 행동을 바꿨습니다")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
