# `paper/app.py`를 읽기 위한 배경지식과 코드 해설

이 문서는 두 부분이다.

- **1부 배경지식** — 비동기, 스레드, 락, TCP·HTTP·웹소켓, ack, 그리고 주식 호가의 최소 개념.
  코드를 한 줄도 안 보고 읽을 수 있게 썼다.
- **2부 코드 해설** — 위 개념이 `paper/app.py`의 어느 줄에서 왜 그렇게 생겼는지.

1부를 건너뛰고 2부부터 읽어도 되지만, 2부에서 "이건 1부 X절"이라고 되짚는 자리가 많다.

---

# 1부. 배경지식

## 1.1 이 서버가 동시에 하는 일

먼저 왜 어려운 얘기가 필요한지부터 보자. 이 프로그램은 파이썬 프로세스 **하나**인데,
그 안에서 아래 일들이 *동시에* 벌어진다.

1. 토스 서버와 웹소켓 연결을 유지하면서, 초당 수십~수백 건씩 날아오는 체결·호가 데이터를 받는다.
2. 60초마다 한 번씩 "지금 장 마감했나?"를 확인한다.
3. 브라우저가 `주문 넣어줘` HTTP 요청을 보내면 처리한다.
4. 브라우저로 연결된 웹소켓들에 갱신 내용을 밀어 넣는다.

"동시에"가 문제다. 보통 배우는 프로그램은 `input()` 받고 → 계산하고 → `print()` 하는
**한 줄기 흐름**이다. 위 네 가지는 서로를 기다려 주지 않는다. 2번이 API 응답을 10초
기다리는 동안 1번 데이터가 계속 쏟아지고, 그 사이에 3번 요청이 들어온다.

한 줄기 흐름으로 이걸 처리하는 방법이 두 가지 있고, 이 서버는 **둘 다** 쓴다.
그래서 코드가 암호처럼 보인다. 하나씩 보자.

## 1.2 블로킹 — 모든 문제의 출발점

```python
resp = requests.get("https://openapi.tossinvest.com/api/v1/prices", timeout=10)
```

이 한 줄이 실행되는 동안, 이 줄을 실행한 흐름은 **완전히 멈춰 있다**. 네트워크로 요청을
보내고, 서버가 답할 때까지 아무것도 못 한다. 0.3초일 수도 있고, 서버가 죽어 있으면
`timeout=10`이 걸릴 때까지 10초일 수도 있다.

이걸 **블로킹(blocking)**이라고 한다. CPU가 바쁜 게 아니다. CPU는 놀고 있고, 그냥
"답 올 때까지 대기" 상태로 붙잡혀 있는 것이다. 파일 읽기, 네트워크 요청, `sleep`,
DB 조회가 전부 블로킹이다.

컴퓨터가 느린 이유의 대부분은 계산이 아니라 이 대기다. 그래서 "대기하는 동안 다른 일을
하게 만드는" 두 가지 기법이 나온다.

## 1.3 방법 A: 스레드 (thread)

**스레드**는 같은 프로그램(메모리를 공유하는 상태) 안에서 독립적으로 돌아가는 실행 흐름이다.
흐름이 여러 개니까, 하나가 `requests.get`에서 멈춰 있어도 다른 하나는 계속 돈다.
OS가 알아서 흐름들을 번갈아 CPU에 올려 준다.

```python
import threading
t = threading.Thread(target=오래_걸리는_일)
t.start()      # 여기서 안 기다린다. 다음 줄로 바로 넘어간다.
print("나는 먼저 찍힌다")
```

장점은 **기존 코드를 그대로 쓸 수 있다**는 것. `requests.get`을 그냥 부르면 된다.
단점은 두 가지다.

**단점 1: 비싸다.** 스레드 하나당 메모리(보통 8MB 스택)와 OS 자원을 잡아먹는다.
동시 접속 1만 명에게 스레드 1만 개를 줄 수는 없다.

**단점 2: 경쟁 상태(race condition).** 이게 진짜 문제다.

### 경쟁 상태와 락

두 스레드가 같은 데이터를 건드리면 이런 일이 난다. 잔고가 100만 원이고, 두 개의
주문이 동시에 들어왔다고 하자.

```
스레드 A                        스레드 B
잔고 읽기 → 100만               |
                                잔고 읽기 → 100만
80만 짜리 주문 가능? → 예       |
                                80만 짜리 주문 가능? → 예
잔고 쓰기 → 20만                |
                                잔고 쓰기 → 20만
```

80만 원짜리 주문이 두 개 체결됐는데 잔고는 20만 원이다. 40만 원이 어디선가 생겼다.
각 스레드는 자기 관점에서 완벽하게 옳게 동작했다. 문제는 "읽고 → 판단하고 → 쓰는"
사이에 다른 스레드가 끼어들었다는 것이다.

해결책이 **락(lock, 자물쇠)**이다.

```python
lock = threading.Lock()

with lock:            # 이 블록에 들어갈 수 있는 스레드는 한 번에 하나
    잔고_읽기()
    검증()
    잔고_쓰기()
```

한 스레드가 락을 잡고 있으면 다른 스레드는 `with lock:` 줄에서 **블로킹**되어 기다린다.
앞 스레드가 블록을 빠져나가며 락을 놓으면 그때 들어간다. 이제 "읽고-판단하고-쓰는"
과정이 통으로 원자적(atomic)이 된다.

여기서 아주 중요한 규칙 하나가 나온다.

> **락을 잡은 채로 느린 일(네트워크 요청)을 하면 안 된다.**

락은 다른 모두를 세워 놓는 물건이다. 락 안에서 10초짜리 API 호출을 하면 그 10초 동안
이 락을 쓰려는 모든 흐름이 정지한다. 이 규칙은 2부에서 `api_place`가 왜 그렇게
생겼는지 설명할 때 그대로 나온다.

## 1.4 방법 B: 비동기 (async / 이벤트 루프)

스레드가 "흐름을 여러 개 만든다"였다면, 비동기는 **흐름은 하나인데, 대기가 생길 때마다
다른 일로 갈아탄다**이다.

식당 종업원으로 비유하면 이렇다. 스레드 방식은 손님 테이블마다 종업원을 한 명씩 붙이는
것이다. 비동기 방식은 종업원 한 명이 1번 테이블 주문을 받아 주방에 넣고, 음식이 나올
때까지 서 있지 않고 바로 2번 테이블로 가고, 주방에서 "나왔어요" 하면 그때 1번으로
돌아가는 것이다. 종업원은 **한 명**인데 테이블 20개를 처리한다. 그가 절대 하면 안 되는
일은 한 테이블 앞에서 멍하니 서 있는 것이다.

이 종업원이 **이벤트 루프(event loop)**다. 파이썬에서는 `asyncio`가 제공한다.

### 문법

```python
async def 가격_가져오기():          # async def = 코루틴 함수
    data = await 네트워크_요청()     # await = "여기서 대기가 생긴다. 다른 일 하고 와라"
    return data
```

- `async def`로 정의한 함수를 **코루틴(coroutine)**이라고 한다. 그냥 부르면 실행되지
  않고 "실행 계획서" 객체만 만들어진다. 실행하려면 `await`를 붙이거나 이벤트 루프에
  넘겨야 한다.
- `await`는 **양보 지점**이다. "나 여기서 기다려야 하니까, 루프야 그동안 다른 코루틴
  돌려. 준비되면 나 여기서부터 다시 시작시켜 줘."

`await`가 붙은 지점에서만 다른 일로 넘어간다. 이게 스레드와의 결정적 차이다.
스레드는 OS가 **아무 때나** 흐름을 바꾼다(그래서 1.3의 경쟁 상태가 난다). 비동기는
`await`가 없는 구간에서는 절대 끊기지 않는다. 그래서 비동기 코드끼리는 락이 훨씬 덜 필요하다.

### 태스크 (Task)

여러 코루틴을 동시에 돌리려면 루프에 등록해야 한다.

```python
task = asyncio.create_task(가격_가져오기())   # 등록만 하고 즉시 다음 줄로
```

이게 "주방에 주문 넣기"다. 결과를 기다리지 않는다.

> **함정:** CPython은 실행 중인 Task를 약한 참조(weak reference)로만 들고 있다.
> 반환값을 변수에 안 담아 두면, 파이썬의 가비지 컬렉터가 "아무도 안 쓰는 객체네"
> 하고 **실행 도중에 수거**해 버릴 수 있다. 태스크가 아무 에러도 없이 조용히
> 사라진다. 그래서 실전 코드는 태스크를 집합(set)에 담아 붙잡아 둔다.
> `app.py`의 `background_tasks`와 `spawn()`이 정확히 이 문제 때문에 있다.

### 비동기의 치명적 규칙

> **이벤트 루프 위에서 블로킹 코드를 부르면 서버 전체가 멈춘다.**

종업원 한 명이 한 테이블 앞에서 10초 서 있으면 식당 전체가 10초 멈춘다. `async def`
안에서 `requests.get(timeout=10)`이나 `time.sleep(5)`를 부르면 그 시간 동안 웹소켓
수신도, 다른 요청 처리도, 전부 정지한다.

이럴 때 쓰는 탈출구가 있다.

```python
결과 = await asyncio.to_thread(블로킹_함수)   # 이 함수만 별도 스레드로 빼서 실행
```

블로킹 함수를 스레드풀에 던지고, 그동안 루프는 다른 일을 한다. 끝나면 결과를 받아
이어서 실행한다. 2부의 `expire_at_close`가 이걸 쓴다.

### 두 세계를 잇는 다리

이 서버는 스레드와 이벤트 루프를 둘 다 쓴다. 그러면 **스레드에서 이벤트 루프에 일을
시켜야 하는** 순간이 온다. 이때 `asyncio.create_task`를 그냥 부르면 안 된다.
그 함수는 "지금 이 흐름이 이벤트 루프 위"라는 전제를 깔고 있어서, 일반 스레드에서
부르면 `RuntimeError: no running event loop`로 죽는다.

정답은 이거다.

```python
loop.call_soon_threadsafe(함수, 인자)
```

이름 그대로 **스레드 안전(thread-safe)**하다. 어느 스레드에서 불러도 되고, 이벤트 루프
쪽에 "이 함수 좀 실행해 줘"라고 안전하게 쪽지를 남긴다. 루프는 자기 차례가 되면 그걸
꺼내 실행한다. 2부의 `broadcast()`가 이 함수 하나로 만들어져 있다.

## 1.5 네트워크: 패킷, TCP, ack

인터넷으로 데이터를 보낼 때 통째로 가지 않는다. **패킷**이라는 작은 조각으로 쪼개져
각자 여러 라우터를 거쳐 간다. 이 과정에서 패킷은 유실되거나, 순서가 뒤바뀌거나,
중복 도착할 수 있다. 네트워크는 기본적으로 신뢰할 수 없는 물건이다.

**TCP**는 그 위에 신뢰성을 얹는 규약이다. 핵심 장치가 **ack(acknowledgement, 수신 확인
응답)**다.

```
보내는 쪽                    받는 쪽
패킷 #1 전송  ──────────────▶  받음
             ◀────────────── "1번 잘 받았음" (ack)
패킷 #2 전송  ──────────────▶  (유실)
             (ack가 안 온다)
   ... 일정 시간 대기 후 ...
패킷 #2 재전송 ─────────────▶  받음
             ◀────────────── "2번 잘 받았음" (ack)
```

받는 쪽이 ack를 보내고, 보내는 쪽은 ack가 안 오면 다시 보낸다. 순서 번호가 붙어 있어서
받는 쪽이 순서도 맞춰 준다. 그래서 TCP 위에서 프로그램을 짜는 사람은 "보낸 건 순서대로
도착한다"고 가정할 수 있다. HTTP도 웹소켓도 전부 TCP 위에서 돈다.

**여기서 중요한 오해 하나를 짚고 가자.** ack가 보장하는 건 "**연결이 살아 있는 동안**
보낸 데이터가 순서대로 도착한다"까지다. 연결이 **끊기면** 그 보장은 거기서 끝난다.
끊긴 동안 상대가 보내려던 데이터는 그냥 사라지고, 다시 연결해도 자동으로 채워 주지 않는다.

이 서버가 딱 그 상황에 놓인다. 토스 웹소켓이 30초 끊겨 있었으면, 그 30초 동안의 체결
데이터는 **영영 안 온다**. 이 서버는 그 체결 데이터로 지정가 주문의 체결 여부를
판정하므로, 끊긴 30초 동안 체결됐어야 할 주문이 체결 안 된 채로 남는다. 복구 방법이
없다. 그래서 코드가 할 수 있는 최선은 **끊겼다는 사실을 사용자에게 크게 알리는 것**이고,
실제로 화면 상단에 빨간 배너를 띄운다.

## 1.6 HTTP와 REST — 요청이 있어야 답이 있다

**HTTP**는 웹의 기본 통신 방식이고, 규칙이 하나다: **클라이언트가 요청하면 서버가 한 번
답하고 끝.** 서버가 먼저 말을 걸 수 없다.

요청은 이렇게 생겼다.

```
GET /api/v1/prices?symbols=005930 HTTP/1.1        ← 메서드 + 경로 + 쿼리
Authorization: Bearer eyJhbGci...                 ← 헤더
```

- **메서드**: `GET`(조회), `POST`(생성), `DELETE`(삭제). 관례이자 의미다.
  `paper/toss.py`가 `GET`만 쓰는 건 "토스에 절대 주문을 넣지 않는다"는 안전 경계를
  구조로 못 박은 것이다.
- **헤더**: 본문과 별개로 붙는 메타데이터. `Authorization: Bearer <토큰>`이 "나 이런
  사람이야"를 증명하는 자리다.
- **토큰**: ID/비밀번호를 매번 보내지 않으려고, 한 번 인증하고 받아 두는 임시 출입증.
  유효기간이 있어서 `data/auth.py`가 만료 60초 전에 자동 갱신한다.

**REST API**는 이 HTTP를 "자원(URL)에 메서드를 적용한다"는 규칙으로 정리한 스타일이다.
`GET /api/orders`는 주문 목록 조회, `POST /api/orders`는 주문 생성, `DELETE /api/orders/3`은
3번 주문 취소. 이 서버의 `/api/*` 엔드포인트들이 전부 이 형태다.

## 1.7 웹소켓 — 서버가 먼저 말을 걸어야 할 때

HTTP로는 "주가가 바뀌면 알려 줘"를 할 수 없다. 서버가 먼저 말을 못 거니까. 그래서
예전엔 **폴링(polling)**을 했다. 1초마다 "바뀐 거 있어?"를 계속 물어보는 것이다.
1초에 한 번씩 연결을 새로 맺고, 헤더를 다 붙여 보내고, 대부분 "없는데?" 답을 받는다.
초당 수십 건 체결되는 주식 시세에는 느리고 낭비다.

**웹소켓(WebSocket)**은 이걸 해결한다. 처음 한 번만 HTTP로 접속한 뒤 "이 연결을 웹소켓으로
승격시켜 줘"라고 요청하고(**핸드셰이크**), 서버가 수락하면 그 TCP 연결이 계속 열린 채로
남는다. 이후로는 **양쪽 다 아무 때나 메시지를 보낼 수 있다.**

```
HTTP:      요청 → 응답 (끝). 요청 → 응답 (끝). 요청 → 응답 (끝).
WebSocket: 핸드셰이크 → [연결 유지] ←→ ←→ ←→ ←→ ... (계속)
```

### 이 서버에서 웹소켓이 두 겹인 이유

```
토스 서버  ══[웹소켓 #1]══▶  이 서버  ══[웹소켓 #2]══▶  브라우저
```

브라우저가 토스에 직접 붙으면 될 것 같은데, 안 되는 이유가 두 개다.

1. **핸드셰이크에 `Authorization` 헤더가 필요한데, 브라우저의 WebSocket API는 커스텀
   헤더를 넣을 수 없다.** 자바스크립트 `new WebSocket(url)`에는 헤더를 넣는 인자가 아예 없다.
2. 넣을 수 있다 해도 **액세스 토큰이 프론트엔드로 새어 나간다.** 브라우저에 내려간 값은
   사용자가 개발자도구로 다 볼 수 있다. 토큰이 유출되면 남이 내 계정으로 API를 부른다.

여기에 더해 **계정당 동시 연결이 2개로 제한**된다. 브라우저 탭마다 붙이면 탭 3개에서 막힌다.

그래서 백엔드가 토스 쪽 연결 **하나**만 물고, 받은 걸 브라우저 여러 개에 복사해서
뿌린다. 이 "하나로 받아서 여럿에게 뿌리기"를 **팬아웃(fan-out)**이라고 하고,
`app.py`의 `broadcast()` / `_fanout()`이 그 일을 한다.

### keepalive (핑)

연결을 열어만 두면 아무 데이터도 안 흐르는 구간이 생긴다. 중간의 방화벽이나 NAT 장비는
"조용한 연결 = 죽은 연결"로 보고 임의로 끊어 버린다. 서버도 마찬가지 정책을 둔다.
토스는 **180초 동안 아무것도 안 오면 끊는다.**

그래서 주기적으로 의미 없는 신호를 보낸다. 이게 **keepalive** 또는 **핑(ping)**이다.
`paper/feed.py`는 60초마다 순수 텍스트 `PING`을 보낸다(JSON으로 감싸면 토스 서버가
못 알아듣는다). 180초 제한에 60초 간격이니 두 번 연속 실패해도 여유가 있다.

### 지수 백오프 (exponential backoff)

연결이 끊기면 다시 붙어야 한다. 그런데 즉시, 계속 재시도하면 안 된다. 서버가 장애로
죽어 있는 상황이라면 수많은 클라이언트가 초당 수백 번씩 재접속을 시도해 서버를 더
못 일어나게 만든다.

그래서 **실패할 때마다 대기 시간을 두 배로 늘린다**: 1초 → 2초 → 4초 → 8초 → ... → 상한.
`feed.py`가 `backoff = min(backoff * 2, BACKOFF_MAX)`로 이걸 한다. 성공하면 1초로 되돌린다.

## 1.8 주식 시장의 최소 개념

코드를 읽으려면 이 네 가지는 알아야 한다.

### 호가창 (orderbook)

지금 시장에 걸려 있는 **아직 체결 안 된 주문들**의 목록이다.

```
        매도호가(asks)  ← 팔겠다는 사람들. 싼 가격부터.
        71,000원   300주
        70,900원   150주
        70,800원   200주   ← 지금 사려면 여기부터 먹는다
    ─────────────────────
        70,700원   180주   ← 지금 팔면 여기부터 먹는다
        70,600원   400주
        70,500원   250주
        매수호가(bids)  ← 사겠다는 사람들. 비싼 가격부터.
```

`Book(asks=[...], bids=[...])`이 이 스냅샷이고, `Level(price, volume)`이 한 줄이다.

### 시장가 주문 (market order)

"가격 상관없이 지금 당장 사/팔아 줘." 위 호가창에서 500주를 시장가로 사면
70,800원에 200주 + 70,900원에 150주 + 71,000원에 150주 이렇게 **위에서부터 훑어 내려가며**
체결된다. 이걸 코드에서는 **스윕(sweep)**이라 부르고 `broker._sweep()`이 한다.

호가 물량이 다 떨어지면? 이 서버는 거기서 **부분체결로 끝낸다**(기다리지 않는다).

### 지정가 주문 (limit order)

"70,000원 이하면 사 줘. 아니면 기다려." 지금 시세가 70,800원이면 즉시 체결되지 않고
`pending`(대기) 상태로 남는다. 그리고 **가격이 내려와서 실제로 70,000원 이하에 거래가
체결되는 것을 목격하면** 그때 내 주문도 체결된 것으로 친다.

여기서 필요한 게 다음 개념이다.

### 체결 프린트 (trade print)

"방금 이 종목이 70,000원에 300주 거래됐다"는 **사실 통보**다. 주문이 아니라 이미 일어난
일의 기록이다. 토스 웹소켓의 `trade:kr` 채널이 이걸 보낸다.

이 서버의 지정가 체결 규칙은 이 프린트에 전적으로 의존한다. `broker.on_trade()`가
프린트를 받을 때마다 "이 가격이면 채워질 수 있는 대기 주문이 있나?"를 검사한다.
**여기가 지정가가 체결되는 유일한 경로다.** 그래서 1.5에서 말한 "연결이 끊기면 그 동안의
데이터는 영영 안 온다"가 이 서버에서 가장 위험한 고장이 된다.

### 호가단위 (tick size)

주식 가격은 아무 숫자나 못 낸다. 가격대별로 정해진 단위가 있다. 258,500원짜리 종목의
호가단위는 100원이라 258,550원짜리 주문은 **현실에 존재할 수 없다**. 막지 않으면
현실에 없는 주문이 주문장에 들어가고, 그게 체결되는 순간 모의투자 전체가 거짓말이 된다.
`paper/ticks.py`가 이 표를 들고 있다.

---

# 2부. 코드 해설

## 2.1 전체 그림

```
      ┌──────────────────────────────────────────────────────────┐
      │  토스 서버 (openapi.tossinvest.com)                      │
      └────────┬──────────────────────────────┬──────────────────┘
               │ 웹소켓 (밀어 넣기)           │ REST (물어보기)
               │ 체결·호가 스트림             │ 현재가, 호가, 장 시간
               ▼                              ▼
      ┌──────────────────────────────────────────────────────────┐
      │  paper/feed.py           paper/toss.py                   │
      │  연결 유지·재접속·파싱   읽기 전용 GET 래퍼              │
      └────────┬─────────────────────────────┬───────────────────┘
               │ 콜백 (이벤트 루프 위)       │ 함수 호출 (블로킹)
               ▼                             ▼
      ┌──────────────────────────────────────────────────────────┐
      │  paper/app.py     ◀── 이 문서의 주제                     │
      │  ├ 상태: books, last_price, feed_status, clients          │
      │  ├ broker_lock: 브로커 변경을 전부 직렬화                 │
      │  ├ broadcast(): 스레드/루프 어디서든 브라우저에 팬아웃    │
      │  └ REST 엔드포인트 + /ws 엔드포인트                       │
      └────────┬─────────────────────────────┬───────────────────┘
               │ 주문·체결 판정              │ 웹소켓 팬아웃
               ▼                             ▼
      ┌────────────────────────┐   ┌──────────────────────────┐
      │  paper/broker.py       │   │  브라우저 (index.html)   │
      │  체결 엔진 + 잔고      │   │  여러 탭 가능            │
      │  네트워크를 모른다     │   └──────────────────────────┘
      │  상태는 paper.db fills │
      └────────────────────────┘
```

핵심 분업:

- **`feed.py`** — 연결 유지만 책임진다. 데이터를 판단하지 않고 콜백으로 넘긴다.
- **`toss.py`** — HTTP 조회만. **`GET` 외의 메서드가 없다**(주문 안전 경계).
- **`broker.py`** — 네트워크를 전혀 모른다. 입력은 `Book`과 체결 프린트라는 평범한 값,
  출력은 체결 기록. 그래서 테스트가 가짜 데이터만으로 돈다.
- **`app.py`** — 위 셋을 붙이고, **동시성을 혼자 감당한다.** 그래서 어려운 코드가 전부 여기 몰려 있다.

## 2.2 `app.py`에는 두 종류의 흐름이 산다

이게 이 파일을 읽는 열쇠다. 코드는 한 파일에 있지만 **실행되는 세계가 두 개**다.

| | 이벤트 루프 위 (1.4) | 워커 스레드 위 (1.3) |
|---|---|---|
| 누가 | `feed.run()`, `on_trade`, `on_orderbook`, `on_status`, `expire_at_close`, `/ws` 핸들러, `async def` 엔드포인트 | 평범한 `def`로 쓴 REST 엔드포인트 전부 (`api_place`, `api_cancel`, `api_watchlist`, ...) |
| 왜 | 웹소켓은 본질적으로 비동기 | **FastAPI가 `def` 핸들러를 스레드풀에 넘긴다** |
| 금지 | 블로킹 호출 (서버 전체가 멈춘다) | `asyncio.create_task` (루프가 없어서 `RuntimeError`) |

**FastAPI의 이 규칙을 꼭 기억하자.**

- `async def` 엔드포인트 → **이벤트 루프 위**에서 직접 실행. 여기서 블로킹하면 서버 전체 정지.
- 평범한 `def` 엔드포인트 → **워커 스레드**로 넘겨 실행. 블로킹해도 안전하지만, 루프가 없다.

이 설계는 친절하다. `requests` 같은 블로킹 라이브러리를 쓰는 핸들러는 `def`로 쓰면
알아서 안전해진다. 대신 그 핸들러는 이제 다른 스레드에 있으므로, **공유 상태를 만지면
락이 필요하고**(1.3), **이벤트 루프에 일을 시키려면 `call_soon_threadsafe`가 필요하다**(1.4).

`app.py`의 어려운 코드는 거의 전부 이 두 문장의 결과다.

## 2.3 전역 상태들

```python
broker = Broker(DB_PATH)
broker_lock = threading.Lock()

books: dict[str, Book] = {}          # 종목별 최신 호가 스냅샷
book_fetched_at: dict[str, float] = {}
BOOK_MAX_AGE = 3.0
last_price: dict[str, int] = {}      # 종목별 마지막 체결가
session_cache: dict = {...}          # 오늘의 장 시간 (하루 한 번만 조회)
feed_status = {"status": "starting", "message": ""}

clients: set[WebSocket] = set()      # 붙어 있는 브라우저들
loop: asyncio.AbstractEventLoop | None = None
background_tasks: set[asyncio.Task] = set()
```

`books`와 `last_price`가 **캐시**인 게 핵심이다. 시장가 주문이 들어올 때마다 토스에
호가를 물어보면 매번 수백 밀리초가 든다. 웹소켓으로 이미 실시간으로 받고 있으니
받은 값을 여기에 덮어 쓰고, 주문 시에는 이걸 읽는다.

`loop`가 전역인 이유는 1.4의 다리 때문이다. 워커 스레드에서 `broadcast()`를 부를 때
"어느 루프에 쪽지를 남길지"를 알아야 하는데, 스레드에서는 루프를 찾을 방법이 없다.
그래서 `startup`에서 한 번 잡아 전역에 박아 둔다.

`MARKET_DB_PATH`가 절대경로인 이유도 실제로 물린 적 있는 함정이다.
`data.candles`의 기본값은 상대경로라, 서버를 다른 작업 디렉터리에서 띄우면 기존 14MB
DB를 못 찾고 **빈 DB를 새로 만들어 버린다**. 에러 없이, 그냥 차트가 비어 보인다.

## 2.4 `spawn()` — 태스크를 흘리지 않기

```python
def spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task
```

1.4의 "약한 참조" 함정 대응이다. `create_task`의 반환값을 안 붙잡으면 GC가 실행 중인
태스크를 수거해 조용히 멈출 수 있다.

- `background_tasks.add(task)` — 강한 참조를 만들어 GC를 막는다.
- `add_done_callback(background_tasks.discard)` — 끝나면 스스로 집합에서 빠진다.
  안 하면 집합이 무한히 커진다(메모리 누수).

세 줄짜리 관용구지만, 없으면 재현도 안 되는 유령 버그가 난다.

## 2.5 `broadcast()` — 두 세계를 잇는 다리

```python
def broadcast(payload: dict) -> None:
    if loop is None:
        return
    loop.call_soon_threadsafe(spawn, _fanout(payload))
```

세 줄인데 여기에 1.4의 다리가 통째로 들어 있다. `broadcast`를 부르는 쪽이 두 종류다.

- `on_trade`, `on_orderbook`, `on_status` — 웹소켓 수신 루프 안, 즉 **이벤트 루프 위**
- `api_place`, `api_cancel`, `api_reset` — FastAPI가 돌리는 **워커 스레드 위**

`call_soon_threadsafe`는 **양쪽 어디서 불러도 안전**하다. 그래서 호출자를 구분하는
분기 없이 한 함수로 처리된다. 이게 이 세 줄이 이렇게 생긴 유일한 이유다.

읽는 순서에 주의할 게 하나 있다. `_fanout(payload)`는 **부르는 쪽 스레드에서 즉시
평가되어** 코루틴 객체가 만들어지지만(1.4: `async def`를 부르면 실행 계획서만 생긴다),
`spawn`은 **루프 스레드에서** 실행되어 그 계획서를 태스크로 등록한다.
`create_task`를 스레드에서 직접 부르는 실수를 이렇게 피한다.

```python
async def _fanout(payload: dict) -> None:
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)
```

- `list(clients)` — 순회 도중 다른 코루틴이 `clients`를 바꿔도 안전하게 복사본을 돈다.
- 실패한 소켓은 **바로 지우지 않고** `dead`에 모아 뒀다가 순회가 끝난 뒤 지운다.
  순회 중인 자료구조를 수정하는 건 파이썬에서 금지다.
- 브라우저 탭 하나가 닫혀 있어도 나머지에게는 정상 전송된다.

## 2.6 feed 콜백 세 개

`feed.py`가 프레임을 받아 파싱한 뒤 이 함수들을 부른다. **전부 이벤트 루프 위에서 실행된다.**

```python
def on_trade(symbol: str, data: dict) -> None:
    last_price[symbol] = data["price"]
    broadcast({"type": "trade", ...})

    with broker_lock:
        fills = broker.on_trade(symbol, data["price"], data["volume"], tz_now())
    for f in fills:
        broadcast({"type": "fill", ...})
    if fills:
        broadcast(portfolio_payload())
```

한 함수에 이 시스템의 심장이 다 들어 있다.

1. `last_price` 갱신 — 화면의 현재가와 평가손익 계산의 근거.
2. 브라우저에 시세 푸시.
3. **`broker.on_trade()` — 여기가 지정가가 체결되는 유일한 경로다**(1.8). 업스트림이
   끊기면 이 줄이 안 불리고, 체결됐어야 할 주문이 영원히 대기한다.
4. 체결이 났으면 체결 알림 + 갱신된 포트폴리오 푸시.

`with broker_lock`이 붙은 이유(1.3): 이 함수는 이벤트 루프 위인데, 동시에 워커 스레드의
`api_place`가 같은 SQLite 연결과 같은 주문 행을 만질 수 있다. 락이 없으면
`place()`가 주문 행을 커밋한 직후, 아직 스윕하기 전의 **중간 상태**를 `on_trade`가 보게
되고, 같은 수량을 양쪽에서 체결시켜 초과체결이 난다.

```python
def on_orderbook(symbol: str, data: dict) -> None:
    books[symbol] = Book(...)
    book_fetched_at[symbol] = time.monotonic()
    broadcast({"type": "orderbook", ...})
```

`time.monotonic()`을 쓴 게 포인트다. `time.time()`은 시스템 시계라 NTP 동기화나
사용자의 시계 변경으로 **거꾸로 갈 수 있다**. `monotonic`은 절대 뒤로 안 간다.
"몇 초 지났나"를 재는 데는 언제나 이쪽이다.

```python
def on_status(status: str, message: str) -> None:
    feed_status.update(status=status, message=message)
    broadcast({"type": "feed", "status": status, "message": message})
```

`feed.py`가 연결 상태를 알릴 때 불린다. 이게 화면 상단 빨간 배너가 되고, 1.5에서 말한
"복구 불가능한 데이터 공백"을 사용자에게 알리는 유일한 수단이다.

> **여기서 코드에 반복해 나오는 규칙 하나.** `feed_status`는 **실시간 웹소켓의 상태만**
> 뜻한다. `api_candles`나 `expire_at_close` 같은 **별개의 REST 호출이 실패했을 때
> `on_status("error")`를 부르면 안 된다.** 그러면 피드는 멀쩡한데 화면은 끊긴 것처럼
> 보이고, 다음 진짜 feed 전환이 올 때까지 그 거짓 상태가 그대로 남는다.
> 그래서 그쪽 실패들은 콘솔 출력이나 응답 헤더로만 남긴다.

## 2.7 헬퍼 네 개

### `tz_now()` — 절대 네트워크를 타면 안 되는 함수

```python
def tz_now() -> datetime:
    return datetime.now().astimezone()
```

한 줄인데 docstring이 훨씬 길다. 예전 버전은 여기서 장 캘린더 API를 불렀고, 그게
아래 연쇄 고장을 만들었다.

```
이 함수는 체결 프린트마다 불린다 (초당 수십 번)
        ↓
그 자리는 이벤트 루프 위, 정확히는 웹소켓 수신 루프 안이다
        ↓
API 호출이 한 번 실패해 예외가 난다
        ↓
예외가 수신 루프를 뚫고 나가 웹소켓 연결이 끊긴다
        ↓
feed가 재접속한다 → 다시 체결 프린트가 온다 → 같은 자리에서 또 죽는다
        ↓
피드가 영영 살아나지 않는 무한루프
```

`.astimezone()`을 붙이는 이유는 별개다. `datetime.now()`는 타임존 정보가 없는
**naive** 객체를 준다. 이걸 타임존이 붙은 **aware** 객체(`Session.start` 등)와 비교하면
파이썬이 `TypeError`를 낸다. 섞어 쓰지 않기 위해 여기서 로컬 타임존을 붙인다.

### `book_of()` — 캐시와 신선도

```python
def book_of(symbol: str) -> Book:
    fetched = book_fetched_at.get(symbol)
    if symbol not in books or fetched is None or time.monotonic() - fetched > BOOK_MAX_AGE:
        books[symbol] = toss.get_orderbook(symbol)
        book_fetched_at[symbol] = time.monotonic()
    return books[symbol]
```

시장가 주문이 훑을 호가를 준다. 조건 세 개가 각각 다른 사고를 막는다.

- `symbol not in books` — 구독 직후에는 스냅샷이 없다(다음 갱신부터 푸시된다).
  이 fallback이 없으면 종목 추가 직후의 시장가 주문이 **빈 호가창을 훑는다**.
- `time.monotonic() - fetched > BOOK_MAX_AGE` — 반대 방향의 사고. 웹소켓이 끊겨서
  갱신이 멈췄는데 영원히 캐시하면, 시장가 주문이 **몇 분 전 가격으로 체결된다.**
  3초보다 오래된 스냅샷은 버리고 다시 받는다.

**이 함수는 네트워크를 탈 수 있다.** 그래서 1.3의 규칙에 따라 **락 밖에서** 불러야 한다.
2.9에서 다시 나온다.

### `current_session()` — 하루 한 번만

```python
def current_session():
    today = datetime.now().date().isoformat()
    if session_cache["date"] != today:
        session_cache.update(date=today, session=toss.get_session())
    return session_cache["session"]
```

장 시간은 하루에 한 번만 확인하면 된다. 날짜가 바뀔 때만 API를 부른다.
이것도 **블로킹 함수**라는 걸 기억해 두자. 2.8에서 문제가 된다.

### `portfolio_payload()` — `None`과 `0`을 구분하기

```python
if price is None:
    positions.append({..., "price": None, "pnl": None, "pnl_pct": None})
    continue
```

이 `if` 하나가 중요한 이유. 가격을 `last_price.get(symbol) or 0`처럼 뭉개면,
**"가격을 아직 모름"과 "가격이 0원"이 같아진다.** 관심종목에서 뺐거나 startup의
`get_prices`가 실패한 종목이 화면에 `-100%` (전액 손실)로 찍힌다. 실제로는 그냥 모르는 것이다.

`0`, `None`, `""`가 파이썬에서 다 falsy라 `or`로 뭉뚱그리기 쉬운데, **모른다와 값이
0이다가 의미상 다른 자리에서는 항상 `is None`으로 명시적으로 갈라야 한다.**

## 2.8 수명주기: `startup`과 `expire_at_close`

```python
@app.on_event("startup")
async def startup() -> None:
    global loop
    loop = asyncio.get_running_loop()      # 2.3의 다리를 위해 루프를 붙잡는다
    syms = watchlist()
    if syms:
        feed.set_symbols(syms)
        try:
            last_price.update(toss.get_prices(syms))
        except toss.TossError as exc:
            on_status("error", str(exc))    # 여긴 진짜 시세 조회라 feed 상태가 맞다
    spawn(feed.run())                       # 절대 안 끝나는 코루틴
    spawn(expire_at_close())                # 절대 안 끝나는 코루틴
```

`spawn`으로 띄우고 `await`하지 않는 게 핵심이다. 둘 다 무한루프라 `await`하면 서버가
영영 기동을 못 끝낸다. 등록만 하고 넘어가면 이벤트 루프가 알아서 돌린다(1.4).

### `expire_at_close()` — 짧은데 방어가 세 겹

```python
while True:
    await asyncio.sleep(60)
    try:
        session = await asyncio.to_thread(current_session)
        if session is None:
            continue
        now = tz_now()
        if now >= session.end:
            with broker_lock:
                expired = broker.expire_all(now=now)
            if expired:
                broadcast({"type": "expired", "order_ids": expired})
                broadcast(portfolio_payload())
    except Exception as exc:
        print(f"[expire_at_close] 주문 만료 확인 실패: {exc}")
        continue
```

**왜 필요한가:** 실제 주문은 당일 만료다. 이게 없으면 어제 걸어 둔 지정가가 오늘 시세에
체결되고, 잔고가 거짓이 된다.

**`await asyncio.sleep(60)`** — `time.sleep(60)`이었으면 서버 전체가 60초씩 정지한다(1.4).
`await`가 붙은 건 그 60초 동안 루프가 다른 일을 한다는 뜻이다.

**`await asyncio.to_thread(current_session)`** — 이게 1.4의 탈출구다.
`current_session()`은 날짜가 바뀌면 `requests.get(timeout=10)`을 탄다(2.7). 그걸 루프
위에서 그냥 부르면 최대 10초 동안 웹소켓 수신도, 핑도, 모든 요청도 멎는다.
`tz_now()`에서 걷어낸 것과 **정확히 같은 결함**이라 여기서도 스레드로 뺀다.

**`try`로 루프 본문 전체를 감싼 이유** — 토스가 잠깐 죽어 있으면 `TossError`가 난다.
가드가 없으면 예외가 무한루프를 뚫고 나가 **태스크가 조용히 죽고**, 그 뒤로 이 프로세스가
살아 있는 동안 미체결 주문이 다시는 만료되지 않는다. 로그에는
`Task exception was never retrieved` 한 줄만 남는다. `continue`로 다음 60초를 기다린다.

**`on_status`를 안 부르는 이유** — 2.6의 규칙. 이건 피드가 아니라 별개의 REST 실패다.

## 2.9 REST 엔드포인트

### `api_place` — 이 파일에서 가장 조심스러운 함수

```python
@app.post("/api/orders")
def api_place(body: OrderIn):
    session = current_session()
    if session is None:
        raise HTTPException(400, "오늘은 휴장일입니다.")

    book = book_of(body.symbol)        # ← 락 밖! 네트워크를 탈 수 있다
    try:
        with broker_lock:              # ← 락 안에서는 계산만
            oid = broker.place(body.symbol, body.side, body.type, body.qty,
                               body.limit_price, book=book,
                               session=session, now=tz_now())
    except OrderRejected as exc:
        raise HTTPException(400, str(exc))
    broadcast(portfolio_payload())
    return {"order_id": oid, "order": dict(broker.order(oid))}
```

**`book_of()`가 락 밖에 있는 게 이 함수의 전부다.** 1.3의 규칙이다. `book_of`는 캐시가
오래됐으면 토스에 REST를 부른다. 그걸 락 안에서 하면, 그 요청이 끝날 때까지(최대 10초)
같은 락을 기다리는 **`on_trade`가 통째로 막힌다.** 실시간 체결 판정이 몇 초씩 정지한다.

패턴을 일반화하면 이렇다.

```
느린 것(네트워크)은 락 밖에서 미리 준비하고 → 락 안에서는 빠른 것(계산·DB)만 한다
```

`session`, `book`, `now`를 전부 **값으로 만들어서** `broker.place()`에 넘기는 것도 같은
설계다. `broker.py`는 네트워크를 전혀 모르기 때문에 테스트가 가짜 데이터만으로 돈다.

`OrderRejected`를 `HTTPException(400)`으로 바꾸는 것도 의도적이다. 400은 "네 요청이
잘못됐다"이고 500은 "내가 고장났다"인데, 잔고 부족은 서버 고장이 아니다.

### `api_watch` — 이 함수만 `async def`인 이유

```python
@app.post("/api/watchlist")
async def api_watch(body: WatchIn):
    ...
    feed.set_symbols(watchlist())
```

다른 REST 핸들러는 전부 `def`인데 이것만 `async def`다. 우연이 아니다.

`feed.set_symbols()`는 내부에서 `asyncio.create_task(self._declare())`를 부른다.
1.4에서 봤듯 `create_task`는 **지금 이 흐름이 이벤트 루프 위**여야 동작한다.
이 함수가 평범한 `def`였다면 FastAPI가 워커 스레드에서 돌리므로(2.2) 그 스레드에는
루프가 없어 `RuntimeError`로 죽는다.

증상이 고약하다. 관심종목은 DB에 잘 들어가는데(`INSERT`는 그 앞에서 끝났다)
feed 구독 갱신만 조용히 실패해서, **새로 추가한 종목에만 실시간 시세가 안 들어온다.**
DB에는 있는데 화면은 안 움직인다.

`MAX_SYMBOLS` 검사가 있는 이유도 물리적이다. 연결당 구독 100건 제한 / 종목당
`trade` + `orderbook` 2건 = 50종목이 상한이다.

### `api_candles` — 실패해도 형태를 안 바꾼다

```python
try:
    candles.update_candles(symbol, interval, db_path=MARKET_DB_PATH)
except Exception as exc:
    print(f"[api_candles] 캔들 수집 실패 ({symbol}/{interval}): {exc}")
    if response is not None:
        response.headers["X-Candles-Error"] = "fetch-failed"
df = candles.load_candles(...)
```

수집이 실패해도 **응답 본문은 여전히 배열**이다. 프론트가 이걸 바로 `candles.map()`으로
소비하기 때문에, 실패 시 `{"error": ...}` 같은 다른 모양을 주면 거기서 깨진다.
실패 사실은 헤더에만 담는다.

헤더 값이 `"fetch-failed"` 같은 영어인 것도 이유가 있다. **HTTP 헤더는 latin-1로만
인코딩되므로 한글을 넣을 수 없다.** 상세 메시지는 서버 콘솔에만 남긴다.

`on_status`를 안 부르는 건 2.6의 규칙이다.

### 나머지

`api_cancel`, `api_reset`은 `api_place`와 같은 패턴이다: **락으로 감싸고 → 성공하면
`broadcast(portfolio_payload())`.** 이 브로드캐스트가 있어야 다른 탭에서도 잔고가
즉시 갱신된다. 없으면 주문 넣은 탭만 최신이고 나머지는 새로고침할 때까지 옛날 값을 보여 준다.

## 2.10 `/ws` — 서버 쪽 웹소켓 엔드포인트

```python
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()                                   # 핸드셰이크 수락 (1.7)
    clients.add(ws)
    await ws.send_json({"type": "feed", **feed_status}) # 최초 상태 동기화
    await ws.send_json(portfolio_payload())
    try:
        while True:
            await ws.receive_text()      # 브라우저는 아무것도 안 보낸다
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
```

브라우저가 붙는 자리다. 이해가 안 되는 부분이 `while True: await ws.receive_text()`일 텐데,
**받은 값을 안 쓴다.** 브라우저는 아무것도 안 보내는데 왜 받고 있나?

핸들러 함수가 **반환하면 웹소켓 연결이 닫히기 때문**이다. 그래서 연결을 살려 두려면
함수 안에 머물러 있어야 하는데, 그냥 `while True: pass`로 돌면 CPU를 100% 태운다.
`await ws.receive_text()`는 **양보 지점**(1.4)이라 여기서 이벤트 루프에게 제어권을
넘기고 얌전히 잠든다. CPU를 안 쓴다.

그리고 브라우저 탭이 닫히면 이 `await`가 `WebSocketDisconnect` 예외로 깨어난다.
즉 이 줄은 "받기"가 아니라 **"끊길 때까지 잠자기"**다.

`finally`가 중요하다. 어떤 경로로 나가든 `clients`에서 제거된다. 안 하면 죽은 소켓이
집합에 계속 쌓이고, `_fanout`이 매번 거기에 전송을 시도한다.

방향을 정리하면 이렇다.

```
서버 → 브라우저:  trade, orderbook, fill, portfolio, feed, expired   (웹소켓 푸시)
브라우저 → 서버:  주문·취소·관심종목·차트                            (REST, 웹소켓 아님)
```

브라우저는 웹소켓으로 **듣기만** 한다. 행동은 전부 REST로 한다. 순서·에러·상태 코드가
필요한 건 요청-응답이 훨씬 다루기 쉽기 때문이다(1.6).

## 2.11 주문 하나가 흐르는 길

### 시장가 매수 100주

```
1. [브라우저]  POST /api/orders {symbol, side:"buy", type:"market", qty:100}
2. [워커스레드] api_place 시작 — 이 요청만의 스레드 (2.2)
3.             current_session() → 휴장이면 400
4.             book_of() → 캐시가 3초 이내면 그대로, 아니면 토스 REST (락 밖!)
5.             with broker_lock:                      ← 여기부터 다른 흐름 정지
6.               broker.place() → _validate()
7.                 수량>0? 호가단위? 장중? 현금 충분?(수수료 포함)
8.               orders 행 INSERT (status='pending')
9.               _sweep() — asks를 위에서부터 훑으며 _record_fill() 반복
10.              _settle() — filled / partial / cancelled 확정
11.            락 해제                                ← on_trade가 다시 돈다
12.            broadcast(portfolio_payload())
13. [이벤트루프] _fanout — 모든 브라우저 탭이 새 잔고를 받는다
14. [브라우저]  HTTP 응답 도착 + 웹소켓 푸시 도착 (둘 다 온다)
```

9번의 `_sweep`이 1.8의 "위에서부터 훑기"다. 호가가 소진되면 부분체결로 끝난다.
시장가는 **대기하지 않으므로** `pending`을 거치지 않고 바로 종료 상태가 된다.

### 지정가 매수 100주 @ 70,000원 (현재가 70,800원)

```
1~8.  위와 동일 (단, 8번에서 남은 pending 행은 limit_price=70000)
9.    _sweep(limit=70000) — asks 최저가가 70,800이라 즉시 break. 0주 체결.
10.   filled(0) < qty(100) → _settle 호출 안 함. status='pending'으로 남는다.
11.   응답: {"order_id": 7, "order": {..., "status": "pending"}}

      ... 시간이 흐른다. 서버는 이 주문에 대해 아무것도 안 한다 ...

12. [토스]      70,000원에 300주 거래 발생
13. [feed.py]   프레임 수신 → parse_event → ("trade", "005930", {price:70000, volume:300})
14. [이벤트루프] on_trade() 호출  ← 여기는 스레드가 아니라 루프 위다 (2.6)
15.             last_price 갱신 + 시세 브로드캐스트
16.             with broker_lock:
17.               broker.on_trade() — pending 주문 조회
18.                 WHERE status='pending' AND symbol=? AND limit_price IS NOT NULL
19.                 매수이고 70000 <= 70000 → 체결!
20.                 _record_fill(100주 @ 70,000) — 체결가는 프린트된 가격이다
21.                 프린트 물량 300 중 100 소진, 남은 200은 다른 대기 주문에게
22.                 filled_qty >= qty → status='filled'
23.             broadcast(체결 알림) + broadcast(포트폴리오)
24. [브라우저]  체결 알림이 뜬다
```

**18번의 `limit_price IS NOT NULL`이 없으면 서버가 죽는다.** 시장가 주문도 9번 스윕
직전까지는 잠깐 `status='pending'`으로 커밋돼 있고, 그 행의 `limit_price`는 `NULL`이다.
필터가 없으면 19번에서 `70000 <= None`을 비교하다 `TypeError`가 나고,
그 예외가 웹소켓 수신 루프를 뚫고 나가 **연결이 끊긴다**. 그러면 1.5의 데이터 공백이
시작된다. `broker_lock`이 있어도 이 필터는 필요하다 — 락은 순서를 보장하지 코드의
가정을 보장하지 않는다.

**20번: 체결가는 내 지정가(70,000)가 아니라 프린트된 가격이다.** 70,000원 이하로 사겠다고
했는데 69,800원에 거래가 났으면 69,800원에 산다. 유리한 쪽으로 체결되는 실제 규칙과 맞다.

**모델링하지 않은 것:** 큐 포지션. 실제 거래소는 같은 가격에 먼저 주문한 사람부터
체결시킨다. 여기서는 내 앞에 줄 서 있던 물량을 무시하므로 **실제보다 잘 체결된다.**
코드에 `ponytail:` 주석으로 명시돼 있다.

## 2.12 이 설계에서 조용히 틀리는 자리들

"조용히"가 핵심이다. 에러 메시지 없이 결과만 틀리는 것들이 가장 위험하다.

| 자리 | 안 지키면 | 방어 |
|---|---|---|
| 업스트림 웹소켓 끊김 | 지정가 체결 판정이 통째로 멈춘다. 복구 불가(1.5) | `on_status` → 빨간 배너 |
| `parse_event`의 예외 | 프레임 하나 때문에 연결이 끊긴다 | 어떤 입력에도 `None` 반환, 절대 안 던짐 |
| `tz_now()`에 네트워크 | 재접속마다 같은 자리에서 죽는 무한루프 | 로컬 시각만 반환 |
| `limit_price IS NOT NULL` 누락 | `None` 비교 `TypeError` → 연결 끊김 | SQL에 필터 |
| `broker_lock` 없음 | 초과체결, 중간 상태 노출 | 모든 브로커 변경을 직렬화 |
| 락 안에서 네트워크 | `on_trade`가 몇 초씩 정지 | `book_of`를 락 밖에서 먼저 |
| `expire_at_close`의 예외 | 태스크가 죽고 주문이 영영 안 만료됨 | 루프 본문 전체 `try` |
| 태스크 참조 안 잡기 | GC가 실행 중 태스크를 수거 | `spawn()` |
| 수수료 빼고 검증 | 잔고를 정확히 쓰는 주문이 통과 후 마이너스 | `reserved()`·`_validate` 양쪽에 수수료 포함 |
| 호가 단마다 반올림 안 함 | '반올림들의 합' ≠ '합의 반올림' → 1원 초과 | `_sweep_cost`가 `_record_fill`과 동일하게 반올림 |
| `price or 0` | "모름"이 `-100%` 손실로 표시됨 | `is None`으로 명시적 분기 |
| 상대경로 DB | 빈 DB를 새로 만들고 차트가 빈다 | `MARKET_DB_PATH` 절대경로 |
| `feed_status`를 REST 실패로 덮기 | 멀쩡한 피드가 끊긴 것처럼 보이는 거짓 상태 | 콘솔·헤더로만 |

## 2.13 직접 확인해 보기

```bash
python paper/tests/test_broker.py     # 체결 엔진 (프레임워크 없이 assert)
python paper/tests/test_ticks.py      # 호가단위
python paper/tests/test_toss.py       # 응답 파싱
python paper/tests/test_feed.py       # 프레임 파싱

python -m uvicorn paper.app:app --reload    # http://localhost:8000
```

테스트가 네트워크 없이 도는 이유가 2.1의 분업이다. `broker.py`는 `Book`과 체결 프린트라는
평범한 값만 받으므로, 가짜 호가창을 만들어 넣으면 체결 엔진 전체를 검증할 수 있다.

읽어 볼 순서를 추천하면:

1. `paper/ticks.py` (38줄) — 가장 짧고, 도메인 규칙 하나가 왜 필요한지가 명확하다.
2. `paper/broker.py` — 동시성이 전혀 없는 순수한 로직. 체결이 뭔지 여기서 익힌다.
3. `paper/feed.py` — 웹소켓 한 개의 수명주기. 1.7이 코드가 된 모습.
4. `paper/app.py` — 위 셋을 붙이는 자리. 어려운 건 전부 "두 세계를 잇기"(2.2)에서 나온다.
