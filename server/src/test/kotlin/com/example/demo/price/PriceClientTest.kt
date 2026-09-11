package com.example.demo.price

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals

class PriceClientTest {

    private val sample = """{
        "result": [
        {
            "symbol": "005930",
            "timestamp": "2026-03-25T09:30:00.123+09:00",
            "lastPrice": "72000",
            "currency": "KRW"
        }
        ]
    }
"""

    @Test
    fun `현재가를 잘 가져온다`(){
        val price = parsePrice(sample)
        assertEquals(listOf(72000L), price )
    }
}