package com.example.demo.feed

import org.springframework.stereotype.Component
import java.util.concurrent.ConcurrentHashMap

@Component
class OrderbookStore {
    private val latest = ConcurrentHashMap<String, OrderbookData>()

    fun update(symbol: String, data: OrderbookData) {
        latest[symbol] = data
    }

    fun latest(symbol: String): OrderbookData? = latest[symbol]
}
