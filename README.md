# toss

토스증권 OpenAPI로 만든 한국 주식 **모의투자(페이퍼 트레이딩) 웹사이트**와, 그 뒤를 받치는 분봉 백테스팅 하네스.

핵심은 `paper/`다. 실시간 시세를 받아 브라우저에서 손으로 주문을 넣고, 체결·잔고·손익을 **가짜 돈**으로 추적한다.

```bash
pip install fastapi uvicorn websockets requests pandas numpy python-dotenv
python -m uvicorn paper.app:app --reload    # http://localhost:8000
```

`.env`에 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`이 필요하다. 토큰은 `scrap.py`가 자동 발급·캐시한다(만료 60초 전 갱신). 401보다 **IP 미등록**으로 막히는 경우가 더 잦으니, 실패하면 토큰부터 의심하지 말고 토스 개발자센터의 허용 IP를 먼저 확인해라.

---

## 모의투자 (`paper/`)

### 실제 돈이 나가지 않는다는 보장

토스 Open API에는 **모의투자 sandbox가 없다.** 서버가 실서버 하나뿐이라 주문 엔드포인트를 부르면 그건 진짜 주문이고 진짜 돈이 나간다.

그래서 이 프로젝트는 경계를 코드 구조로 긋는다:

- `paper/toss.py`는 **읽기 전용 함수만** 노출한다 — 현재가, 호가, 종목정보, 장 캘린더.
- 주문·계좌 경로는 코드 어디에도 등장하지 않는다.
- 체결은 전부 `paper/broker.py`가 로컬에서 시뮬레이션한다.

이 경계를 지키는 점검은 문자열 검색이 아니라 **구조 검사**다: `paper/`에 GET 외의 HTTP 메서드가 없는지, 요청 헬퍼에 `orders`·`accounts` 경로가 인자로 넘어가는 자리가 없는지를 본다. 예전에는 엔드포인트 문자열 자체를 금지했는데, 그러면 "이 엔드포인트를 부르지 마라"는 경고문이 그 문자열을 담을 수 없어 경고가 무력해졌다 — 위험한 것의 이름을 부르지 못하는 경고는 경고가 아니다.

### 구조

```
브라우저 ──/ws──┐
브라우저 ──/ws──┤  app.py (FastAPI)  ──웹소켓 1개──▶  토스 실시간
브라우저 ──/ws──┘     │                              (trade:kr / orderbook:kr)
                      ├─ feed.py    프레임 파싱 · 재접속 · 구독 선언
                      ├─ broker.py  체결 엔진 · 포트폴리오 (paper.db)
                      ├─ ticks.py   KRX 호가단위
                      └─ toss.py    읽기 전용 REST
```

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 서버. REST + `/ws` 팬아웃 + 정적 페이지 |
| `feed.py` | 토스 웹소켓 업스트림 하나를 물고 콜백으로 흘려보낸다 |
| `broker.py` | 체결 엔진과 포트폴리오. **네트워크를 모른다** |
| `ticks.py` | 호가단위 표와 지정가 유효성 |
| `toss.py` | 읽기 전용 REST 래퍼 |
| `static/index.html` | 화면 전부 (토스증권 톤, 빌드 없음) |

`broker.py`가 네트워크를 모르는 게 설계의 중심이다. 입력은 '호가 스냅샷(`Book`)'과 '체결 프린트'라는 평범한 값이고 출력은 체결 기록이라, 테스트가 가짜 데이터만으로 돌아간다.

### 왜 백엔드가 웹소켓을 중계하나

브라우저는 토스 웹소켓에 직접 못 붙는다. 핸드셰이크에 `Authorization` 헤더가 필요한데 브라우저 WebSocket API는 커스텀 헤더를 못 넣고, 넣을 수 있어도 액세스 토큰이 프론트로 샌다. 게다가 **계정당 동시 연결이 2개**라 탭마다 붙이면 3번째 탭에서 막힌다.

그래서 백엔드가 업스트림 하나를 물고 브라우저에는 자체 `/ws`로 팬아웃한다. 구독은 종목당 `trade` + `orderbook` 2건, 연결당 100건 제한이라 **관심종목 최대 50개**다.

구독 선언 프로토콜은 full-replace다. '추가'가 아니라 '지금 구독 전체'를 보내는 거라, 빈 목록을 보내면 전부 해제된다.

### 체결 규칙

| | 동작 |
|---|---|
| **시장가** | 호가를 다단으로 훑고, 소진되면 부분체결로 끝난다. 대기하지 않는다 |
| **지정가** | 지금 이미 유리하면 즉시 체결. 잔량은 `pending`으로 남아 `trade:kr` 프린트를 기다린다 |
| 지정가 체결가 | 내 지정가가 아니라 **프린트된 가격** (유리한 쪽) |
| 거래 시간 | 정규장 09:00~15:30만. 시간외단일가는 체결 규칙이 달라 거부한다 |
| 장 마감 | 미체결 주문을 만료시킨다. 안 하면 어제 지정가가 오늘 시세에 체결된다 |
| 비용 | 수수료 0.015% (양방향) + 거래세 0.20% (매도) |
| 초기자본 | 1,000만원 (`/api/reset`으로 변경 가능) |

**모델링하지 않는 것**: 큐 포지션. 내 앞에 줄 서 있던 물량을 무시하므로 실제보다 잘 체결된다.

**`partial`은 종료 상태다.** 부분체결된 채 아직 대기 중인 지정가는 `pending` + `filled_qty > 0`이다. 이 둘을 뭉치면 주문장에서 '아직 체결될 수 있는 주문'을 못 가린다.

**호가단위를 검증한다.** 258,500원짜리 종목의 호가단위는 100원이라 258,550원 같은 지정가는 실제로 낼 수 없다. 막지 않으면 현실에 존재하지 않는 주문이 체결되고 모의투자 전체가 거짓말이 된다.

**예약금액·체결금액은 수수료까지 포함해 계산한다.** 이걸 빼먹으면 보유 현금을 정확히 다 쓰는 주문이 검증을 통과하고 잔고를 마이너스로 만든다.

### 상태는 `fills`에서 파생한다

현금·보유수량·평균단가를 따로 저장하지 않는다. 전부 `paper.db`의 `fills`를 훑어 계산한다. 테이블로 들고 있으면 체결마다 두 곳을 맞춰야 하고, 어긋나면 잔고가 **조용히** 틀린다. 거래 수가 수백 건 수준이라 매번 훑어도 비용이 없다.

### 알아 둘 실패 모드

- **업스트림이 끊기면 지정가 체결 판정이 멈춘다.** 이 설계에서 가장 위험한 조용한 실패라, 화면 상단에 빨간 배너를 띄운다. `feed_status`는 오직 실시간 피드만 뜻한다 — 캔들 수집이나 장 캘린더 조회 실패로 이걸 덮으면 피드는 멀쩡한데 화면만 끊긴 것처럼 보인다.
- **`parse_event`는 절대 예외를 던지지 않는다.** 깨진 프레임은 전부 `None`. 여기서 예외가 나면 웹소켓 읽기 루프 밖으로 새어 연결이 끊긴다. 프레임 하나 버리는 쪽이 훨씬 싸다.
- **`tz_now()`는 절대 네트워크를 타면 안 된다.** 이전 버전은 여기서 장 캘린더 API를 불렀는데, 체결 프린트마다(이벤트 루프 위에서) 불리다 보니 API 실패 한 번이 웹소켓 루프를 끊고, 재접속마다 같은 자리에서 또 죽어 피드가 영영 안 살아나는 무한루프가 됐다.
- **`broker_lock`이 브로커 변경을 전부 직렬화한다.** FastAPI는 동기 핸들러를 워커 스레드에서 돌리고 피드 콜백은 이벤트 루프에서 도는데, 둘 다 같은 SQLite 커넥션과 같은 주문 행을 만진다. 락을 문 채로 네트워크를 타면 안 된다 — 그 요청이 끝날 때까지 피드 콜백이 전부 멈춘다.
- **`on_trade`의 조회는 `limit_price IS NOT NULL`을 반드시 건다.** 시장가 주문도 스윕 전에는 `pending`으로 커밋돼 있고 그 행의 지정가는 NULL이라, 안 거르면 `None`과 가격을 비교하다 피드가 죽는다.

### API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/watchlist` | 관심종목 + 종목명 |
| POST | `/api/watchlist` | `{symbol, action: add\|remove}` |
| GET | `/api/quote?symbol=` | 현재가 + 호가 10단 |
| GET | `/api/candles?symbol=&interval=1m` | 차트용 분봉 (최근 500봉) |
| POST | `/api/orders` | `{symbol, side, type, qty, limit_price?}` |
| GET | `/api/orders?status=` | 주문 조회 |
| DELETE | `/api/orders/{id}` | 취소 |
| GET | `/api/portfolio` | 현금·주문가능·예약·보유 |
| POST | `/api/reset` | 계좌 초기화 |
| GET | `/api/status` | 피드 상태 |
| WS | `/ws` | `trade` · `orderbook` · `fill` · `expired` · `portfolio` · `feed` |

### 테스트

```bash
python paper/test_broker.py   # 체결 엔진
python paper/test_ticks.py    # 호가단위
python paper/test_toss.py     # REST 응답 파싱
python paper/test_feed.py     # 웹소켓 프레임 파싱
```

프레임워크 없이 assert 기반이고, 전부 네트워크 없이 돈다.

---

## 백테스팅 하네스

같은 리포에 분봉 백테스팅이 들어 있다. 모의투자와는 **완전히 별개 경로**다 — `paper/`는 `strategies/`·`run.py`·`results.py`를 건드리지 않는다.

```bash
python scrap.py 005930 000660 --interval 1m      # 캔들 수집 → market_data.db
python run.py EmaCrossStrategy --ticker 005930 --optimize --plot
python run.py --all --ticker 005930              # 전략 × 종목 순위표
python results.py                                # 전 전략 × KOSPI50 증분 평가
```

```
load_candles → walk_forward_split(70/30) → Strategy.generate_signals
             → run_backtest → metrics / 리포트
```

전략은 `strategies/<카테고리>/<파일>.py`에 클래스만 만들면 자동 등록된다. 현재 41개(추세추종/평균회귀/모멘텀/변동성/세션기반)가 등록돼 있고 전부 롱 온리다.

자세한 계약과 함정은 `CLAUDE.md`에 있다.

## 데이터

- `market_data.db` — 캔들. `INSERT OR IGNORE` 증분 수집이라 재실행해도 안전하다. gitignore 대상.
- `paper.db` — 모의투자 주문·체결.
- `results.db`, `results/` — 백테스트 결과 캐시. gitignore 대상.
