"""
토스 Open API 액세스 토큰 발급과 캐시.

candles.py에서 떼어낸 이유:
  이 토큰은 캔들 수집(data/candles.py)과 모의투자(paper/)가 함께 쓴다. 그런데
  candles.py는 pandas·sqlite를 끌고 오는 무거운 모듈이라, 토큰 한 줄 쓰자고
  paper/toss.py와 paper/feed.py가 데이터프레임 스택 전체를 import하게 된다.
  여기 떼어 두면 paper/는 requests만 있으면 된다.
"""
import os
import time
from typing import Optional

import requests
from dotenv import load_dotenv

TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"

load_dotenv()  # .env를 환경변수로 로드 (모듈 임포트 시 1회 실행)

# 모듈 내부에서만 쓰는 토큰 캐시. 밖에서 직접 건드리지 말 것.
_access_token: Optional[str] = None
_token_expires_at: float = 0.0


def get_access_token() -> str:
    """
    캐시된 토큰이 있고 아직 유효하면 재사용, 없거나 만료됐으면 재발급.
    """
    global _access_token, _token_expires_at
    if _access_token is None or time.time() >= _token_expires_at:
        _access_token, expires_in = _issue_token()
        # 만료 60초 전에 미리 갱신하도록 여유를 둠
        _token_expires_at = time.time() + expires_in - 60
    return _access_token


def _issue_token() -> tuple[str, int]:
    client_id = os.getenv("TOSS_CLIENT_ID")
    client_secret = os.getenv("TOSS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 환경변수가 없음. .env 확인 바람")

    response = requests.post(
        url=TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(f"access_token 획득 실패 [{response.status_code}]. IP 등록 확인 바람")

    body = response.json()
    access_token = body.get("access_token")
    expires_in = body.get("expires_in", 3600)  # API가 안 주면 1시간으로 가정
    if not access_token:
        raise RuntimeError("응답에 access_token이 없음")

    return access_token, expires_in
