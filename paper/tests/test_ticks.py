"""호가단위 표 검증. `python paper/tests/test_ticks.py`로 돌린다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from paper.ticks import is_valid_price, tick_size


def test_구간별_호가단위():
    # KRX 국내주식 호가단위 (2023-01-25 개정 기준)
    assert tick_size(1_999) == 1
    assert tick_size(2_000) == 5
    assert tick_size(4_999) == 5
    assert tick_size(5_000) == 10
    assert tick_size(19_999) == 10
    assert tick_size(20_000) == 50
    assert tick_size(49_999) == 50
    assert tick_size(50_000) == 100
    assert tick_size(199_999) == 100
    assert tick_size(200_000) == 500
    assert tick_size(499_999) == 500
    assert tick_size(500_000) == 1_000
    assert tick_size(1_000_000) == 1_000


def test_경계값이_아래_구간이_아니라_위_구간에_속한다():
    # 2,000원 정확히는 1원 단위가 아니라 5원 단위다. 경계를 반대로 잡으면
    # 1,999원짜리 주문이 막히고 2,000원짜리가 통과하는 식으로 뒤집힌다.
    assert tick_size(1_999) == 1
    assert tick_size(2_000) == 5


def test_유효_지정가_판정():
    assert is_valid_price(258_500)        # 20만~50만 -> 500원 단위
    assert not is_valid_price(258_550)
    assert not is_valid_price(258_100)
    assert is_valid_price(1_999)          # 2천원 미만 -> 1원 단위
    assert is_valid_price(7_010)          # 5천~2만 -> 10원 단위
    assert not is_valid_price(7_005)


def test_실제_호가와_일치한다():
    # 2026-08-31에 토스 API로 실제로 받은 삼성전자 호가다:
    # 258,000 / 258,500 / 259,000 / 259,500 / 260,000 — 간격이 500원이다.
    # 표가 한 칸이라도 밀리면 이 assert가 깨진다. 이 파일의 유일한 실측 근거라
    # 지우지 마라.
    assert tick_size(258_500) == 500
    for price in (258_000, 258_500, 259_000, 259_500, 260_000):
        assert is_valid_price(price)


def test_0원_이하는_유효하지_않다():
    assert not is_valid_price(0)
    assert not is_valid_price(-100)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("test_ticks 통과")
