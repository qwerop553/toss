"""
KRX 국내주식 호가단위.

왜 필요한가:
  258,500원짜리 종목의 호가단위는 100원이라 258,550원 같은 지정가는 실제로
  낼 수 없다. 막지 않으면 현실에 존재하지 않는 주문이 주문장에 들어가고,
  그 주문이 체결되는 순간 모의투자 전체가 거짓말이 된다.

표는 2023-01-25 개정된 현행 기준이다. 개정되면 아래 표만 고치면 된다.
"""

# (하한가, 호가단위). 가격이 하한가 '이상'이면 그 구간이다. 큰 값부터 훑는다.
_TIERS = [
    (500_000, 500),
    (200_000, 100),
    (50_000, 50),
    (20_000, 10),
    (5_000, 5),
    (0, 1),
]


def tick_size(price: int) -> int:
    """price가 속한 구간의 호가단위를 돌려준다."""
    for floor, tick in _TIERS:
        if price >= floor:
            return tick
    return 1  # 도달하지 않는다. _TIERS의 마지막이 0이라서.


def is_valid_price(price: int) -> bool:
    """실제로 낼 수 있는 지정가인지."""
    if price <= 0:
        return False
    return price % tick_size(price) == 0
