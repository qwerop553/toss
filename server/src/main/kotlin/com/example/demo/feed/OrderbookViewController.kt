package com.example.demo.feed

import org.springframework.stereotype.Controller
import org.springframework.web.bind.annotation.GetMapping

@Controller
class OrderbookViewController {
    @GetMapping("/orderbook")
    fun orderbook(): String = "orderbook"
}
