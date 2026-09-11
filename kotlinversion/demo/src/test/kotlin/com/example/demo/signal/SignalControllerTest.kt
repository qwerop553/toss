package com.example.demo.signal

import com.example.demo.feed.OrderbookStore
import com.example.demo.feed.PriceSocketHandler
import com.example.demo.feed.TradeData
import com.example.demo.feed.signalMessageJson
import com.example.demo.feed.tradeMessageJson
import com.example.demo.trade.Side
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.springframework.http.ResponseEntity

/**
 * TradeServiceTest는 JPA 리포지토리가 필요해서 @DataJpaTest로 스프링
 * 컨텍스트를 띄웠지만, 여기는 **스프링을 아예 안 띄운다.**
 *
 * 이유: 이 컨트롤러가 하는 일은 전부 순수한 값 처리다 — JSON 문자열을
 * 파싱하고, 규칙을 검사하고, 저장소에 넣고, 응답 객체를 만든다. DB도
 * 필요 없고 웹 계층의 도움도 필요 없다. 그래서 객체를 손으로 조립해
 * 메서드를 직접 부르는 게 가장 빠르고, 무엇보다 안전하다 — 컨텍스트를
 * 띄우는 순간 FeedConfig가 딸려 올 위험(토스에 실제로 접속을 시도한다)을
 * 아예 지지 않는다. TradeServiceTest의 주석이 경고하는 바로 그 위험이다.
 *
 * PriceSocketHandler를 진짜 객체로 넘기는 것도 같은 맥락이다. 목(mock)을
 * 만들 필요가 없다 — 연결된 세션이 하나도 없으면 브로드캐스트는 빈
 * 목록을 도는 것으로 끝나고 아무 부작용도 없다. 대신 실제로 나가는
 * 메시지 모양은 signalMessageJson/tradeMessageJson을 직접 불러서 따로
 * 검증한다.
 */
class SignalControllerTest {

    private val signalStore = SignalStore()
    private val controller = SignalController(signalStore, PriceSocketHandler(OrderbookStore(), signalStore))

    private fun post(body: String): ResponseEntity<Any> = controller.receiveSignal(body)

    private fun bodyOf(response: ResponseEntity<Any>): Map<*, *> = response.body as Map<*, *>

    /** 계약의 정상 요청 본문. 테스트마다 한 필드씩 망가뜨려 쓰기 위해 문자열 조립으로 둔다. */
    private fun requestJson(
        stockCode: String = "005930",
        side: String = "\"BUY\"",
        price: String = "71500",
        strategy: String = "EmaCrossStrategy",
        timestamp: String = "2026-09-11T13:45:00+09:00",
        noteLine: String = ", \"note\": \"ema9 > ema21 골든크로스\"",
    ) = """
        {"stockCode": "$stockCode", "side": $side, "price": $price,
         "strategy": "$strategy", "timestamp": "$timestamp"$noteLine}
    """.trimIndent()

    @Test
    fun `정상 요청은 200과 함께 1부터 증가하는 id를 돌려준다`() {
        val first = post(requestJson())
        assertEquals(200, first.statusCode.value())
        assertEquals(true, bodyOf(first)["received"])
        assertEquals(1L, bodyOf(first)["id"])

        // 채번이 요청마다 증가하는지까지 봐야 "일련번호"라는 계약이 검증된다.
        assertEquals(2L, bodyOf(post(requestJson()))["id"])
    }

    @Test
    fun `note가 없는 요청도 정상 처리된다`() {
        val response = post(requestJson(noteLine = ""))
        assertEquals(200, response.statusCode.value())
        assertEquals(true, bodyOf(response)["received"])
    }

    @Test
    fun `잘못된 side는 400이다`() {
        // 소문자도 거부된다 — Side.valueOf는 대소문자를 구분한다.
        assertEquals(400, post(requestJson(side = "\"buy\"")).statusCode.value())
        assertEquals(400, post(requestJson(side = "\"HOLD\"")).statusCode.value())
    }

    @Test
    fun `price가 0 이하면 400이다`() {
        assertEquals(400, post(requestJson(price = "0")).statusCode.value())
        assertEquals(400, post(requestJson(price = "-100")).statusCode.value())
    }

    @Test
    fun `필수 필드가 빠지면 400이다`() {
        // 필드 하나씩 통째로 빠진 본문을 만들어 전부 400인지 확인한다.
        val full = mapOf(
            "stockCode" to "\"005930\"",
            "side" to "\"BUY\"",
            "price" to "71500",
            "strategy" to "\"EmaCrossStrategy\"",
            "timestamp" to "\"2026-09-11T13:45:00+09:00\"",
        )
        for (missing in full.keys) {
            val body = full.filterKeys { it != missing }.entries.joinToString(", ") { "\"${it.key}\": ${it.value}" }
            assertEquals(400, post("{$body}").statusCode.value(), "$missing 누락인데 400이 아니다")
        }
    }

    @Test
    fun `잘못된 형식의 값은 400이다`() {
        // 6자리가 아닌 종목코드, 오프셋이 없는 시각. 둘 다 계약 위반이고,
        // 특히 뒤쪽은 DateTimeParseException이 500으로 새어 나가지 않는지를 본다.
        assertEquals(400, post(requestJson(stockCode = "5930")).statusCode.value())
        assertEquals(400, post(requestJson(timestamp = "2026-09-11 13:45")).statusCode.value())
    }

    @Test
    fun `푸시 메시지는 note가 있으면 담고 없으면 필드 자체를 생략한다`() {
        val signal = Signal(1L, "005930", Side.BUY, 71_500L, "EmaCrossStrategy", "2026-09-11T13:45:00+09:00", "골든크로스")
        val json = signalMessageJson(signal)
        assertTrue(json.contains("\"type\":\"signal\""), json)
        assertTrue(json.contains("\"price\":71500"), "price는 따옴표 없는 숫자여야 한다: $json")
        assertTrue(json.contains("\"note\":\"골든크로스\""), json)

        // 여기가 이 기능에서 가장 틀리기 쉬운 지점이다 — null을 그대로
        // 직렬화하면 "note":null이 찍히는데, 계약은 필드 자체를 생략하라고 했다.
        assertFalse(signalMessageJson(signal.copy(note = null)).contains("note"), "note 키가 남아 있다")
    }

    @Test
    fun `체결 푸시 메시지는 timestamp가 null이면 키 자체를 생략한다`() {
        val json = tradeMessageJson("005930", TradeData(price = 71_500L, volume = 10L, timestamp = "2026-09-11T13:45:00+09:00"))
        assertTrue(json.contains("\"type\":\"trade\""), json)
        // 종목 필드명이 symbol이 아니라 stockCode인 건 의도된 계약이다(파이썬 러너가 이 이름을 읽는다).
        assertTrue(json.contains("\"stockCode\":\"005930\""), json)
        // 숫자로 나가야 한다. 문자열로 나가면 파이썬 쪽이 문자열 비교를 하게 된다.
        assertTrue(json.contains("\"price\":71500"), json)
        assertTrue(json.contains("\"volume\":10"), json)

        assertFalse(
            tradeMessageJson("005930", TradeData(71_500L, 10L, null)).contains("timestamp"),
            "timestamp 키가 남아 있다",
        )
    }
}
