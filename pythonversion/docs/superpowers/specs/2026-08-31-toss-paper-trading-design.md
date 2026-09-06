# 토스증권 연동 모의투자 웹사이트 — 설계

작성일: 2026-08-31

## 무엇을 만드는가

토스증권 Open API에서 **실시간 시세를 받아** 브라우저에서 손으로 주문을 넣고,
체결·잔고·손익을 가짜 돈으로 추적하는 로컬 웹사이트.

사용자는 한 명(리포 주인)이고 `localhost`에서만 돈다. 로그인·세션·배포는 없다.

기존 백테스팅 하네스와는 **별개 경로**다. `strategies/`, `run.py`, `results.py`는
건드리지 않는다. 자동매매는 범위 밖이다 — 주문은 사람이 직접 넣는다.

## 안전 경계 (가장 중요)

토스 Open API에는 **모의투자 sandbox 서버가 없다.** OpenAPI 스펙에 서버가
`https://openapi.tossinvest.com` 하나뿐이고, `POST /api/v1/orders`를 부르면
그건 실제 돈이 나가는 진짜 주문이다.

따라서:

- 체결은 **전부 우리 쪽에서 시뮬레이션**한다.
- `toss.py`는 **읽기 전용 엔드포인트만** 노출한다. 주문·계좌 관련 경로를
  감싸는 함수를 만들지 않는다. 이 사실을 파일 최상단 docstring에 못 박는다.
- 코드 어디에도 `/api/v1/orders`, `/api/v1/accounts` 문자열이 등장하지 않는다.

## 확인된 API 사실

실제로 호출해서 확인한 것들이다(문서보다 이쪽이 정확하다).

| 엔드포인트 | 파라미터 | 응답 |
|---|---|---|
| `GET /api/v1/prices` | `symbols=` (**복수**, 배치 가능) | `result[].{symbol, timestamp, lastPrice, currency}` |
| `GET /api/v1/orderbook` | `symbol=` (**단수**, 1종목씩) | `result.{timestamp, currency, asks[10], bids[10]}`, 각 `{price, volume}` |
| `GET /api/v1/stocks` | `symbols=` | `{symbol, name, market, status, koreanMarketDetail.krxTradingSuspended, ...}` |
| `GET /api/v1/market-calendar/KR` | — | `today.integrated.{preMarket, regularMarket, afterMarket}`의 start/end 시각 |
| `GET /api/v1/candles` | 기존 `scrap.py`가 이미 사용 중 | 분봉 |

**모든 숫자 필드는 문자열로 온다.** 파싱 시점에 `Decimal`이나 `int`로 바꾼다.
가격은 원화 정수이므로 `int`, 수량도 `int`다. 부동소수로 다루지 않는다.

장 운영시간(오늘 기준): 장전 08:00–09:00, 정규장 09:00–15:30,
시간외 15:30–20:00.

### 웹소켓

- 주소: `wss://openapi-ws.tossinvest.com/ws/v1`
- 인증: 핸드셰이크에 `Authorization: Bearer <token>` 헤더
- 채널: `trade:kr`, `orderbook:kr` (그 외 `personal:order`는 실계좌용이라 쓰지 않는다)
- 구독은 **선언형 full-replace**. 배열 하나를 보내면 그게 구독 전체가 된다:

```json
[
  {"id": "req-1"},
  {"type": "trade:kr",     "codes": ["005930", "000660"]},
  {"type": "orderbook:kr", "codes": ["005930"]}
]
```

- 이벤트 페이로드:

```json
{"type":"message","topic":"trade:kr:005930",
 "data":{"price":"258500","volume":"12","timestamp":"...","currency":"KRW"}}

{"type":"message","topic":"orderbook:kr:005930",
 "data":{"timestamp":"...","currency":"KRW",
         "asks":[{"price":"259000","volume":"75814"}],
         "bids":[{"price":"258500","volume":"91468"}]}}
```

- keepalive: 순수 텍스트 `PING`(JSON 아님, 대문자)을 60초마다. 서버는 180초
  무수신이면 끊는다. 응답은 `{"type":"pong"}`.
- 한도: **동시 연결 2개/계정**, **연결당 구독 100건**, 선언 5회/초.
  `rate-limit-exceeded`면 1초 대기 후 재선언.
- **구독 직후 스냅샷이 오지 않는다.** 다음 갱신부터 푸시되므로 현재 상태는
  REST(`/prices`, `/orderbook`)로 먼저 채워야 한다.

## 왜 백엔드가 필요한가

브라우저는 토스 WS에 직접 붙을 수 없다. 두 가지 이유가 각각 독립적으로 치명적이다:

1. 핸드셰이크에 `Authorization` 헤더가 필요한데 브라우저 WebSocket API는
   커스텀 헤더를 넣을 수 없다.
2. 넣을 수 있더라도 액세스 토큰이 프론트엔드로 새어 나간다.

그래서 백엔드가 업스트림 연결을 물고 브라우저에 팬아웃한다. 이건 설계
선택이 아니라 제약이다.

연결을 **하나만** 유지하는 이유는 계정당 2개 제한 때문이다. 탭마다 새로
붙이면 탭 3개에서 막힌다.

## 아키텍처

```
브라우저 ──ws──┐
              ├─ FastAPI (uvicorn, 단일 프로세스)
브라우저 ──http─┘        │
                        ├── feed.py   토스 WS 업스트림 1개 (trade:kr, orderbook:kr)
                        │              구독 재선언 · PING 60초 · 백오프 재접속
                        ├── broker.py 체결 엔진 + 포트폴리오  ← 유일한 진실
                        └── toss.py   읽기 전용 REST 래퍼
```

### 파일 배치

```
paper/
  __init__.py
  app.py           FastAPI 앱: REST 라우트, /ws 팬아웃, 시작/종료 훅
  broker.py        체결 엔진 + 포트폴리오 (paper.db). 순수 로직, HTTP 없음
  feed.py          업스트림 WS 클라이언트: 구독 관리, keepalive, 재접속
  toss.py          읽기 전용 REST 래퍼 (prices/orderbook/stocks/market-calendar)
  ticks.py         호가단위 표
  test_broker.py   체결 엔진 검증 (assert 기반, 프레임워크 없음)
  static/index.html
paper.db           SQLite. .gitignore 대상
```

`broker.py`는 네트워크를 모른다. 입력은 "호가 스냅샷"과 "체결 프린트"라는
평범한 값이고 출력은 체결 기록이다. 그래서 테스트가 가짜 데이터만으로 된다.

**토큰 발급은 새로 짜지 않는다.** `scrap.py`의 `_get_access_token()`을
`get_access_token()`으로 이름만 승격하고(호출부 2곳 수정), `paper/toss.py`가
그대로 쓴다. 만료 60초 전 갱신 로직이 이미 들어 있다.

### 새 의존성

`fastapi`, `uvicorn`, `websockets` 3개. 리포에 `requirements.txt`가 없으므로
`CLAUDE.md`의 전역 설치 목록에 추가해 적는다.

프론트엔드 빌드 파이프라인은 만들지 않는다. `index.html` 한 장에 바닐라 JS다.
차트만 CDN `lightweight-charts`를 쓰고, 로딩에 실패하면 **차트만 빠지고 매매는
계속 되게** 한다.

## 데이터 모델 — `paper.db`

테이블 4개다.

```sql
CREATE TABLE account (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    initial_cash INTEGER NOT NULL,   -- 기본 10,000,000원
    created_at   TEXT NOT NULL
);

CREATE TABLE watchlist (
    symbol   TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    symbol      TEXT NOT NULL,
    side        TEXT NOT NULL,   -- 'buy' | 'sell'
    type        TEXT NOT NULL,   -- 'market' | 'limit'
    qty         INTEGER NOT NULL,
    limit_price INTEGER,         -- market이면 NULL
    status      TEXT NOT NULL,   -- 'pending'|'filled'|'partial'|'cancelled'|'expired'
                                 -- pending 외에는 전부 종료 상태
    filled_qty  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE fills (
    id       INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    symbol   TEXT NOT NULL,
    side     TEXT NOT NULL,
    qty      INTEGER NOT NULL,
    price    INTEGER NOT NULL,
    fee      INTEGER NOT NULL,   -- 수수료 (원, 반올림)
    tax      INTEGER NOT NULL,   -- 거래세 (매도만, 원)
    at       TEXT NOT NULL
);
```

관심종목을 별도 테이블로 두는 이유는 서버가 재시작돼도 구독 목록이 남아야
하기 때문이다. 브라우저 `localStorage`에 두면 서버가 무엇을 구독해야 할지
모른 채 뜬다.

`positions`와 `cash` 테이블은 **만들지 않는다.** 보유수량·평균단가·현금을 전부
`fills`에서 파생한다. 테이블로 들고 있으면 체결마다 두 곳을 맞춰야 하고,
어긋나면 잔고가 조용히 틀린다. 거래 수가 수백 건이라 매번 훑어도 비용이 없다.

- 현금 = `initial_cash` − Σ(매수 qty×price + fee) + Σ(매도 qty×price − fee − tax)
- 보유수량 = Σ(매수 qty) − Σ(매도 qty), 종목별
- 평균단가 = 이동평균. 매수 시 갱신, 매도 시 유지(FIFO가 아니라 총평균법)
- **주문가능현금** = 현금 − 미체결 매수주문의 예약금액 Σ(limit_price × 잔량)
  (잔량 = `qty - filled_qty`, `status='pending'`인 매수 지정가만)

예약금액이 없으면 같은 돈으로 지정가 주문을 여러 번 넣을 수 있다.

시장가 매수는 지정가가 없어 예약금액을 계산할 수 없다. 시장가는 **즉시 체결
아니면 즉시 취소**이므로 pending으로 남지 않고, 따라서 예약 대상이 아니다.
대신 주문 접수 시점에 매도호가를 훑어 필요한 현금을 계산해 미리 검증한다.

## 체결 엔진 (`broker.py`)

### 시장가

호가 스냅샷의 반대편을 위에서부터 훑어 **다단 체결**한다. 매수면 `asks`를
1호가부터, 매도면 `bids`를 1호가부터. 각 호가의 `volume`만큼 채우고 다음
호가로 넘어간다.

10호가로 다 못 채우면 채운 만큼만 체결하고 나머지는 버린다. 시장가는
대기하지 않는다.

주문 상태 전이는 이렇다. 시장가는 접수 즉시 종료 상태에 도달하고 `pending`을
거치지 않는다:

| 최종 status | 뜻 |
|---|---|
| `filled` | 전량 체결 |
| `partial` | 일부만 체결되고 종료됨 (시장가가 호가를 소진한 경우) |
| `cancelled` | 사용자가 취소 (지정가만) |
| `expired` | 15:30 자동 만료 (지정가만) |
| `pending` | 대기 중 (지정가만) |

`partial`은 **종료 상태**다. 부분체결된 지정가가 아직 대기 중인 경우는
`pending`으로 남고 `filled_qty`가 0보다 클 뿐이다 — 이 둘을 같은 status로
뭉치면 주문장에서 "아직 체결될 수 있는 주문"을 구분할 수 없다.

### 지정가

주문 접수 시점에 이미 유리하면(매수 지정가 ≥ 매도1호가, 매도 지정가 ≤ 매수1호가)
즉시 호가 기반으로 체결한다. 실제 거래소도 그렇게 동작한다.

아니면 `pending`으로 남는다. 이후 `trade:kr` 이벤트가 올 때마다 판정한다:

- 매수: 프린트 가격 ≤ 지정가 → `min(잔량, 프린트 volume)` 체결
- 매도: 프린트 가격 ≥ 지정가 → `min(잔량, 프린트 volume)` 체결

**체결가는 내 지정가가 아니라 실제 프린트된 가격이다.** 유리한 쪽으로
체결되는 실제 규칙과 맞다.

> `ponytail:` 큐 포지션을 모델링하지 않는다. 내 앞에 줄 서 있던 물량을
> 무시하므로 실제보다 잘 체결된다. 호가 잔량의 변화를 추적하면 개선할 수
> 있지만 이 사이트의 목적을 넘는다.

### 비용

- 매수: 수수료 0.015%
- 매도: 수수료 0.015% + 거래세 0.20%

백테스트가 쓰는 매수 0.015% / 매도 0.215%와 같은 값이되, 매도 쪽을 수수료와
세금으로 **나눠 기록**한다. 지금은 한 덩어리라 명세서에서 세금이 얼마인지
보이지 않는다. 원 단위 반올림한다.

### 장 운영시간

**정규장(09:00–15:30)에서만 체결한다.** 시간외단일가는 10분 단위 단일가
매매라 체결 규칙이 완전히 다르고, 재현하려면 별도 엔진이 필요하다. 1차에서는
장 시간 밖의 주문을 **거부**한다(명확한 에러 메시지와 함께).

장 운영시간은 `/api/v1/market-calendar/KR`에서 받아 하루 한 번 캐시한다.
휴장일도 이걸로 판정한다.

15:30에 미체결 주문 전량을 `expired`로 자동 취소한다.

### 호가단위 검증

지정가가 호가단위에 맞지 않으면 거부한다. 258,500원짜리 종목의 호가단위는
500원이라, 막지 않으면 258,700원처럼 실제로 낼 수 없는 주문이 들어간다.

KRX 가격대별 호가단위 표(`ticks.py`) 하나면 된다.

> `ponytail:` 상·하한가 검증은 넣지 않는다. `/api/v1/price-limits`를 한 번 더
> 불러야 하고, 상한가에 지정가를 거는 건 모의투자에서 해로운 시나리오가 아니다.
> 필요해지면 그 엔드포인트를 추가한다.

## API 표면

```
GET    /api/watchlist          관심종목 + 현재가 (prices 배치 1회)
POST   /api/watchlist          {symbol, action:'add'|'remove'} → 업스트림 재선언
GET    /api/quote?symbol=      호가 10단 + 현재가 스냅샷
GET    /api/candles?symbol=    market_data.db 과거분 + 오늘분
POST   /api/orders             {symbol, side, type, qty, limit_price?}
GET    /api/orders?status=     미체결·체결 내역
DELETE /api/orders/{id}        취소
GET    /api/portfolio          현금, 주문가능현금, 보유, 평가손익
POST   /api/reset              초기자본으로 초기화 (확인 필요)
WS     /ws                     서버 → 브라우저 푸시
```

WS 메시지 종류:

```json
{"type":"trade",     "symbol":"005930", "price":258500, "volume":12, "at":"..."}
{"type":"orderbook", "symbol":"005930", "asks":[...], "bids":[...]}
{"type":"fill",      "order_id":7, "symbol":"005930", "qty":10, "price":258500}
{"type":"portfolio", "cash":..., "available":..., "positions":[...]}
{"type":"feed",      "status":"connected"|"reconnecting"|"error", "message":"..."}
```

### 차트 데이터

새로 짜지 않는다. `market_data.db`가 8/28까지라 오늘 게 없으므로, 종목을 열 때
`scrap.update_candles()`로 최신까지 당기고(증분이라 안전하다) 그 뒤는 실시간
체결을 1분봉으로 접어 이어 그린다.

## 에러 처리

**업스트림이 끊기면 지정가 체결 판정이 멈춘다.** 이걸 조용히 두면 사용자는
체결됐어야 할 주문이 왜 안 됐는지 모른다. 이 설계에서 가장 위험한 조용한
실패다.

- 재접속은 지수 백오프(1s → 2s → 4s → … 최대 30s)
- 끊긴 동안 화면 상단에 **"실시간 연결 끊김 — 지정가 체결 중단됨"** 배너
- 재접속에 성공하면 구독을 다시 선언하고, REST로 현재 상태를 다시 채운다
  (구독 직후 스냅샷이 안 오므로 이 단계가 없으면 화면이 멈춘 값으로 남는다)

그 밖에:

- 토큰 만료 / **IP 미등록**: 구분해서 배너에 표시한다. CLAUDE.md에 IP 미등록
  실패가 잦다고 적혀 있어서 "인증 실패"로 뭉뚱그리면 원인을 못 찾는다.
- `rate-limit-exceeded`: 1초 대기 후 재선언
- `too-many-topics`: 관심종목 추가를 거부하고 이유를 알린다(50종목 상한)
- 주문 거부 사유는 전부 사용자에게 그대로 보여준다(현금 부족, 보유 부족,
  호가단위 위반, 장 시간 밖, 거래정지 종목)

## 테스트

`paper/test_broker.py` 하나. 프레임워크 없이 assert 기반이고, 체결 엔진만
노린다. `broker.py`가 네트워크를 모르므로 가짜 호가·체결 데이터만으로 전부
검증된다.

1. 시장가 매수가 호가를 다단으로 훑어 체결된다
2. 10호가로 부족하면 채운 만큼만 체결하고 잔량은 취소된다
3. 지정가가 `pending`으로 남았다가 체결 프린트로 채워진다
4. 지정가 부분체결 후 잔량이 유지된다
5. 주문 접수 시 이미 유리한 지정가는 즉시 체결된다
6. 현금이 모자라면 주문이 거부된다
7. 미체결 매수의 예약금액이 두 번째 주문을 막는다
8. 보유 수량을 넘는 매도가 거부된다
9. 수수료·거래세가 반영된 현금이 정확하다
10. 취소된 주문은 예약금액에서 빠진다
11. 호가단위에 맞지 않는 지정가가 거부된다
12. 장 시간 밖 주문이 거부된다

`python paper/test_broker.py`로 돌린다.

## 범위 밖 (명시적으로 안 하는 것)

- 실제 주문 전송. sandbox가 없으므로 영구히 범위 밖이다.
- 자동매매 / 전략 연동. `strategies/`는 건드리지 않는다.
- 다중 사용자, 로그인, 배포
- 시간외단일가·장전 시간외 체결
- 미국 주식 (`trade:us`, `orderbook:us`)
- 신용·공매도·조건부 주문
- 상·하한가 검증
