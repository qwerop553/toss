package com.example.demo.trade

import jakarta.persistence.Entity
import jakarta.persistence.Id

/** 로그인이 없어서 계정은 항상 id=1L 한 행뿐이다. */
@Entity
class Account(
    var cashBalance: Long,
    @Id val id: Long,
)
