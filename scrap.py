"""
토스 서버에서 원하는 종목의 분봉을 받아 오는 패키지
중요한 함수는 update_candles(ticker) — 토큰은 이 모듈이 알아서 처리함
"""

DEFAULT_DB_PATH = "market_data.db"
API_BASE = "https://openapi.tossinvest.com/api/v1/candles"
TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"

import sqlite3
import time
from typing import Optional
import pandas as pd
import requests

from dotenv import load_dotenv
import os

load_dotenv()  # .env를 환경변수로 로드 (모듈 임포트 시 1회 실행)

# 모듈 내부에서만 쓰는 토큰 캐시. 밖에서 직접 건드리지 말 것.
_access_token: Optional[str] = None
_token_expires_at: float = 0.0


def update_candles(ticker: str, interval: str = "1m",
                    adjusted: bool = True, db_path: str = DEFAULT_DB_PATH,
                    max_pages: int = 200, initial_bars: int = 20000) -> int:
    """
    주어진 ticker의 1분봉을 받아서 DB에 저장한다.
    토큰 발급/갱신은 내부적으로 처리되므로 호출부는 신경 쓸 필요 없음.
    """
    access_token = _get_access_token()
    conn = _get_conn(db_path)
    last_ts = get_last_timestamp(conn, ticker, interval)

    new_rows = []
    before = None
    pages = 0
    reached_existing = False

    while pages < max_pages:
        candles, next_before = _fetch_page(ticker, interval, access_token,
                                            count=200, before=before, adjusted=adjusted)
        if not candles:
            break

        for c in candles:
            ts = c["timestamp"]
            if last_ts is not None and ts <= last_ts:
                reached_existing = True
                break
            new_rows.append((
                ticker, interval, ts,
                float(c["openPrice"]), float(c["highPrice"]),
                float(c["lowPrice"]), float(c["closePrice"]), float(c["volume"]),
            ))

        pages += 1
        if reached_existing:
            break
        if not next_before:
            break
        if last_ts is None and len(new_rows) >= initial_bars:
            break
        before = next_before

    inserted = 0
    if new_rows:
        before_changes = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO candles
            (ticker, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, new_rows)
        conn.commit()
        inserted = conn.total_changes - before_changes

    conn.close()
    return inserted

def update_multiple(tickers: list[str], interval: str = "1m",
                     adjusted: bool = True, db_path: str = DEFAULT_DB_PATH) -> dict:
    results = {}
    for ticker in tickers:
        added = update_candles(ticker, interval, adjusted, db_path)
        results[ticker] = added
        print(f"  {ticker} ({interval}): {added}개 추가")
    return results

def load_candles(ticker: str, interval: str = "1m", db_path: str = DEFAULT_DB_PATH,
                  start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    conn = _get_conn(db_path)
 
    query = "SELECT timestamp, open, high, low, close, volume FROM candles WHERE ticker = ? AND timeframe = ?"
    params = [ticker, interval]
 
    if start:
        query += " AND timestamp >= ?"
        params.append(start)
    if end:
        query += " AND timestamp <= ?"
        params.append(end)
 
    query += " ORDER BY timestamp ASC"
 
    df = pd.read_sql(query, conn, params=params)
    conn.close()
 
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
 
    return df
 

def get_last_timestamp(conn: sqlite3.Connection, ticker: str, interval: str) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(timestamp) FROM candles WHERE ticker = ? AND timeframe = ?",
        (ticker, interval),
    ).fetchone()
    return row[0] if row and row[0] else None


def _get_access_token() -> str:
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


def _get_conn(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    _init_db(conn)
    return conn

def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            ticker    TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open      REAL NOT NULL,
            high      REAL NOT NULL,
            low       REAL NOT NULL,
            close     REAL NOT NULL,
            volume    REAL NOT NULL,
            PRIMARY KEY (ticker, timeframe, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_candles_lookup
        ON candles (ticker, timeframe, timestamp)
    """)
    conn.commit()

def _fetch_page(ticker: str, interval: str, access_token: str,
                 count: int = 200, before: Optional[str] = None,
                 adjusted: bool = True) -> tuple[list, Optional[str]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "symbol": ticker,
        "interval": interval,
        "count": count,
        "adjusted": str(adjusted).lower(),
    }
    if before:
        params["before"] = before  # requests가 '+' 등을 알아서 URL 인코딩함
 
    resp = requests.get(API_BASE, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"API 호출 실패 [{resp.status_code}]: {resp.text}")
 
    result = resp.json()["result"]
    candles = result.get("candles", []) # get(key, default)
    next_before = result.get("nextBefore")
    return candles, next_before

def _main():
    import argparse

    parser = argparse.ArgumentParser(description="토스 API로 캔들 데이터 업데이트")
    parser.add_argument("tickers", nargs="+", help="종목 코드 (여러 개 가능, 공백으로 구분)")
    parser.add_argument("--interval", default="1m", help="봉 주기 (기본: 1m)")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="DB 파일 경로")
    parser.add_argument("--no-adjust", action="store_true", help="수정주가 미적용")
    args = parser.parse_args()

    adjusted = not args.no_adjust

    if len(args.tickers) == 1:
        added = update_candles(args.tickers[0], interval=args.interval,
                                adjusted=adjusted, db_path=args.db_path)
        print(f"{args.tickers[0]} ({args.interval}): {added}개 추가")
    else:
        update_multiple(args.tickers, interval=args.interval,
                         adjusted=adjusted, db_path=args.db_path)


if __name__ == "__main__":
    _main()