package com.example.demo.feed

import org.springframework.stereotype.Component
import java.net.URI
import java.net.http.HttpClient
import java.net.http.WebSocket
import java.util.concurrent.CompletionStage
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

private const val WS_URL = "wss://openapi-ws.tossinvest.com/ws/v1"

// 서버는 180초 동안 아무것도 안 받으면 연결을 끊는다. 60초로 잡아서
// 세 번 여유를 두는 것 — 타이머 스레드가 한두 번 지연돼도 안전하게.
private const val PING_INTERVAL_SECONDS = 60L

// 재연결 대기 시간의 상한. 끊김이 길게 반복돼도(예: 토스 쪽 장애) 30초에
// 한 번씩은 재시도하도록 위쪽을 막아둔다 — 안 막으면 배수로 계속 커져서
// 몇 시간씩 재시도를 안 하게 될 수 있다.
private const val BACKOFF_MAX_SECONDS = 30L

// 연결 하나당 구독 가능한 건수가 100건이고, 종목 하나당 trade+orderbook
// 두 채널을 다 구독하니 2건씩 쓴다. 그래서 100 / 2 = 50종목이 이 연결
// 하나가 감당할 수 있는 한도다. 이 값을 넘겨 선언하면 토스 서버가 어떻게
// 반응할지 확인 안 됐으므로, 넘기기 전에 여기서 먼저 막는다.
private const val MAX_SYMBOLS = 50
/**
 * 토스 웹소켓 업스트림. 연결을 하나만 물고 콜백으로 흘려보낸다.
 *
 * 왜 연결이 하나인가:
 *   계정당 동시 연결이 2개로 제한된다. 브라우저 탭마다 새로 붙이면 탭
 *   3개에서 막힌다. 그래서 백엔드가 하나를 물고 브라우저에는 자체 /ws로
 *   팬아웃한다(그 팬아웃 부분은 이 클래스가 아니라 Spring의 /ws
 *   엔드포인트가 담당 — 이 클래스는 "토스와의 연결"만 안다).
 *
 * 왜 브라우저가 직접 못 붙나:
 *   핸드셰이크에 Authorization 헤더가 필요한데 브라우저 WebSocket API는
 *   커스텀 헤더를 넣을 수 없고, 넣을 수 있더라도 액세스 토큰이 프론트로
 *   새어 나간다. 반대로 이 클래스가 쓰는 java.net.http.WebSocket은 헤더를
 *   자유롭게 넣을 수 있는 서버(백엔드) 전용 클라이언트라서 이 문제가
 *   애초에 없다 — 이게 이 클래스가 브라우저 쪽과 코드를 공유할 수 없는
 *   근본 이유이기도 하다.
 */

class TossFeedClient(
    // 토큰을 문자열 하나로 안 받고 함수로 받는 이유: 토큰은 만료되고
    // 갱신된다(파이썬 버전의 get_access_token()과 동일). connect()가
    // 재연결할 때마다 이 함수를 다시 호출해야 그 시점에 유효한 토큰을
    // 쓴다. 생성 시점에 문자열로 한 번만 받으면 재연결 때 만료된 옛
    // 토큰을 계속 쓰게 된다.
    private val tokenProvider: () -> String,
    private val onTrade: (symbol: String, data: TradeData) -> Unit,
    private val onOrderbook: (symbol: String, data: OrderbookData) -> Unit,
    // 연결 상태(connected/reconnecting) 변화를 바깥(Spring 쪽, 결국 화면의
    // 배너)에 알리는 콜백. 파이썬 버전 주석 그대로: 업스트림이 끊기면
    // 지정가 체결 판정이 멈추는데, 조용히 두면 사용자는 왜 주문이 안
    // 체결됐는지 알 길이 없다. 그래서 상태 변화는 반드시 알린다.
    private val onStatus: (status: String, message: String) -> Unit,
) {
    // JDK 표준 HTTP 클라이언트. 이게 java.net.http.WebSocket을 만드는
    // 진입점이다. 별도 라이브러리(OkHttp, Tyrus 등)를 추가하지 않는 이유는
    // "커스텀 헤더가 필요하다"는 요구사항 하나를 위해 라이브러리를 더
    // 끌어올 필요가 없기 때문 — JDK 11+가 이미 이걸 표준으로 제공한다.
    private val httpClient = HttpClient.newHttpClient()

    // ping 전송과 재연결 대기(sleep 대신 schedule)를 전담하는 스레드 하나.
    // 왜 onOpen/onText 같은 소켓 콜백 스레드와 분리했나:
    //   HttpClient의 콜백은 내부 스레드풀에서 실행되는데, 거기서 직접
    //   Thread.sleep이나 블로킹 타이머를 돌리면 그 풀의 다른 작업(다음
    //   메시지 처리)이 막힐 수 있다. 파이썬 버전이 asyncio 이벤트 루프
    //   하나에서 await sleep으로 순서를 보장하는 것과 목적은 같고, 방식만
    //   "논블로킹 async"에서 "전용 스레드 하나"로 바뀐 것이다.
    // isDaemon = true인 이유: 이 스레드가 살아있다고 JVM 종료(예: 앱 셧다운)
    // 가 막히면 안 된다. 데몬 스레드는 다른 모든 스레드가 끝나면 JVM과
    // 함께 강제 종료된다.
    private val scheduler = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "toss-feed-scheduler").apply { isDaemon = true }
    }

    // @Volatile인 이유: 이 두 필드는 스케줄러 스레드(재연결 시 null로 리셋)와
    // 소켓 콜백 스레드(onOpen에서 세팅) 양쪽에서 읽고 쓴다. volatile이
    // 없으면 한쪽 스레드가 값을 바꿔도 다른 스레드가 캐시된 옛 값을 계속
    // 볼 수 있다(가시성 문제) — 락을 걸 정도로 복잡한 동기화가 필요한
    // 값은 아니라서, 가장 가벼운 volatile로 가시성만 보장한다.
    @Volatile private var webSocket: WebSocket? = null
    @Volatile private var symbols: List<String> = emptyList()

    // 재연결 대기 시간(초). onOpen에서 1로 리셋되고, 실패할 때마다 두
    // 배씩 늘어난다(지수 백오프) — "연결이 잠깐 튄 것"이면 1초 만에 바로
    // 복구되고, "서버가 아예 죽은 것"이면 재시도 폭격으로 서버를 더
    // 괴롭히지 않고 점점 뜸하게 두드린다.
    private var backoffSeconds = 1L

    // 현재 떠 있는 PING 스케줄을 취소할 수 있게 핸들을 들고 있는다.
    // 연결이 끊겼는데 이 핸들이 없으면 죽은 연결에 계속 PING을 보내려
    // 시도하는 타이머가 살아남는다.
    private var pingTask: ScheduledFuture<*>? = null

    // 구독 선언마다 붙이는 요청 id의 일련번호. 동시에 여러 스레드에서
    // setSymbols를 부를 가능성을 생각해 (재연결 스레드가 자동으로 다시
    // declare를 부르는 경우 등) 단순 var 대신 원자적으로 증가하는
    // AtomicLong을 쓴다.
    private val seq = AtomicLong(0)

    fun start() = connect()

    open fun shutdown(){
        pingTask?.cancel(false)
        scheduler.shutdownNow()
        webSocket?.abort()
    }

    /**
     * 관심종목이 바뀌면 전체를 다시 선언한다.
     *
     * 왜 "추가"가 아니라 "전체 재선언"인가: FeedEvent.kt의 buildDeclaration
     * 설명대로 이 프로토콜 자체가 full-replace라서, 새 종목만 따로 보내는
     * API가 없다. 그래서 여기서도 "지금까지 있던 것 + 새 것"을 합치는 게
     * 아니라 symbols 필드 자체를 통째로 교체한다.
     */
    fun setSymbols(newSymbols: List<String>) {
        // 한도를 넘겨 선언을 보내면 서버가 어떻게 반응하는지 확인되지
        // 않았으므로, 아예 보내기 전에 여기서 막아 실패를 예측 가능하게
        // 만든다(서버의 알 수 없는 거부 대신 우리 쪽의 분명한 예외).
        require(newSymbols.size <= MAX_SYMBOLS) {
            "구독 가능한 종목은 ${MAX_SYMBOLS}개까지입니다 (연결당 구독 100건 / 종목당 2건)."
        }
        symbols = newSymbols
        // 아직 연결이 없으면(webSocket == null) 여기서 보낼 수 없다 —
        // 대신 다음 onOpen이 declare(ws)를 부를 때 이 최신 symbols 값을
        // 그대로 읽어가므로, 연결이 나중에 열려도 결과적으로 반영된다.
        webSocket?.let { declare(it) }
    }

    /**
     * 연결을 새로 하나 연다. 이 함수 자체는 성공/실패를 기다리지 않고
     * 바로 반환한다(비동기) — 실제 성공/실패는 whenComplete 콜백이나
     * WebSocket.Listener의 onOpen/onError로 나중에 통보된다.
     */
    private fun connect() {
        httpClient.newWebSocketBuilder()
            // 브라우저는 못 넣는 바로 그 헤더. 매번 tokenProvider()를 새로
            // 호출해서, 재연결 시점에 만료된 토큰이 아니라 그 순간의
            // 최신 토큰을 쓰게 한다.
            .header("Authorization", "Bearer ${tokenProvider()}")
            .buildAsync(URI.create(WS_URL), listener())
            .whenComplete { _, error ->
                // 여기 잡히는 error는 "핸드셰이크 자체가 실패한 경우"다
                // (예: 인증 실패, DNS 실패). 핸드셰이크는 성공했는데 나중에
                // 끊기는 경우는 이 콜백이 아니라 Listener.onClose/onError로
                // 들어온다 — 그래서 재연결 로직을 한 군데(scheduleReconnect)
                // 로 모아 두고 세 곳(여기, onClose, onError)에서 공통으로
                // 부른다.
                if (error != null) {
                    onStatus("reconnecting", error.toString())
                    scheduleReconnect()
                }
            }
    }

    /**
     * 지수 백오프로 재연결을 예약한다.
     * Thread.sleep으로 현재 스레드를 막는 대신 scheduler.schedule을 쓰는
     * 이유: 이 함수는 소켓 콜백 스레드(onClose/onError)에서도 불리는데,
     * 그 스레드를 sleep으로 막아버리면 HttpClient 내부 스레드풀이 다른
     * 소켓 이벤트를 처리 못 하게 될 수 있다. schedule은 "미래에 실행할
     * 작업을 등록만" 하고 바로 반환하므로 호출한 스레드를 막지 않는다.
     */
    private fun scheduleReconnect() {
        pingTask?.cancel(false)   // 죽은 연결에 PING을 계속 시도하는 타이머를 정리
        webSocket = null
        scheduler.schedule({ connect() }, backoffSeconds, TimeUnit.SECONDS)
        // 다음 실패를 위해 미리 두 배로 늘려 둔다. connect()가 성공하면
        // onOpen이 1로 다시 리셋한다.
        backoffSeconds = minOf(backoffSeconds * 2, BACKOFF_MAX_SECONDS)
    }

    /** 현재 symbols를 기준으로 구독 선언 메시지를 만들어 보낸다. */
    private fun declare(ws: WebSocket) {
        // 매번 다른 id를 붙여야 서버가 "새 선언"으로 인식한다(FeedEvent.kt의
        // buildDeclaration 설명 참고).
        val reqId = "req-${seq.incrementAndGet()}"
        ws.sendText(buildDeclaration(symbols, reqId), true)
    }

    /**
     * 원문 프레임 하나를 파싱해서 알맞은 콜백으로 넘긴다.
     *
     * 여기서 try/catch가 없는 이유: parseEvent는 FeedEvent.kt에 문서화된
     * 대로 "절대 예외를 던지지 않는다"는 계약을 스스로 지킨다. 그 계약을
     * 믿고 이 함수는 결과가 null인지 아닌지만 본다 — 만약 여기서도
     * 방어적으로 try/catch를 또 두르면, "예외가 안 난다"는 계약이 정말
     * 지켜지고 있는지 테스트로 확인할 유인이 사라지고 버그를 감추게 된다.
     */
    private fun dispatch(raw: String) {
        when (val event = parseEvent(raw)) {
            is FeedEvent.Trade -> onTrade(event.symbol, event.data)
            is FeedEvent.Orderbook -> onOrderbook(event.symbol, event.data)
            // sealed interface라 컴파일러가 이 분기를 강제한다 — Trade,
            // Orderbook, null 중 하나를 빠뜨리면 컴파일이 안 된다.
            null -> Unit
        }
    }

    /**
     * 소켓 이벤트 콜백 모음. 매 connect()마다 새 인스턴스를 만드는 이유:
     * buffer(아래)가 "현재 연결에서 아직 안 끝난 조각 메시지"를 들고
     * 있는 상태값인데, 연결이 바뀌면 이전 연결의 미완성 조각을 이어붙일
     * 이유가 없다. 재연결마다 buffer를 깨끗하게 새로 시작하려고 리스너
     * 자체를 새로 만든다.
     */
    private fun listener() = object : WebSocket.Listener {
        // 토스가 JSON 하나를 여러 조각(onText가 last=false로 여러 번 불림)
        // 으로 나눠 보낼 수 있다. Python의 websockets 라이브러리는 이걸
        // 내부에서 자동으로 합쳐 주지만, JDK 표준 API는 조각을 그대로
        // 넘기므로 여기서 직접 이어붙였다가 last가 true일 때만 파싱한다.
        private val buffer = StringBuilder()

        override fun onOpen(ws: WebSocket) {
            backoffSeconds = 1   // 연결에 성공했으니 다음 실패는 다시 1초부터
            webSocket = ws
            declare(ws)          // 연결하자마자 지금 관심종목을 선언
            onStatus("connected", "")
            // 순수 텍스트 "PING"이다(JSON으로 감싸면 서버가 못 알아듣는다).
            // scheduleAtFixedRate로 60초 간격 반복 — 서버의 180초 타임아웃
            // 안에 여러 번 여유 있게 신호를 보낸다.
            pingTask = scheduler.scheduleAtFixedRate(
                { webSocket?.sendText("PING", true) },
                PING_INTERVAL_SECONDS, PING_INTERVAL_SECONDS, TimeUnit.SECONDS,
            )
            // JDK WebSocket은 백프레셔가 있어서, 이 request(n)을 부르기
            // 전까지는 다음 메시지를 절대 안 준다. "메시지 하나 처리
            // 준비 끝났다"를 매번 명시적으로 신청하는 셈이다 — 이걸
            // 안 하면 이후 onText가 한 번도 안 불린다.
            ws.request(1)
        }

        override fun onText(ws: WebSocket, data: CharSequence, last: Boolean): CompletionStage<*>? {
            buffer.append(data)
            if (last) {
                // 조각이 전부 모였을 때만 한 번 파싱·디스패치하고 버퍼를
                // 비운다. last가 false인 동안은 그냥 쌓기만 한다.
                dispatch(buffer.toString())
                buffer.clear()
            }
            // 이번 조각을 다 처리했으니 다음 조각/메시지를 요청한다.
            // last 여부와 무관하게 매번 불러야 스트림이 안 멈춘다.
            ws.request(1)
            return null   // 이 콜백을 동기로 처리했다는 뜻으로 null 반환(추가 대기 없음)
        }

        override fun onClose(ws: WebSocket, code: Int, reason: String): CompletionStage<*>? {
            pingTask?.cancel(false)
            webSocket = null
            // 파이썬 버전 주석 그대로: 끊긴 동안 지정가 체결 판정이
            // 멈춘다. 조용히 두면 사용자는 체결됐어야 할 주문이 왜 안
            // 됐는지 모른다. 반드시 알린다.
            onStatus("reconnecting", "closed: $code $reason")
            scheduleReconnect()
            return null
        }

        override fun onError(ws: WebSocket, error: Throwable) {
            // onClose와 사실상 같은 처리다 — JDK가 정상 종료(onClose)와
            // 비정상 에러(onError) 중 어느 쪽으로 알려줄지는 실패 원인에
            // 따라 달라지므로, 두 콜백 모두 같은 복구 절차(핑 취소 →
            // 상태 초기화 → 알림 → 재연결 예약)를 밟게 해 둔다.
            pingTask?.cancel(false)
            webSocket = null
            onStatus("reconnecting", error.toString())
            scheduleReconnect()
        }

    }
}
