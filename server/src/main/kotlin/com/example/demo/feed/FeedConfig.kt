package com.example.demo.feed

import com.example.demo.auth.TossAuthClient
import com.example.demo.trade.TradeService
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration

@Configuration
class FeedConfig {

    @Bean(destroyMethod = "shutdown")
    fun tossFeedClient(
        tossAuthClient: TossAuthClient,
        orderbookStore: OrderbookStore,
        priceSocketHandler: PriceSocketHandler,
        tradeService: TradeService,
    ): TossFeedClient {
        val feed = TossFeedClient(
            tokenProvider = tossAuthClient::accessToken,
            // 체결 프린트는 두 군데로 간다. (1) 모의 체결 판정(기존 동작),
            // (2) /ws 구독자들. 토스 업스트림 소켓이 계정당 2개뿐이라
            // 파이썬 러너가 토스에 직접 붙을 수 없고, 대신 이 서버의 /ws를
            // 구독해 시세를 받기 때문에 체결도 흘려줘야 한다. 순서는
            // 체결 판정이 먼저다 — 내 주문이 체결된 결과까지 반영된 뒤에
            // 외부가 그 프린트를 보는 게 자연스럽다.
            onTrade = { symbol, data ->
                tradeService.onTradePrint(symbol, data.price, data.volume)
                priceSocketHandler.broadcast(symbol, data)
            },
            onOrderbook = { symbol, data ->
                orderbookStore.update(symbol, data)
                priceSocketHandler.broadcast(symbol, data)
                },
            onStatus = { status, message -> println("[STATUS] $status $message")},
        )
        feed.start()
        feed.setSymbols(listOf("005930"))
        return feed
    }
}