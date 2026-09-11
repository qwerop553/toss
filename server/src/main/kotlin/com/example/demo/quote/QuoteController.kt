package com.example.demo.quote

import org.springframework.stereotype.Controller
import org.springframework.ui.Model
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.client.HttpClientErrorException
import org.springframework.web.client.RestClientException

@Controller
class QuoteController(private val quoteClient: QuoteClient) {

    @GetMapping("/quote")
    fun quote(@RequestParam(required = false) code: String?, model: Model): String {
        model.addAttribute("code", code)
        if (code.isNullOrBlank()) return "quote"

        try {
            model.addAttribute("quote", quoteClient.quote(code))
        } catch (e: HttpClientErrorException.NotFound) {
            model.addAttribute("error", "종목을 찾을 수 없습니다: $code")
        } catch (e: IllegalStateException) {
            // 상한가라 매도호가가 없거나, 장 마감이라 호가창이 비어 있는 경우
            model.addAttribute("error", "지금은 호가가 없습니다.")
        } catch (e: RestClientException) {
            model.addAttribute("error", "시세를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        }
        return "quote"
    }
}
