package com.example.demo.trade

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.data.jpa.test.autoconfigure.DataJpaTest
import org.springframework.context.annotation.Import

/**
 * @SpringBootTest 대신 @DataJpaTest + @Import를 쓰는 이유: 전체 컨텍스트를
 * 띄우면 FeedConfig가 즉시 토스에 실제로 연결을 시도한다(네트워크·토큰
 * 필요, 테스트마다 느려지고 실패 원인도 아니다). @DataJpaTest는 JPA
 * 관련 빈(리포지토리, 인메모리 DB)만 띄우고, TradeService는 서비스 빈이라
 * 기본 대상이 아니므로 @Import로 직접 끼워 넣는다.
 */
@DataJpaTest
@Import(TradeService::class)
class TradeServiceTest {

    @Autowired lateinit var tradeService: TradeService
    @Autowired lateinit var accountRepository: AccountRepository
    @Autowired lateinit var holdingRepository: HoldingRepository

    @Test
    fun `현금이 부족하면 매수 주문이 거부된다`() {
        assertThrows<IllegalArgumentException> {
            tradeService.placeOrder("005930", Side.BUY, 999_999_999L, 1_000L)
        }
    }

    @Test
    fun `정상적인 지정가 매수 주문은 PENDING으로 저장된다`() {
        val order = tradeService.placeOrder("005930", Side.BUY, 70_000L, 10L)
        assertEquals(Status.PENDING, order.status)
    }

    @Test
    fun `지정가를 크로스하는 프린트가 오면 매수 주문이 체결되고 잔고·보유수량이 갱신된다`() {
        val order = tradeService.placeOrder("005930", Side.BUY, 70_000L, 10L)

        // 프린트가 지정가(70_000)보다 낮으니 크로스 — 전량 체결돼야 한다.
        // 체결가는 프린트 가격(69_500)이지 내 지정가가 아니다.
        tradeService.onTradePrint("005930", 69_500L, 5L)

        val holding = holdingRepository.findByStockCode("005930")
        assertEquals(10L, holding?.quantity)
        assertEquals(69_500L * 10, holding?.totalCost)

        val account = accountRepository.findById(1L).get()
        assertEquals(100_000_000L - 69_500L * 10, account.cashBalance)
    }

    @Test
    fun `지정가보다 비싼 프린트는 매수 주문을 체결시키지 않는다`() {
        tradeService.placeOrder("005930", Side.BUY, 70_000L, 10L)

        tradeService.onTradePrint("005930", 70_500L, 5L)   // 지정가보다 비쌈 → 크로스 안 됨

        assertEquals(null, holdingRepository.findByStockCode("005930"))
    }

    @Test
    fun `보유 수량이 없으면 매도 주문이 거부된다`() {
        assertThrows<IllegalArgumentException> {
            tradeService.placeOrder("005930", Side.SELL, 70_000L, 1L)
        }
    }

    @Test
    fun `매수 체결 후에는 그만큼 매도할 수 있다`() {
        tradeService.placeOrder("005930", Side.BUY, 70_000L, 10L)
        tradeService.onTradePrint("005930", 70_000L, 10L)

        val sellOrder = tradeService.placeOrder("005930", Side.SELL, 71_000L, 10L)
        assertEquals(Status.PENDING, sellOrder.status)

        tradeService.onTradePrint("005930", 71_500L, 10L)   // 지정가(71_000) 이상 → 크로스

        val holding = holdingRepository.findByStockCode("005930")
        assertEquals(0L, holding?.quantity)
        assertEquals(0L, holding?.totalCost)
    }
}
