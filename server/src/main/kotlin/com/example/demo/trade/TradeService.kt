package com.example.demo.trade

import org.springframework.stereotype.Service
import org.springframework.transaction.annotation.Transactional
import java.time.Instant

private const val ACCOUNT_ID = 1L
private const val STARTING_CASH = 100_000_000L

/**
 * 매수·매도의 단일 진입점. 검증(현금·보유수량)부터 잔고·보유·주문 갱신까지
 * 이 클래스 하나가 책임진다 — 화면마다 규칙이 복제되면 언젠가 한 군데가
 * 어긋난다는 게 원래 설계서의 전제였고, 지정가가 들어와도 같은 이유가
 * 적용된다.
 */
@Service
class TradeService(
    private val accountRepository: AccountRepository,
    private val holdingRepository: HoldingRepository,
    private val orderRepository: OrderRepository,
) {
    // placeOrder(브라우저 요청을 받는 Tomcat 스레드)와 onTradePrint(피드
    // 콜백 스레드)가 같은 Account/Holding/Order 행을 동시에 건드릴 수 있다.
    // 이 객체 하나로 두 진입점을 직렬화한다 — 파이썬 버전의 broker_lock과
    // 같은 이유다. 락 안에서 하는 일이 전부 로컬 H2 DB 작업뿐이라(네트워크
    // 호출 없음) 오래 붙들고 있어도 다른 요청을 심각하게 막지 않는다.
    private val lock = Any()

    @Transactional
    fun placeOrder(stockCode: String, side: Side, price: Long, quantity: Long): Order = synchronized(lock) {
        require(price > 0) { "가격은 0보다 커야 합니다." }
        require(quantity > 0) { "수량은 0보다 커야 합니다." }

        when (side) {
            Side.BUY -> {
                // 현금은 종목별로 나뉘지 않는 하나의 풀이라, 이미 대기 중인
                // 다른 매수 주문들이 써 버릴 몫(reservedCash)을 먼저 빼야
                // 같은 돈으로 주문을 두 번 넣는 걸 막을 수 있다.
                val available = account().cashBalance - reservedCash()
                require(available >= price * quantity) {
                    "현금이 부족합니다 (가용 ${available}원, 필요 ${price * quantity}원)."
                }
            }
            Side.SELL -> {
                val holding = holdingRepository.findByStockCode(stockCode)?.quantity ?: 0L
                val available = holding - reservedQuantity(stockCode)
                require(available >= quantity) {
                    "보유 수량이 부족합니다 (가용 ${available}주, 필요 ${quantity}주)."
                }
            }
        }

        return orderRepository.save(
            Order(
                stockCode = stockCode,
                side = side,
                limitPrice = price,
                quantity = quantity,
                status = Status.PENDING,
                createdAt = Instant.now(),
            )
        )
    }

    /**
     * TossFeedClient의 onTrade 콜백이 체결(trade) 프린트를 받을 때마다
     * 부른다. 이 종목의 대기 주문 중 이 프린트로 크로스된 것들을 전량
     * 체결시킨다(부분체결 없음 — Status 참고).
     */
    @Transactional
    fun onTradePrint(stockCode: String, price: Long, volume: Long) {
        synchronized(lock) {
            val pending = orderRepository.findByStockCodeAndStatus(stockCode, Status.PENDING)
            for (order in pending) {
                val crossed = when (order.side) {
                    Side.BUY -> price <= order.limitPrice   // 내가 낼 수 있는 가격 이하로 거래됨
                    Side.SELL -> price >= order.limitPrice  // 내가 받고 싶은 가격 이상으로 거래됨
                }
                if (crossed) fill(order, price)
            }
        }
    }

    // 이 함수를 밖으로 안 여는 이유: onTradePrint 안에서만 불리는데, 만약
    // 여기에 @Transactional을 달면(그리고 밖에서 직접 부른다면) Spring의
    // AOP 프록시는 "같은 객체 안에서의 호출(self-invocation)"엔 안 걸려서
    // 그 어노테이션이 조용히 무시된다. 그래서 트랜잭션은 진입점인
    // onTradePrint 하나에만 걸어 두고, fill은 그 트랜잭션 안에서 실행되는
    // 평범한 내부 헬퍼로 둔다.
    private fun fill(order: Order, fillPrice: Long) {
        val account = account()
        // 체결가는 내 지정가가 아니라 프린트된 가격이다 — 지정가보다
        // 유리하게 체결될 수 있다는 뜻이고, 이것도 파이썬 버전과 같다.
        val gross = fillPrice * order.quantity
        when (order.side) {
            Side.BUY -> {
                account.cashBalance -= gross
                val holding = holdingRepository.findByStockCode(order.stockCode)
                    ?: Holding(stockCode = order.stockCode, quantity = 0, totalCost = 0)
                holding.quantity += order.quantity
                holding.totalCost += gross
                holdingRepository.save(holding)
            }
            Side.SELL -> {
                account.cashBalance += gross
                val holding = holdingRepository.findByStockCode(order.stockCode)
                    ?: error("매도 체결인데 보유 종목이 없습니다: ${order.stockCode}")
                // totalCost를 수량 비율만큼 차감한다 — 평균단가를 저장하지
                // 않는 설계와 짝이다. 정수 나눗셈이라 소수점 이하는 버려진다.
                holding.totalCost -= holding.totalCost * order.quantity / holding.quantity
                holding.quantity -= order.quantity
                holdingRepository.save(holding)
            }
        }
        accountRepository.save(account)
        order.status = Status.FILLED
        orderRepository.save(order)
    }

    private fun reservedCash(): Long =
        orderRepository.findByStatus(Status.PENDING)
            .filter { it.side == Side.BUY }
            .sumOf { it.limitPrice * it.quantity }

    private fun reservedQuantity(stockCode: String): Long =
        orderRepository.findByStockCodeAndStatus(stockCode, Status.PENDING)
            .filter { it.side == Side.SELL }
            .sumOf { it.quantity }

    // 로그인이 없어 계정을 만드는 화면이 없으므로, 처음 쓰이는 순간
    // 시작 현금으로 계정을 만들어 둔다.
    private fun account(): Account =
        accountRepository.findById(ACCOUNT_ID).orElseGet {
            accountRepository.save(Account(id = ACCOUNT_ID, cashBalance = STARTING_CASH))
        }
}
