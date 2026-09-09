package com.example.demo.feed

import org.springframework.stereotype.Component
import org.springframework.web.socket.CloseStatus
import org.springframework.web.socket.TextMessage
import org.springframework.web.socket.WebSocketSession
import org.springframework.web.socket.handler.TextWebSocketHandler
import tools.jackson.databind.json.JsonMapper
import java.util.concurrent.CopyOnWriteArraySet

private val mapper = JsonMapper.builder().build()

// 브라우저로 보낼 메시지 모양. OrderbookData엔 symbol이 없어서(종목별로
// 따로 관리되는 값이라) 여기서 symbol과 type을 붙여 감싼다.
private data class OrderbookMessage(
    val type: String = "orderbook",
    val symbol: String,
    val asks: List<OrderbookLevel>,
    val bids: List<OrderbookLevel>,
)

@Component
class PriceSocketHandler(private val orderbookStore: OrderbookStore) : TextWebSocketHandler() {
    // 파이썬의 clients: set[WebSocket]과 같은 역할. CopyOnWriteArraySet인
    // 이유는 아래에서 따로 설명한다.
    private val sessions = CopyOnWriteArraySet<WebSocketSession>()

    override fun afterConnectionEstablished(session: WebSocketSession) {
        sessions += session
        // 방금 접속한 브라우저는 지금까지의 호가를 하나도 못 봤으니,
        // 저장소에 있는 최신 값을 스냅샷으로 즉시 보내준다.
        orderbookStore.latest("005930")?.let { session.sendMessage(TextMessage(toJson("005930", it))) }
    }

    override fun afterConnectionClosed(session: WebSocketSession, status: CloseStatus) {
        sessions -= session
    }

    /** TossFeedClient가 새 호가를 받을 때마다 이걸 부른다. */
    fun broadcast(symbol: String, data: OrderbookData) {
        val message = TextMessage(toJson(symbol, data))
        for (session in sessions) {
            if (session.isOpen) session.sendMessage(message)
        }
    }

    private fun toJson(symbol: String, data: OrderbookData): String =
        mapper.writeValueAsString(OrderbookMessage(symbol = symbol, asks = data.asks, bids = data.bids))
}
