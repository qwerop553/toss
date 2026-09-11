package com.example.demo.quote

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class QuoteClientTest {

    private val sample = """
        {
          "result": {
            "timestamp": "2026-03-25T09:30:00.123+09:00",
            "currency": "KRW",
            "asks": [
              { "price": "72300", "volume": "1200" },
              { "price": "72200", "volume": "3400" },
              { "price": "72100", "volume": "8500" }
            ],
            "bids": [
              { "price": "72000", "volume": "5200" },
              { "price": "71900", "volume": "4100" },
              { "price": "71800", "volume": "2700" }
            ]
          }
        }
    """

    @Test
    fun `매도호가 중 최저가와 매수호가 중 최고가를 뽑는다`() {
        val quote = parseQuote(sample)

        assertEquals(72100L, quote.bestAsk)
        assertEquals(72000L, quote.bestBid)
    }

    @Test
    fun `호가가 비어 있으면 예외를 던진다`() {
        val empty = """{ "result": { "asks": [], "bids": [] } }"""

        assertThrows<IllegalStateException> { parseQuote(empty) }
    }
}
