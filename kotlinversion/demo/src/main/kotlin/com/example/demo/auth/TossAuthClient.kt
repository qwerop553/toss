package com.example.demo.auth

import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.util.LinkedMultiValueMap
import org.springframework.web.client.RestClient
import org.springframework.web.client.body
import tools.jackson.databind.json.JsonMapper
import java.time.Instant

private const val TOKEN_URL = "https://openapi.tossinvest.com/oauth2/token"
private val mapper = JsonMapper.builder().build()

/**
 * 토스 OpenAPI 액세스 토큰 발급·캐시.
 *
 * Python data/auth.py의 get_access_token()과 같은 역할을 한다. QuoteClient·
 * PricesClient가 각자 토큰을 들고 있지 않고 이 컴포넌트 하나를 주입받아
 * accessToken()을 부르게 하는 이유: 캐시(언제 발급했고 언제 만료되는지)가
 * 한 곳에만 있어야 한다. 두 클라이언트가 각자 캐시를 들고 있으면, 한쪽만
 * 갱신되고 다른 쪽은 만료된 토큰을 계속 쓰는 식으로 어긋날 수 있다.
 *
 * @Component로 등록해 Spring이 애플리케이션 전체에 이 인스턴스 하나만
 * 만들게 한다(싱글턴) — 그래야 "캐시가 하나"라는 전제가 실제로 지켜진다.
 */
@Component
class TossAuthClient {
    // 생성자 파라미터로 안 받고 생성 시점에 바로 읽는 이유: 이 값들은
    // 프로세스가 떠 있는 동안 바뀌지 않는 정적인 설정이라(.env를 앱
    // 실행 중에 고쳐도 다시 안 읽는다), 매번 다시 조회할 이유가 없다.
    // .env를 못 찾거나 키가 없으면 여기서 즉시 실패해서, 앱이 시작하자마자
    // "설정이 잘못됐다"를 바로 알 수 있게 한다 — 첫 API 호출 때가 돼서야
    // 실패하면 원인 추적이 더 어렵다.
    private val env = EnvFile.load()
    private val clientId = env["TOSS_CLIENT_ID"] ?: error(".env에 TOSS_CLIENT_ID가 없습니다")
    private val clientSecret = env["TOSS_CLIENT_SECRET"] ?: error(".env에 TOSS_CLIENT_SECRET이 없습니다")

    // 토큰 발급 URL은 QuoteClient/PricesClient가 쓰는 base-url(.../api/v1)과
    // 호스트는 같지만 경로가 다르다. 그쪽 RestClient(baseUrl 고정)를
    // 재사용하지 않고 별도 인스턴스를 만드는 이유는, 이 클래스가 그
    // 클라이언트들의 존재를 몰라도 되게(의존 방향을 안 만들게) 하기
    // 위해서다 — 인증은 시세 조회보다 아래 계층에 있어야 한다.
    private val client = RestClient.create()

    private var cachedToken: String? = null
    private var expiresAt: Instant = Instant.EPOCH

    /**
     * 캐시된 토큰이 있고 아직 유효하면 재사용, 없거나 만료됐으면 재발급한다.
     *
     * @Synchronized인 이유: 이 빈은 싱글턴이라 여러 요청 스레드(FastAPI의
     * 워커 스레드에 대응하는, Spring MVC의 요청 처리 스레드들)가 동시에
     * accessToken()을 부를 수 있다. 잠금이 없으면 두 스레드가 동시에
     * "만료됐네"를 보고 토큰을 두 번 발급받을 수 있다 — 틀린 결과를
     * 내는 건 아니지만 불필요한 API 호출이고, 토큰 발급 자체에도 호출
     * 제한이 있을 수 있어 피하는 게 안전하다.
     */
    @Synchronized
    fun accessToken(): String {
        cachedToken?.let { token -> if (Instant.now().isBefore(expiresAt)) return token }
        val (token, expiresInSeconds) = issueToken()
        cachedToken = token
        // 만료 60초 전에 미리 갱신되도록 여유를 둔다. 정확히 만료 시점에
        // 걸쳐 요청하면, 요청이 서버에 도달했을 땐 이미 만료돼 거부당할
        // 수 있다.
        expiresAt = Instant.now().plusSeconds(expiresInSeconds - 60)
        return token
    }

    private fun issueToken(): Pair<String, Long> {
        val form = LinkedMultiValueMap<String, String>().apply {
            add("grant_type", "client_credentials")
            add("client_id", clientId)
            add("client_secret", clientSecret)
        }
        val body = client.post()
            .uri(TOKEN_URL)
            .contentType(MediaType.APPLICATION_FORM_URLENCODED)
            .body(form)
            .retrieve()
            .body<String>()
            ?: error("토큰 발급 응답이 비어 있습니다")

        val json = mapper.readTree(body)
        // access_token은 반드시 있어야 하므로 없으면 즉시 실패(error).
        // expires_in은 없으면 1시간으로 가정한다 — 토스 API 문서 기준
        // 기본값이고, python 버전의 expires_in 기본값과 동일하게 맞춘다.
        val accessToken = json.get("access_token")?.asString()
            ?: error("응답에 access_token이 없습니다")
        val expiresIn = json.get("expires_in")?.asLong() ?: 3600L
        return accessToken to expiresIn
    }
}
