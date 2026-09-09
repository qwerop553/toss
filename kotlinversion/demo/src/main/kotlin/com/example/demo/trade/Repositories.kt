package com.example.demo.trade

import org.springframework.data.jpa.repository.JpaRepository

interface OrderRepository : JpaRepository<Order, Long> {
    /** 특정 종목의 대기 주문 — 체결 판정(onTradePrint)이 쓴다. */
    fun findByStockCodeAndStatus(stockCode: String, status: Status): List<Order>

    /** 종목 무관 전체 대기 주문 — 현금은 종목별로 나뉘지 않는 하나의 풀이라
     *  가용 현금을 계산할 땐 전 종목의 대기 매수 주문을 다 합쳐야 한다. */
    fun findByStatus(status: Status): List<Order>
}

interface HoldingRepository : JpaRepository<Holding, Long> {
    fun findByStockCode(stockCode: String): Holding?
}

interface AccountRepository : JpaRepository<Account, Long>
