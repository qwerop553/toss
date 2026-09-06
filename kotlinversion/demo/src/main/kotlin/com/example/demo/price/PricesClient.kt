package com.example.demo.price

import org.springframework.beans.factory.annotation.Value
import org.springframework.stereotype.Component
import org.springframework.web.client.RestClient
import org.springframework.web.client.body
import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper

/** 최우선 호가. 매수는 bestAsk, 매도는 bestBid로 체결한다. */
data class Prices(val nowPrices: ArrayList<Long>)

private const val PRICES_PATH = "/prices"

@Component
class PricesClient(
    @Value("\${toss.base-url}") baseUrl: String,
    @Value("\${toss.token}") private val token: String,
) {
    private val client = RestClient.builder().baseUrl(baseUrl).build()

    fun prices(stockCodes: String): List<Long> {
        val body = client.get()
            .uri("$PRICES_PATH?symbols={symbols}", stockCodes)
            .header("Authorization", "Bearer $token")
            .retrieve()
            .body<String>()
            ?: error("현재가 응답이 비어 있다")
        return parsePrice(body)
    }
}

private val mapper = JsonMapper.builder().build()

internal fun parsePrice(json: String): List<Long> {
    val results = mapper.readTree(json).get("result") ?: error("응답에 result가 없다")
    println("parsePrice의 results 값: $results")
    val prices = ArrayList<Long>()
    for (result in results){
        prices += (result.get("lastPrice") ?: error("호가에 lastPrice가 없다")).asString().toLong()
    }
    if (prices.isEmpty()) error("lastPrice가 비어있다.")
    println(prices)
    return prices
}


