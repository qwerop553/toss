package com.example.demo.quote

import com.example.demo.auth.TossAuthClient
import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component
import org.springframework.web.client.RestClient
import org.springframework.web.client.body
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper

/** 최우선 호가. 매수는 bestAsk, 매도는 bestBid로 체결한다. */
data class Quote(val bestAsk: Long, val bestBid: Long)

private const val QUOTE_PATH = "/orderbook"

@Component
class QuoteClient(
    @Value("\${toss.base-url}") baseUrl: String,
    private val tossAuthClient: TossAuthClient,
) {
    private val client = RestClient.builder().baseUrl(baseUrl).build()

    fun quote(stockCode: String): Quote {
        // 토큰을 생성자에서 한 번만 받지 않고 호출마다 tossAuthClient에 다시
        // 묻는 이유: 토큰은 만료되고 갱신된다. 여기서 매번 물어보면 캐시
        // 재사용/재발급 판단은 TossAuthClient 한 곳에서만 하고, 이 클래스는
        // "지금 유효한 토큰이 뭔지"만 신경 쓰면 된다.
        val body = client.get()
            .uri("$QUOTE_PATH?symbol={symbol}", stockCode)
            .header("Authorization", "Bearer ${tossAuthClient.accessToken()}")
            .retrieve()
            .body<String>()
            ?: error("호가 응답이 비어 있다")
        return parseQuote(body)
    }
}

private val mapper = JsonMapper.builder().build()

internal fun parseQuote(json: String): Quote {
    val result = mapper.readTree(json).get("result") ?: error("응답에 result가 없다")
    return Quote(
        bestAsk = prices(result, "asks").min(),
        bestBid = prices(result, "bids").max(),
    )
}

/** 배열 순서를 가정하지 않는다. asks는 내림차순으로 오므로 첫 원소가 최우선 호가가 아니다. */
private fun prices(result: JsonNode, field: String): List<Long> {
    val node = result.get(field) ?: error("응답에 $field 가 없다")
    val prices = ArrayList<Long>()
    for (level in node) {
        prices += (level.get("price") ?: error("호가에 price가 없다")).asString().toLong()
    }
    if (prices.isEmpty()) error("$field 호가가 비어 있다")
    return prices
}
