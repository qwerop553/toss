package com.example.demo.feed

import com.example.demo.signal.Signal
import com.example.demo.signal.SignalStore
import org.springframework.stereotype.Component
import org.springframework.web.socket.CloseStatus
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketSession
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator
import org.springframework.web.socket.handler.TextWebSocketHandler
import tools.jackson.databind.json.JsonMapper
import java.util.concurrent.ConcurrentHashMap

private val mapper = JsonMapper.builder().build()

// 한 세션에 대한 전송이 이 시간을 넘기면 세션을 끊는다. 느린 소비자가
// 보내는 쪽 스레드를 영원히 붙잡는 것을 막는 상한이다.
private const val SEND_TIME_LIMIT_MS = 5_000

// 전송 대기 버퍼 상한. 소비자가 못 따라가서 이만큼 밀리면 그 세션을 버린다.
// 체결 프린트는 초당 수십 건이 올 수 있어서, 상한이 없으면 느린 구독자
// 하나가 서버 메모리를 계속 먹는다.
private const val BUFFER_SIZE_LIMIT = 512 * 1024

// 브라우저로 보낼 메시지 모양. OrderbookData엔 symbol이 없어서(종목별로
// 따로 관리되는 값이라) 여기서 symbol과 type을 붙여 감싼다.
//
// 종목 필드 이름이 여기만 "symbol"이고 아래 trade/signal 메시지는
// "stockCode"인 것은 **의도된 불일치**다. 호가 메시지의 symbol은 이미
// orderbook.html이 쓰고 있고, 이제는 파이썬 러너도 /ws를 구독하게 되므로
// 이름을 바꾸면 이미 돌아가는 소비자들을 동시에 깨뜨린다. 반대로 새로
// 생기는 메시지(trade/signal)는 소비자가 아직 없으니, 나머지 코드베이스가
// 쓰는 이름(REST 요청 본문도 stockCode다)으로 통일해 두는 편이 낫다.
// 즉 "전부 symbol"과 "전부 stockCode" 중에 후자로 수렴 중이고, 호가만
// 아직 옛 이름으로 남아 있는 상태다.
private data class OrderbookMessage(
    val type: String = "orderbook",
    val symbol: String,
    val asks: List<OrderbookLevel>,
    val bids: List<OrderbookLevel>,
)

/**
 * 체결(trade) 프린트 한 건을 푸시 메시지로 만든다.
 *
 * 여기도 데이터 클래스 대신 ObjectNode를 직접 조립한다 — 이유는 아래
 * signalMessageJson과 같다. TradeData.timestamp는 nullable인데(토스가 안
 * 줄 때가 있다) 계약상 없으면 **키 자체를 생략**해야 하고, 데이터 클래스로
 * 직렬화하면 `"timestamp": null`이 찍힌다.
 *
 * price·volume은 반드시 숫자로 나간다. TradeData가 이미 Long이라
 * put(String, Long) 오버로드가 선택되므로 자동으로 숫자가 되는데, 여기서
 * 실수로 toString()을 끼워 넣으면 파이썬 쪽이 문자열을 비교하다 "9" > "10"
 * 같은 조용한 오작동을 하게 된다(FeedEvent.kt가 파싱 단계에서 굳이 Long으로
 * 바꿔 둔 것과 같은 이유다).
 */
fun tradeMessageJson(symbol: String, data: TradeData): String {
    val node = mapper.createObjectNode()
    node.put("type", "trade")
    node.put("stockCode", symbol)
    node.put("price", data.price)
    node.put("volume", data.volume)
    if (data.timestamp != null) node.put("timestamp", data.timestamp)
    return mapper.writeValueAsString(node)
}

/**
 * 시그널 푸시 메시지를 만든다.
 *
 * **OrderbookMessage처럼 데이터 클래스를 하나 더 만들지 않고 ObjectNode를
 * 직접 조립하는 이유:** 계약이 "note가 없으면 필드 자체를 생략하라(null로
 * 내보내지 마라)"고 못 박았다. 데이터 클래스에 note: String?을 두고
 * 직렬화하면 Jackson은 기본적으로 `"note": null`을 찍는다. @JsonInclude
 * 같은 애노테이션으로 바꿀 수도 있지만, 그건 "애노테이션이 이렇게 동작할
 * 것이다"를 믿는 것이고, 아래 코드의 `if (note != null) put(...)` 한 줄은
 * 눈으로 확인되는 사실이다. 게다가 이 리포는 이미 FeedEvent.buildDeclaration
 * 에서 같은 방식(ObjectNode 직접 조립)으로 보내는 JSON을 만들고 있다.
 *
 * private가 아니라 공개 함수인 이유: 이 "note가 있을 때만 필드가 붙는다"는
 * 규칙이 이 기능에서 가장 틀리기 쉬운 부분이라 테스트로 직접 확인하고
 * 싶었다. 클래스 안의 private 함수로 두면 웹소켓 세션 없이는 검증할 수가
 * 없다.
 */
fun signalMessageJson(signal: Signal): String {
    val node = mapper.createObjectNode()
    node.put("type", "signal")
    node.put("id", signal.id)
    node.put("stockCode", signal.stockCode)
    node.put("side", signal.side.name)
    node.put("price", signal.price)
    node.put("strategy", signal.strategy)
    node.put("timestamp", signal.timestamp)
    if (signal.note != null) node.put("note", signal.note)
    return mapper.writeValueAsString(node)
}

@Component
class PriceSocketHandler(
    private val orderbookStore: OrderbookStore,
    private val signalStore: SignalStore,
) : TextWebSocketHandler() {
    /**
     * 파이썬의 clients: set[WebSocket]과 같은 역할.
     *
     * **Set이 아니라 "세션id → 세션" Map인 이유:** 아래에서 원본 세션을
     * ConcurrentWebSocketSessionDecorator로 감싸서 보관하는데, 연결이
     * 끊길 때 컨테이너가 afterConnectionClosed로 넘겨주는 것은 감싸기 전의
     * **원본** 세션이다. 데코레이터는 equals를 재정의하지 않으므로 Set에
     * 담아두면 `sessions -= session`이 아무것도 못 지우고 죽은 세션이
     * 영원히 남는다. 세션 id는 감싸도 그대로 유지되므로(데코레이터가
     * 위임한다) id를 키로 쓰면 이 문제가 사라진다.
     */
    private val sessions = ConcurrentHashMap<String, WebSocketSession>()

    override fun afterConnectionEstablished(session: WebSocketSession) {
        // **원본 세션을 그대로 쓰지 않고 감싸는 이유:** sendMessage는 스레드
        // 세이프가 아니다. 지금 이 핸들러는 서로 다른 두 스레드에서 불린다 —
        // 호가·체결은 TossFeedClient의 웹소켓 수신 스레드에서, 시그널은
        // SignalController가 도는 HTTP 워커 스레드에서 온다. 두 스레드가 같은
        // 세션에 동시에 쓰면 톰캣이 IllegalStateException("The remote endpoint
        // was in state [TEXT_FULL_WRITING]")을 던지고, 아래 sendAll의 catch가
        // 그걸 "죽은 세션"으로 오해해 멀쩡한 구독자를 목록에서 빼버린다.
        // 브라우저 입장에서는 새로고침 전까지 화면이 조용히 멈춘 것처럼 보인다.
        //
        // 직접 락을 잡는 대신 스프링이 이미 제공하는 데코레이터를 쓴다. 이건
        // 전송을 직렬화해 줄 뿐 아니라 위의 시간·버퍼 상한까지 같이 걸어줘서,
        // 느린 구독자(예: 전략 계산이 밀린 파이썬 러너)가 시세 스레드를 붙잡는
        // 상황도 함께 막는다. 체결 프린트가 호가보다 훨씬 자주 오는 지금
        // 구조에서는 이 상한이 실제로 필요하다.
        val concurrent = ConcurrentWebSocketSessionDecorator(session, SEND_TIME_LIMIT_MS, BUFFER_SIZE_LIMIT)
        sessions[session.id] = concurrent

        // 방금 접속한 브라우저는 지금까지의 호가를 하나도 못 봤으니,
        // 저장소에 있는 최신 값을 스냅샷으로 즉시 보내준다.
        // 감싼 쪽으로 보내야 한다 — 원본으로 보내면 바로 이 순간 피드
        // 스레드가 브로드캐스트하는 것과 겹칠 수 있다.
        orderbookStore.latest("005930")?.let { concurrent.sendMessage(TextMessage(toJson("005930", it))) }
        // 시그널도 같은 이유로 최신 한 건만 보낸다. 여러 건을 몰아 보내면
        // 배너가 순식간에 덮어써져서 결국 마지막 것만 보이는데, 그럴 거면
        // 처음부터 마지막 것만 보내는 게 맞다.
        signalStore.latest()?.let { concurrent.sendMessage(TextMessage(signalMessageJson(it))) }
    }

    override fun afterConnectionClosed(session: WebSocketSession, status: CloseStatus) {
        // 여기 들어오는 session은 감싸기 전의 원본이다. 그래서 객체가 아니라
        // id로 지운다(위 sessions 선언의 설명 참고).
        sessions -= session.id
    }

    /** TossFeedClient가 새 호가를 받을 때마다 이걸 부른다. */
    fun broadcast(symbol: String, data: OrderbookData) = sendAll(TextMessage(toJson(symbol, data)))

    /**
     * TossFeedClient가 새 체결 프린트를 받을 때마다 부른다.
     *
     * 체결은 호가보다 훨씬 자주 오기 때문에 이 경로가 무거우면 시세
     * 콜백 스레드가 밀린다. 그래서 JSON은 세션마다가 아니라 **한 번만**
     * 만들어서(TextMessage 하나) 모든 세션이 같은 객체를 재사용한다 —
     * 위 호가 브로드캐스트와 똑같은 모양이다.
     */
    fun broadcast(symbol: String, data: TradeData) = sendAll(TextMessage(tradeMessageJson(symbol, data)))

    /**
     * SignalController가 시그널을 저장한 직후에 부른다.
     * 새 소켓을 따로 열지 않고 호가와 **같은 /ws 세션들**로 내보낸다 —
     * 프론트는 메시지의 type 필드로 분기한다.
     */
    fun broadcast(signal: Signal) = sendAll(TextMessage(signalMessageJson(signal)))

    /**
     * 열린 세션 전부에게 같은 메시지를 보낸다.
     *
     * **왜 sendMessage를 try/catch로 감싸는가:** isOpen이 true여도 그 직후에
     * 보내다가 IOException이 날 수 있다(브라우저가 새로고침·탭 종료로 막
     * 끊었는데 afterConnectionClosed가 아직 안 불린 찰나). 그 예외를 그대로
     * 올려보내면 호가 경로에서는 죽은 세션 하나 때문에 뒤쪽 세션들이 그
     * 프레임을 통째로 못 받고, 시그널 경로에서는 이미 저장까지 끝난
     * 시그널이 파이썬에는 500으로 보여서 불필요한 재전송을 부른다. 어차피
     * 죽은 세션이니 목록에서 빼고 나머지에게 계속 보내는 게 맞다.
     *
     * 여기서 예외를 "죽은 세션"으로 해석해도 되는 건, 동시 전송 충돌을
     * afterConnectionEstablished의 데코레이터가 이미 막아주기 때문이다.
     * 그게 없으면 멀쩡한 세션이 스레드 경합 때문에 던진 예외까지 여기서
     * 강제 퇴장 처리되어, 화면이 이유 없이 멈춘다.
     *
     * 반복 중에 sessions에서 원소를 빼도 안전한 건 ConcurrentHashMap이기
     * 때문이다 — 순회가 약한 일관성(weakly consistent)이라
     * ConcurrentModificationException이 나지 않는다.
     */
    private fun sendAll(message: TextMessage) {
        for ((id, session) in sessions) {
            if (!session.isOpen) continue
            try {
                session.sendMessage(message)
            } catch (e: Exception) {
                sessions -= id
            }
        }
    }

    private fun toJson(symbol: String, data: OrderbookData): String =
        mapper.writeValueAsString(OrderbookMessage(symbol = symbol, asks = data.asks, bids = data.bids))
}
