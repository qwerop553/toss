package com.example.demo.signal

import com.example.demo.feed.PriceSocketHandler
import com.example.demo.trade.Side
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RestController
import tools.jackson.databind.json.JsonMapper
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

// OrderController.kt와 같은 이유로 파일 단위 싱글턴이다(JsonMapper는 스레드
// 세이프하고 생성 비용이 있어서 요청마다 새로 만들 이유가 없다).
private val mapper = JsonMapper.builder().build()

// 종목코드는 6자리 숫자다. Regex 객체를 매 요청마다 새로 컴파일하지 않도록
// 파일 상단에 한 번만 만들어 둔다.
private val STOCK_CODE = Regex("""\d{6}""")

/**
 * 파이썬 전략 프로세스가 보내는 매매 시그널 수신구.
 *
 * **@RequestBody를 data class가 아니라 String으로 받는 이유는
 * OrderController.kt의 설명과 정확히 같다** — 이 리포는 어디서나 트리
 * 모델(readTree)로 JSON을 다루고, 이 조합(Jackson 3 + 이 Spring Boot
 * 버전)에서 Kotlin 생성자 바인딩이 별도 설정 없이 항상 되는지 확신이 없다.
 * 이미 검증된 방식을 쓰면 그 불확실성을 아예 안 지고 간다. 게다가 여기선
 * 덤이 하나 더 있다: note처럼 "있을 수도, 아예 필드가 없을 수도" 있는
 * 값을 get()의 null 여부로 곧장 구분할 수 있다.
 *
 * **검증 실패를 전부 400으로 묶는 방식도 OrderController와 같다.** 잘못된
 * side(Side.valueOf)와 규칙 위반(require)은 IllegalArgumentException,
 * 필수 필드 누락(error)은 IllegalStateException으로 자연스럽게 갈리므로
 * catch 두 개면 계약이 요구하는 400 케이스가 전부 덮인다. 여기에 하나만
 * 더 붙였는데, timestamp 파싱 실패(DateTimeParseException)는 저 두 계열
 * 어디에도 속하지 않아서(RuntimeException 직계) 따로 잡아주지 않으면
 * 500이 나가기 때문이다.
 */
@RestController
class SignalController(
    private val signalStore: SignalStore,
    private val priceSocketHandler: PriceSocketHandler,
) {

    @PostMapping("/api/signals")
    fun receiveSignal(@RequestBody body: String): ResponseEntity<Any> {
        return try {
            val json = mapper.readTree(body)

            val stockCode = (json.get("stockCode") ?: error("stockCode가 없습니다")).asString()
            require(STOCK_CODE.matches(stockCode)) { "stockCode는 6자리 숫자여야 합니다: $stockCode" }

            val price = (json.get("price") ?: error("price가 없습니다")).asLong()
            require(price > 0) { "price는 0보다 커야 합니다: $price" }

            val timestamp = (json.get("timestamp") ?: error("timestamp가 없습니다")).asString()
            // 파싱 결과를 일부러 버린다. 목적은 값을 얻는 게 아니라 "오프셋이
            // 포함된 ISO-8601인가"를 여기 경계에서 한 번 확인하는 것이고,
            // 보관·전송은 원문 문자열 그대로 한다(Signal.kt의 설명 참고).
            // OffsetDateTime.parse는 오프셋이 없는 문자열도 거부하므로
            // 계약의 "오프셋 포함"까지 이 한 줄이 검증해 준다.
            OffsetDateTime.parse(timestamp)

            val signal = signalStore.add(
                stockCode = stockCode,
                side = Side.valueOf((json.get("side") ?: error("side가 없습니다")).asString()),
                price = price,
                strategy = (json.get("strategy") ?: error("strategy가 없습니다")).asString(),
                timestamp = timestamp,
                // 계약상 note는 없으면 필드 자체가 생략되어 오지만, 보내는
                // 쪽이 실수로 "note": null을 넣을 수도 있다. 그때 NullNode에
                // asString()을 부르면 예외가 나거나 "null"이라는 문자열이
                // 들어올 수 있어서(Jackson 버전에 따라 다르다), 둘 다
                // "note 없음"으로 취급되도록 isNull을 함께 본다.
                note = json.get("note")?.takeIf { !it.isNull }?.asString(),
            )

            // 저장이 끝난 다음에 푸시한다. 순서를 뒤집으면 브라우저가
            // 아직 번호도 안 붙은 시그널을 먼저 보게 된다.
            priceSocketHandler.broadcast(signal)

            ResponseEntity.ok(mapOf("received" to true, "id" to signal.id))
        } catch (e: IllegalArgumentException) {
            // require()의 규칙 위반과 Side.valueOf의 잘못된 값이 둘 다 이 예외다.
            ResponseEntity.badRequest().body(mapOf("error" to e.message))
        } catch (e: IllegalStateException) {
            // error(...)로 던진, 필수 필드 누락 같은 요청 자체의 결함.
            ResponseEntity.badRequest().body(mapOf("error" to e.message))
        } catch (e: DateTimeParseException) {
            ResponseEntity.badRequest().body(mapOf("error" to "timestamp가 ISO-8601(오프셋 포함) 형식이 아닙니다: ${e.parsedString}"))
        }
    }
}
