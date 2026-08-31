"""호가단위 표 검증. `python paper/test_ticks.py`로 돌린다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper.ticks import is_valid_price, tick_size


def test_구간별_호가단위():
    # KRX 국내주식 호가단위 (2023-01-25 개정 기준)
    assert tick_size(1_500) == 1
    assert tick_size(4_999) == 1
    assert tick_size(5_000) == 5
    assert tick_size(19_999) == 5
    assert tick_size(20_000) == 10
    assert tick_size(49_999) == 10
    assert tick_size(50_000) == 50
    assert tick_size(199_999) == 50
    assert tick_size(200_000) == 100
    assert tick_size(499_999) == 100
    assert tick_size(500_000) == 500
    assert tick_size(1_000_000) == 500


def test_경계값이_아래_구간이_아니라_위_구간에_속한다():
    # 5,000원 정확히는 1원 단위가 아니라 5원 단위다. 경계를 반대로 잡으면
    # 4,999원짜리 주문이 통과하고 5,000원짜리가 막히는 식으로 뒤집힌다.
    assert tick_size(4_999) == 1
    assert tick_size(5_000) == 5


def test_유효_지정가_판정():
    assert is_valid_price(258_500)        # 20만원대 -> 100원 단위
    assert not is_valid_price(258_550)
    assert not is_valid_price(258_501)
    assert is_valid_price(4_999)          # 5천원 미만 -> 1원 단위
    assert is_valid_price(7_005)          # 5천~2만 -> 5원 단위
    assert not is_valid_price(7_003)


def test_0원_이하는_유효하지_않다():
    assert not is_valid_price(0)
    assert not is_valid_price(-100)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_ticks 통과")
