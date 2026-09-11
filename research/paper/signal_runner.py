"""
실시간 시그널 러너 — 시세를 받아 전략을 돌리고, 신호가 나면 HTTP로 쏜다.

    python -m paper.signal_runner EmaCrossStrategy --ticker 005930

전체 흐름:

    Kotlin 서버 ws://localhost:8080/ws  (체결 메시지)
        -> parse_trade()        깨진 프레임은 버린다 (절대 예외를 안 낸다)
        -> MinuteBars           틱을 1분봉으로 누적
        -> 봉이 닫히면 SignalRunner._on_bar_closed
        -> 전략.generate_signals(과거캔들 + 오늘 누적봉)
        -> 마지막 봉의 신호가 1/-1이면
        -> POST http://localhost:8080/api/signals

왜 토스 웹소켓(paper/feed.py의 Feed)에 직접 붙지 않나:
  토스 업스트림은 계정당 동시 연결이 2개뿐이다. Kotlin 서버가 이미 하나를 물고
  있으므로 러너가 또 붙으면 모의투자 앱(paper/app.py)을 같이 띄울 자리가 없다.
  그래서 토스에 붙는 것은 Kotlin 하나로 통일하고, 러너는 Kotlin이 팬아웃해 주는
  로컬 웹소켓에서 체결을 받는다. 덕분에 실시간 경로에서는 토스 토큰이 아예
  필요 없다 (과거 캔들 워밍업은 DB에서 읽으므로 여기도 토큰이 필요 없다).

왜 paper/ 아래인가:
  CLAUDE.md의 의존 방향 규칙 — `paper/`는 `strategies/`와 `data/`를 import해도
  되지만 `backtest/`는 import하지 않는다. 이 러너는 정확히 그 모양이다
  (전략 + 캔들 DB만 쓰고 백테스팅 하네스는 건드리지 않는다). 실시간 시세를
  다루는 코드가 이미 전부 paper/에 있고, 테스트 관례(assert 기반, 네트워크 없음)도
  paper/tests/에 있어서 옆에 두는 편이 찾기 쉽다.

실매매 경계:
  이 파일이 내보내는 HTTP는 localhost의 Kotlin 서버 하나뿐이다. 토스 주문·계좌
  엔드포인트를 부르는 경로는 여기에도 없고, 추가해서도 안 된다.
"""
import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

KST = timezone(timedelta(hours=9))

# Kotlin 서버 기본 주소. 시세(ws)와 신호 전송(POST)이 같은 서버라 --server 하나로 묶었다.
DEFAULT_SERVER = "localhost:8080"

# 재연결 백오프 상한(초). paper/feed.py와 같은 값을 쓴다.
BACKOFF_MAX = 30

# POST 타임아웃(초). 이 호출은 이벤트 루프 위에서 동기로 도므로 넉넉히 잡으면
# 그만큼 시세 읽기가 밀린다. 신호는 하루에 몇 번 수준이라 2초면 충분하다.
POST_TIMEOUT = 2.0

# 전략이 먹는 캔들 스키마. data/candles.py의 load_candles()가 내는 것과 같다.
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

log = logging.getLogger("signal_runner")


# ---------------------------------------------------------------- 메시지 파싱

def parse_trade(raw) -> dict | None:
    """
    Kotlin /ws 프레임 하나를 체결 dict로. 관심 없거나 깨진 프레임은 None.

    절대 예외를 던지지 않는다. paper/feed.py의 parse_event가 같은 규율을 지키는
    이유와 똑같다 — 여기서 예외가 나면 읽기 루프(`async for`) 밖으로 새어나가
    연결이 통째로 끊기고, 끊긴 동안 봉이 안 쌓여 신호가 조용히 사라진다.
    프레임 하나를 버리는 쪽이 압도적으로 싸다.

    모르는 type은 조용히 무시한다. 한 소켓에 orderbook/trade/signal이 섞여 오고
    나중에 종류가 더 늘어도 러너가 안 깨지게 하기 위한 것이다. 우리가 POST한
    신호가 type="signal"로 되돌아오는 것도 이 규칙에 자연히 걸려 버려진다.
    """
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != "trade":
        return None

    try:
        code = msg["stockCode"]
        price = int(msg["price"])
        volume = int(msg.get("volume", 0))
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(code, str) or price <= 0:
        return None

    return {"stockCode": code, "price": price, "volume": volume,
            "timestamp": parse_timestamp(msg.get("timestamp"))}


def parse_timestamp(raw) -> datetime:
    """
    체결 시각을 KST aware datetime으로. 없거나 못 읽으면 '지금'으로 대체한다.

    왜 틱을 버리지 않고 수신 시각으로 대체하나:
      timestamp는 토스가 안 주면 Kotlin이 키를 아예 생략한다. 그런데 우리는 그
      체결을 실시간으로 받고 있으므로 수신 시각은 체결 시각과 1초 안쪽으로 같다.
      반대로 틱을 버리면 그 봉의 거래량·고가·저가가 조용히 틀어진다 — 값이
      틀렸다는 신호조차 없이 전략 입력이 오염되는 쪽이 훨씬 위험하다.
      분봉 경계(정각)에 걸친 틱 몇 개가 옆 봉으로 넘어갈 수 있지만, 그건 원래
      체결 시각과 수신 시각의 차이만큼이고 분봉 단위에서는 무시할 수 있다.
    """
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
            return dt.astimezone(KST) if dt.tzinfo else dt.replace(tzinfo=KST)
        except ValueError:
            pass
    return datetime.now(KST)


# ---------------------------------------------------------------- 틱 -> 분봉

class MinuteBars:
    """
    체결 틱을 1분봉으로 누적한다. 종목 하나당 하나씩 쓴다.

    봉이 닫히는 시점은 '다음 분의 틱이 도착한 순간'이다. 타이머를 돌려 정각에
    닫지 않는 이유: 타이머를 쓰면 거래가 없는 분에도 빈 봉이 생겨 전략 입력에
    없던 봉이 끼고, 이벤트 루프에 타이머 태스크가 하나 더 붙는다. 대신 그날
    마지막 봉은 다음 틱이 안 오면 영영 안 닫힌다 — 장 마감 봉 하나를 못 쓰는
    대가로 구조가 단순해진다. 마감 봉이 꼭 필요해지면 그때 타이머를 붙여라.
    """

    def __init__(self):
        self.closed: list[dict] = []   # 닫힌 봉들 (오래된 것부터)
        self.current: dict | None = None

    def add(self, price: int, volume: int, ts: datetime) -> dict | None:
        """틱 하나를 반영한다. 이 틱 때문에 봉이 닫혔으면 그 봉을, 아니면 None."""
        minute = ts.replace(second=0, microsecond=0)

        if self.current is None:
            self.current = self._open(minute, price, volume)
            return None

        if minute > self.current["timestamp"]:
            done = self.current
            self.closed.append(done)
            self.current = self._open(minute, price, volume)
            return done

        # 같은 분이거나, 순서가 뒤집혀 늦게 도착한 틱. 늦은 틱도 그냥 현재 봉에
        # 합친다 — 이미 닫아 보낸 봉을 되돌려 고칠 방법이 없고, 버리면 거래량이
        # 빈다. 어느 쪽이든 틀리는 자리라 더 단순한 쪽을 골랐다.
        bar = self.current
        bar["high"] = max(bar["high"], price)
        bar["low"] = min(bar["low"], price)
        bar["close"] = price
        bar["volume"] += volume
        return None

    @staticmethod
    def _open(minute: datetime, price: int, volume: int) -> dict:
        return {"timestamp": minute, "open": price, "high": price,
                "low": price, "close": price, "volume": volume}


# ---------------------------------------------------------------- 신호 전송

def build_payload(stock_code: str, side: str, price, strategy: str,
                  timestamp, note: str | None = None) -> dict:
    """
    POST /api/signals 바디를 계약대로 만든다.

    note는 없으면 **키 자체를 뺀다**. null로 보내면 서버가 400을 낸다.
    러너 자신은 note를 채우지 않는다 — 일반적으로 할 말이 strategy 필드의
    반복밖에 없기 때문이다. 인자로 남겨 둔 것은 계약에 있는 필드라서다.

    값 검증을 여기서 하는 이유: 우리가 보내는 쪽 경계다. 종목코드가 6자리가
    아니거나 가격이 0이면 서버는 400만 돌려주고 끝나서, 왜 신호가 안 들어갔는지
    로그를 봐도 알기 어렵다. 만들 때 터뜨리면 스택이 남는다.
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side는 BUY/SELL만 됩니다: {side!r}")
    if not (isinstance(stock_code, str) and len(stock_code) == 6 and stock_code.isdigit()):
        raise ValueError(f"종목코드는 6자리 숫자여야 합니다: {stock_code!r}")
    price = int(price)
    if price <= 0:
        raise ValueError(f"가격은 0보다 커야 합니다: {price}")

    payload = {
        "stockCode": stock_code,
        "side": side,
        "price": price,
        "strategy": strategy,
        "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
    }
    if note:
        payload["note"] = note
    return payload


def post_signal(url: str, payload: dict) -> bool:
    """
    신호를 보낸다. **어떤 실패에도 예외를 내보내지 않는다.**

    서버가 안 떠 있는 것(ConnectionError), 응답이 늦는 것(Timeout), 계약 위반
    (400) 전부 로그만 남기고 False를 돌려준다. 이 함수가 예외를 던지면 그게
    봉 처리 -> 웹소켓 읽기 루프를 타고 올라가 시세 연결을 끊는다. 시세 루프가
    HTTP 실패로 멈추는 것이 이 러너에서 가장 위험한 실패다.
    """
    try:
        resp = requests.post(url, json=payload, timeout=POST_TIMEOUT)
    except Exception as exc:
        # except Exception이 넓은 건 의도적이다. requests는 연결 거부/타임아웃/
        # DNS/프록시를 각기 다른 예외로 내고, 여기서 하나라도 새면 피드가 죽는다.
        log.warning("신호 전송 실패 (%s: %s) — 계속 진행: %s",
                    type(exc).__name__, exc, payload)
        return False

    if resp.status_code != 200:
        log.warning("신호 거부됨 [%s] %s — 계속 진행: %s",
                    resp.status_code, resp.text[:200], payload)
        return False

    log.info("신호 전송 %s %s @%s (%s)",
             payload["stockCode"], payload["side"], payload["price"], payload["strategy"])
    return True


# ---------------------------------------------------------------- 러너

class SignalRunner:
    """
    체결 메시지를 받아 봉을 쌓고, 봉이 닫힐 때마다 전략을 돌려 신호를 쏜다.

    상태는 종목별 MinuteBars와 워밍업용 과거 캔들뿐이다. '지금 보유 중인가'를
    따로 들고 있지 않은 이유: 전략의 generate_signals()가 프레임 전체를 보고
    상태머신(strategies/base.py의 to_signals)을 처음부터 다시 돌리므로, 마지막
    봉의 값이 곧 '이번 봉에서 일어난 사건'이다. 봉 하나를 정확히 한 번씩만
    평가하므로 같은 신호가 두 번 나가지 않는다.
    """

    def __init__(self, strategy, symbols: list[str], api_url: str,
                 history: dict | None = None):
        self.strategy = strategy
        self.name = type(strategy).__name__
        self.api_url = api_url
        self.bars = {s: MinuteBars() for s in symbols}
        self.history = history or {}          # {종목코드: 과거 분봉 DataFrame}

    def handle_message(self, raw) -> None:
        """
        웹소켓 프레임 하나를 처리한다. **예외를 밖으로 내보내지 않는다.**

        전략 코드가 던지는 예외(지표 계산 중 나는 것 등)까지 여기서 막는다.
        전략 하나가 특정 봉에서 터진다고 시세 연결이 끊기면, 그 뒤로는 신호가
        나야 할 봉이 와도 아무 일도 일어나지 않는다.
        """
        try:
            trade = parse_trade(raw)
            if trade is None:
                return
            self._on_trade(trade)
        except Exception:
            log.exception("체결 처리 실패 — 이 프레임만 버리고 계속한다")

    def _on_trade(self, trade: dict) -> None:
        bars = self.bars.get(trade["stockCode"])
        if bars is None:
            return                     # 구독하지 않은 종목. Kotlin이 더 보내도 무시한다.
        closed = bars.add(trade["price"], trade["volume"], trade["timestamp"])
        if closed is not None:
            self._on_bar_closed(trade["stockCode"], closed)

    def _on_bar_closed(self, symbol: str, bar: dict) -> None:
        df = self.frame(symbol)
        signal = int(self.strategy.generate_signals(df).iloc[-1])
        if signal == 0:
            return
        payload = build_payload(
            stock_code=symbol,
            side="BUY" if signal > 0 else "SELL",
            price=bar["close"],
            strategy=self.name,
            timestamp=bar["timestamp"],
        )
        post_signal(self.api_url, payload)

    def frame(self, symbol: str) -> pd.DataFrame:
        """
        전략에 먹일 DataFrame. 과거 캔들 뒤에 오늘 누적한 봉을 이어붙인다.

        매 봉마다 프레임을 통째로 다시 만들고 전략도 처음부터 다시 돈다.
        증분 계산을 하지 않는 이유: 지표는 ewm/rolling이라 앞 구간이 바뀌면
        뒤가 바뀌고, 무엇보다 백테스트와 **같은 코드로 같은 숫자**가 나와야
        한다. 1분에 한 번 수백~수천 행짜리 pandas 연산 한 번은 공짜에 가깝다.
        """
        live = pd.DataFrame(self.bars[symbol].closed, columns=COLUMNS)
        hist = self.history.get(symbol)
        df = live if hist is None or hist.empty else pd.concat([hist, live], ignore_index=True)
        df = df.reset_index(drop=True)
        # 과거 캔들(pandas가 읽은 tz-aware)과 실시간 봉(파이썬 datetime)을 섞으면
        # object dtype이 되어 전략의 시간 기반 조건이 조용히 깨진다. 한 번 정규화한다.
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(KST)
        return df


# ---------------------------------------------------------------- 워밍업

def _db_path() -> str:
    """market_data.db는 저장소 루트(toss/)에 있다. DB.py의 _ROOT와 같은 규칙이다."""
    here = os.path.dirname(os.path.abspath(__file__))            # .../pythonversion/paper
    return os.path.join(os.path.dirname(os.path.dirname(here)), "market_data.db")


def load_warmup(ticker: str, bars: int, db_path: str | None = None) -> pd.DataFrame:
    """
    최근 분봉 bars개를 DB에서 읽어 온다. 없으면 빈 DataFrame.

    왜 워밍업이 필요한가:
      지표 기반 전략은 __init__에서 self.warmup(보통 가장 긴 지표 기간)을 잡고,
      base.to_signals가 그 구간의 신호를 0으로 눌러 버린다. 게다가 EMA는 앞쪽
      값이 시드에 끌려다녀서, 워밍업을 안 주면 장 시작 후 한참 동안 신호가 안
      나거나 더 나쁘게는 '틀린 지표값으로 난' 신호가 나간다. 과거 봉을 앞에
      붙여 두면 첫 실시간 봉부터 백테스트와 같은 지표값 위에서 판단한다.

    왜 DB.load()나 data/candles.py를 안 쓰나:
      - 루트 DB.py의 load()는 timeframe을 안 거른다. 같은 종목에 1d와 1m이
        함께 들어 있어서(현재 1d 33만행 / 1m 100만행) 일봉이 분봉 사이에
        섞여 들어온다.
      - 정리/data/candles.py의 load_candles()는 timeframe을 거르지만 지금
        import 자체가 깨져 있다 (Server.py에 DEFAULT_DB_PATH가 없다).
      둘 다 고치는 건 이 작업의 범위 밖이라, 필요한 질의 한 줄만 여기서 한다.

    최근 bars개를 뽑아야 하므로 DESC LIMIT으로 자른 뒤 다시 ASC로 뒤집는다.
    """
    path = db_path or _db_path()
    if not os.path.exists(path):
        log.warning("캔들 DB가 없어 워밍업 없이 시작한다: %s", path)
        return pd.DataFrame(columns=COLUMNS)

    conn = sqlite3.connect(path)
    try:
        df = pd.read_sql(
            "SELECT timestamp, open, high, low, close, volume FROM ("
            "  SELECT timestamp, open, high, low, close, volume FROM candles"
            "  WHERE ticker = ? AND timeframe = '1m'"
            "  ORDER BY timestamp DESC LIMIT ?"
            ") ORDER BY timestamp ASC",
            conn, params=[ticker, bars])
    except Exception as exc:
        log.warning("워밍업 조회 실패 (%s: %s) — 워밍업 없이 시작한다",
                    type(exc).__name__, exc)
        return pd.DataFrame(columns=COLUMNS)
    finally:
        conn.close()

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


# ---------------------------------------------------------------- 시세 루프

async def consume(runner: SignalRunner, ws_url: str) -> None:
    """
    Kotlin의 /ws에 붙어 체결을 흘려 넣는다. 이 코루틴은 끝나지 않는다.

    Kotlin이 안 떠 있거나 재시작해도 러너는 죽으면 안 되므로, 연결 실패와
    끊김을 전부 같은 자리에서 받아 지수 백오프로 다시 붙는다. paper/feed.py의
    run()과 같은 구조다.
    """
    import websockets            # 실시간 경로에서만 필요하다. 테스트는 이걸 안 탄다.

    backoff = 1
    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                backoff = 1
                log.info("시세 연결됨: %s", ws_url)
                async for raw in ws:
                    runner.handle_message(raw)
        except Exception as exc:
            log.warning("시세 연결 끊김 (%s: %s) — %d초 뒤 재연결",
                        type(exc).__name__, exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX)


# ---------------------------------------------------------------- CLI

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="실시간 시세로 전략을 돌려 신호를 Kotlin 서버에 보낸다")
    parser.add_argument("strategy", help="전략 클래스 이름 (예: EmaCrossStrategy)")
    parser.add_argument("--ticker", nargs="+", required=True, help="종목코드 (여러 개 가능)")
    parser.add_argument("--server", default=DEFAULT_SERVER,
                        help=f"Kotlin 서버 host:port (기본: {DEFAULT_SERVER})")
    parser.add_argument("--warmup", type=int, default=300,
                        help="앞에 붙일 과거 분봉 수 (기본: 300, 0이면 워밍업 없음)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    # 전략을 하드코딩하지 않는다. REGISTRY는 strategies/__init__.py가 하위 패키지를
    # 훑어 자동으로 채운다 (backtest/run.py가 쓰는 것과 같은 경로다).
    from strategies import REGISTRY
    if args.strategy not in REGISTRY:
        parser.error(f"모르는 전략입니다: {args.strategy}\n"
                     f"가능한 전략: {', '.join(sorted(REGISTRY))}")
    strategy = REGISTRY[args.strategy]()

    history = {}
    for ticker in args.ticker:
        df = load_warmup(ticker, args.warmup) if args.warmup > 0 else pd.DataFrame(columns=COLUMNS)
        history[ticker] = df
        # 워밍업이 전략이 요구하는 구간보다 짧으면 초반 신호가 통째로 눌린다.
        # 조용히 '신호가 안 나는' 상태가 되는 자리라 반드시 알린다.
        if len(df) < getattr(strategy, "warmup", 0):
            log.warning("%s 워밍업 %d봉은 %s가 요구하는 %d봉보다 짧다 "
                        "— 초반 신호가 눌릴 수 있다",
                        ticker, len(df), args.strategy, strategy.warmup)
        else:
            log.info("%s 워밍업 %d봉 (마지막 %s)", ticker, len(df),
                     df["timestamp"].iloc[-1] if not df.empty else "-")

    runner = SignalRunner(strategy, args.ticker,
                          api_url=f"http://{args.server}/api/signals",
                          history=history)
    asyncio.run(consume(runner, f"ws://{args.server}/ws"))


if __name__ == "__main__":
    # 윈도우 콘솔은 기본이 cp949라 한국어 로그의 em-dash 같은 문자에서 죽는다.
    # data/candles.py가 같은 이유로 같은 처리를 한다.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    try:
        _main()
    except KeyboardInterrupt:
        print("\n종료")
