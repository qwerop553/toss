package com.example.demo.trade

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RestController
import tools.jackson.databind.json.JsonMapper

private val mapper = JsonMapper.builder().build()

/**
 * @RequestBody를 Kotlin data class로 바로 안 받고 String으로 받아서 직접
 * 파싱하는 이유: 이 리포는 이미 어디서나(QuoteClient·FeedEvent) 트리
 * 모델(readTree)로 JSON을 다룬다. 요청 바디를 데이터 클래스 생성자로
 * 바로 바인딩하려면 Jackson이 Kotlin 생성자를 이해해야 하는데, 이 조합
 * (Jackson 3 + 이 Spring Boot 버전)에서 그게 별도 설정 없이 항상 되는지
 * 확신이 없다. 이미 검증된 방식(String → readTree)을 쓰면 그 불확실성을
 * 아예 안 지고 간다.
 */
@RestController
class OrderController(private val tradeService: TradeService) {

    @PostMapping("/api/orders")
    fun placeOrder(@RequestBody body: String): ResponseEntity<Any> {
        return try {
            val json = mapper.readTree(body)
            val order = tradeService.placeOrder(
                stockCode = (json.get("stockCode") ?: error("stockCode가 없습니다")).asString(),
                side = Side.valueOf((json.get("side") ?: error("side가 없습니다")).asString()),
                price = (json.get("price") ?: error("price가 없습니다")).asLong(),
                quantity = (json.get("quantity") ?: error("quantity가 없습니다")).asLong(),
            )
            ResponseEntity.ok(mapOf("id" to order.id, "status" to order.status.name))
        } catch (e: IllegalArgumentException) {
            // require()의 검증 실패(현금·수량 부족)와 Side.valueOf의 잘못된
            // 값 둘 다 이 예외라 한 곳에서 400으로 묶어 처리할 수 있다.
            ResponseEntity.badRequest().body(mapOf("error" to e.message))
        } catch (e: IllegalStateException) {
            // error(...)로 던진, JSON 필드 누락 같은 요청 자체의 결함.
            ResponseEntity.badRequest().body(mapOf("error" to e.message))
        }
    }
}
