"""
토스 데이터 수집 패키지(시세 캔들, 종목 목록, 인증).

이 패키지가 쓰는 경로 상수는 여기 한 곳에만 적는다.
"""


import os
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(_ROOT, "market_data.db")
