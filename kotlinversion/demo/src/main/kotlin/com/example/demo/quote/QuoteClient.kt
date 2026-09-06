package com.example.demo.quote

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
    @Value("\${toss.token}") private val token: String,
) {
    private val client = RestClient.builder().baseUrl(baseUrl).build()

    fun quote(stockCode: String): Quote {
        val body = client.get()
            .uri("$QUOTE_PATH?symbol={symbol}", stockCode)
            .header("Authorization", "Bearer $token")
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
