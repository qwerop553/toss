package com.example.demo.trade

import jakarta.persistence.Entity
import jakarta.persistence.GeneratedValue
import jakarta.persistence.Id

/**
 * 보유 종목 하나. 평균단가는 저장하지 않는다 — 나눗셈이라 정수로 안 떨어져서
 * 매수할 때마다 반올림 오차가 누적된다. totalCost와 quantity만 저장하고,
 * 평균단가는 화면에 보여줄 때만 나눈다.
 */
@Entity
class Holding(
    val stockCode: String,
    var quantity: Long,
    var totalCost: Long,
    @Id @GeneratedValue val id: Long? = null,
)
