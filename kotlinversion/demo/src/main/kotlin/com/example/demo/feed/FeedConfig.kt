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
            onTrade = { symbol, data -> tradeService.onTradePrint(symbol, data.price, data.volume) },
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