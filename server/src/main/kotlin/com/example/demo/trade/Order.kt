package com.example.demo.trade

import jakarta.persistence.Entity
import jakarta.persistence.EnumType
import jakarta.persistence.Enumerated
import jakarta.persistence.GeneratedValue
import jakarta.persistence.Id
import jakarta.persistence.Table
import java.time.Instant

enum class Side { BUY, SELL }

/**
 * 부분체결(PARTIAL)이 없다 — TradeService.onTradePrint가 지정가를 크로스한
 * 프린트 하나로 항상 전량을 채우기 때문이다(파이썬 paper/broker.py와 같은
 * 단순화: 큐 포지션을 모델링하지 않아 실제보다 잘 체결된다).
 */
enum class Status { PENDING, FILLED, CANCELLED }

/**
 * 지정가 주문 하나.
 *
 * 테이블명을 명시적으로 "orders"로 지정한다 — 클래스명 그대로 두면 H2가
 * "order"를 SQL 예약어(ORDER BY)로 읽어서 모든 쿼리가 문법 오류로 깨진다.
 */
@Entity
@Table(name = "orders")
class Order(
    val stockCode: String,
    @Enumerated(EnumType.STRING) val side: Side,
    val limitPrice: Long,
    val quantity: Long,
    @Enumerated(EnumType.STRING) var status: Status,
    val createdAt: Instant,
    @Id @GeneratedValue val id: Long? = null,
)
