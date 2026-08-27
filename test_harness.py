"""
하네스 자체 검사. 프레임워크 없이 `python test_harness.py`로 실행한다.
전략의 수익성을 검증하는 게 아니라, 하네스 배관(상태머신·FIFO 짝짓기)이
깨졌는지를 잡는 것이 목적이다.
"""
import pandas as pd

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
