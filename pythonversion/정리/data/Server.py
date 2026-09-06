import os
import time
import requests
import sqlite3
from dotenv import load_dotenv


def _get_last_timestamp(conn: sqlite3.Connection, ticker: str):
    row = conn.execute(
        "SELECT MAX(timestamp) FROM candles WHERE ticker = ?",
        (ticker,)
    ).fetchone()
    return row[0] if row and row[0] else None

class DB:
    _instance = None
    _initialized = False
    _access_token = _client_id = _client_secret = None
    _token_expires_at = None

    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _DB_PATH = os.path.join(_ROOT, "market_data.db")
    _API_BASE = "https://openapi.tossinvest.com/api/v1/candles"
    _TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"

    def update(self, *tickers: tuple[str]):
        self._refresh_token()
        conn = sqlite3.connect(self._DB_PATH)
        updated = {}
        for ticker in tickers:
            last_ts = _get_last_timestamp(conn, ticker)

            new_rows = []
            before = None
            pages = 0
            reached_existing = False

            headers = {"Authorization": f"Bearer {self._access_token}"}
            params = {"symbol": ticker, "interval": "1m", "adjusted": "true"}

            while pages < 200:
                if before:
                    params["before"] = before  
                resp = requests.get(self._API_BASE, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    raise RuntimeError(f"종목 업데이트 실패 [{resp.status_code}]: {resp.text}")

                result = resp.json()["result"]
                candles = result.get("candles", [])
                before = result.get("nextBefore")

                if not candles:
                    break

                for c in candles:
                    ts = c["timestamp"]
                    if last_ts is not None and ts <= last_ts:
                        reached_existing = True 
                        break
                    new_rows.append((
                        ticker, "1m", ts,
                        float(c["openPrice"]), float(c["highPrice"]),
                        float(c["lowPrice"]), float(c["closePrice"]), float(c['volume'])
                    ))

                pages += 1
                if reached_existing or not before:
                    break
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
                updated[ticker] = inserted

        conn.close()
        return updated


    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        load_dotenv(dotenv_path=os.path.join(self._ROOT, ".env"))
        self._client_id = os.getenv("TOSS_CLIENT_ID")
        self._client_secret = os.getenv("TOSS_CLIENT_SECRET")
        if not self._client_id or not self._client_secret:
            raise RuntimeError("client_key, secret_key 값을 불러올 수 없음")

    def _refresh_token(self):
        if self._is_token_valid(): return
        self._get_access_token()

    def _is_token_valid(self):
        return self._access_token is not None and time.time() <= self._token_expires_at

    def _get_access_token(self):

        if self._is_token_valid():
            return self._access_token

        response = requests.post(
            url=self._TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise RuntimeError(f"토큰 발행 실패. IP 등록 확인 필요[{response.status_code}]")

        body = response.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in", 3600)  # API가 안 주면 1시간으로 가정
        self._token_expires_at = time.time() + expires_in
        if not access_token:
            raise RuntimeError("응답에 access_token이 없음")
        self._access_token = access_token
        return self._access_token



if __name__ == "__main__":
    server = Server()
    print(server.update("005930", "000660"))


