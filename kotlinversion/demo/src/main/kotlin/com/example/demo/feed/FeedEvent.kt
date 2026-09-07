package com.example.demo.feed

import tools.jackson.databind.JsonNode
import tools.jackson.databind.json.JsonMapper

/*
 * 파싱과 구독 선언 직렬화를 TossFeedClient 밖으로 뺀 이유:
 * 이 파일의 함수들은 전부 순수 함수(같은 입력엔 항상 같은 출력, 소켓·스레드
 * 같은 상태를 전혀 갖지 않는다)다. 그래서 실제 웹소켓을 열지 않고도
 * "이 문자열이 들어오면 이런 결과가 나와야 한다"를 그대로 단위 테스트할 수
 * 있다. 반대로 연결 수립, 재연결 타이밍, 콜백 스레드 같은 "상태가 있고
 * 시간에 따라 달라지는" 부분은 TossFeedClient에만 남겨서, 그쪽은 목(mock)
 * 없이는 테스트하기 어렵다는 걸 명확히 구분해 둔다.
 */

// JsonMapper는 스레드 세이프하고 생성 비용이 있으므로(내부에 스키마 캐시 등을
// 들고 있음) 요청마다 새로 만들지 않고 파일 전체가 공유하는 싱글턴으로 둔다.
// QuoteClient.kt/PricesClient.kt와 같은 패턴이다.
private val mapper = JsonMapper.builder().build()

/**
 * 체결(trade) 프린트 한 건.
 *
 * price·volume은 토스 원문 JSON에서 숫자가 아니라 문자열로 온다
 * ("price": "70000"처럼). 여기서 Long으로 변환해 두지 않으면 이 값을 쓰는
 * 쪽(체결 판정, 분봉 집계)이 전부 문자열 비교를 하게 되고, "9" > "10"이
 * 참이 되는 식으로 조용히 틀린 결과를 낸다. 그래서 이 경계(파싱 지점)에서
 * 한 번만 확실하게 숫자로 바꿔 둔다.
 *
 * timestamp는 nullable이다 — 토스가 이 필드를 안 줄 수도 있는데, 없다고
 * 프레임 전체를 버릴 이유는 없어서(체결가·거래량만으로도 쓸모가 있다)
 * 필수값으로 만들지 않았다.
 */
data class TradeData(val price: Long, val volume: Long, val timestamp: String?)

/** 호가 한 단(하나의 가격대와 그 가격에 쌓인 수량). asks/bids 배열의 원소 하나에 대응한다. */
data class OrderbookLevel(val price: Long, val volume: Long)

/**
 * 호가창 스냅샷 한 번.
 *
 * asks/bids의 배열 순서를 신뢰하지 않는다 — 실제로 확인해 보면 asks는
 * 내림차순으로 온다(즉 asks[0]이 최우선 매도호가가 아니라 가장 비싼
 * 호가다). 여기서 순서를 가정하고 첫 원소를 집으면 API가 정렬을 바꾸는
 * 순간 조용히 틀린 호가로 체결하게 된다. 그래서 "최우선 호가가 뭔가"는
 * 이 데이터 클래스가 정하지 않고, 그걸 쓰는 쪽이 min/max로 직접 계산하게
 * 미룬다.
 */
data class OrderbookData(val asks: List<OrderbookLevel>, val bids: List<OrderbookLevel>)

/**
 * parseEvent가 원문 프레임에서 뽑아낸, "우리가 관심 있는" 이벤트 하나.
 *
 * sealed interface로 만든 이유: 이 타입을 소비하는 쪽(TossFeedClient.dispatch)의
 * when 식이 Trade/Orderbook 두 케이스를 전부 처리했는지를 컴파일 타임에
 * 강제할 수 있다. 나중에 세 번째 이벤트 종류가 늘어나면, dispatch의 when에
 * 분기를 안 추가한 순간 컴파일이 깨져서 "새 이벤트 종류를 처리 안 하고
 * 빠뜨렸다"는 실수를 실행 전에 잡아준다. 일반 enum이나 문자열 태그로
 * 했다면 이 보장이 없다.
 */
sealed interface FeedEvent {
    data class Trade(val symbol: String, val data: TradeData) : FeedEvent
    data class Orderbook(val symbol: String, val data: OrderbookData) : FeedEvent
}

/**
 * 수신 프레임(원문 텍스트 하나)을 FeedEvent로 바꾼다.
 * 관심 없는 프레임(우리가 구독 안 한 타입, 시스템 메시지 등)이거나
 * 일부만 온(필드가 빠졌거나 깨진) 프레임은 null을 반환한다.
 *
 * **이 함수는 절대 예외를 던지지 않는다.** 이게 이 파일에서 가장 중요한
 * 규칙이다. 이유:
 *   TossFeedClient.dispatch는 이 함수의 반환값(FeedEvent? 이거나 null)만
 *   보고 콜백을 부른다. 만약 여기서 예외가 새어 나가면, 그 예외는
 *   WebSocket.Listener.onText 콜백 안에서 잡히지 않은 채 그대로 던져지고,
 *   JDK 웹소켓 구현은 그런 리스너 예외를 보면 연결 자체를 닫아버린다.
 *   즉 프레임 하나가 이상하게 생겼다는 이유로 전체 시세 연결이 끊기는
 *   것이다. 끊긴 동안에는 지정가 체결 판정 같은 실시간 로직이 전부
 *   멈추는데, 그게 이 설계에서 가장 비싼 실패다. 그러니 "프레임 하나를
 *   조용히 버리는 것"이 압도적으로 싼 선택이고, 그걸 강제하기 위해
 *   함수 전체를 try/catch로 감싼다.
 */
fun parseEvent(raw: String): FeedEvent? {
    // 1단계: JSON 자체가 깨졌으면(불완전한 텍스트, 잘못된 인코딩 등) 여기서 끝.
    // readTree가 던지는 예외 타입을 일일이 나열하지 않고 Exception으로
    // 넓게 잡는 이유는, "이 프레임을 이해할 수 없다"는 결론이 예외의
    // 정확한 종류와 무관하게 항상 같기 때문이다(어차피 버릴 거라 종류를
    // 구분해서 다르게 처리할 필요가 없다).
    val msg = try {
        mapper.readTree(raw)
    } catch (e: Exception) {
        return null
    }

    // "type"이 없거나 "message"가 아니면 우리가 다루는 프레임이 아니다
    // (예: 구독 성공/실패를 알리는 제어 메시지, ack 등). msg.get("type")이
    // null이면 그 자리에서 바로 함수를 빠져나간다 — 이 ?: return null은
    // 람다 안이 아니라 함수 본문에 직접 있는 non-local return이라 여기서
    // parseEvent 자체를 끝낸다.
    if ((msg.get("type") ?: return null).asString() != "message") return null

    // topic은 "channel:market:symbol" 형태의 콜론 구분 문자열이다
    // (예: "trade:kr:005930"). 형식이 다르면(길이가 3이 아니거나 시장이
    // "kr"이 아니면) 우리가 처리할 수 있는 프레임이 아니다.
    val parts = (msg.get("topic") ?: return null).asString().split(":")
    if (parts.size != 3 || parts[1] != "kr") return null   // 미국 주식은 이 사이트의 범위 밖이다
    val channel = parts[0]
    val symbol = parts[2]
    val data = msg.get("data") ?: return null

    // 2단계: 필드 하나하나를 꺼내다가 없거나(null) 숫자로 안 바뀌면
    // requiredLong/levels가 예외를 던진다. 그 예외를 여기서 다시 한번
    // 잡아서 null로 바꾼다 — "타입은 message고 topic도 맞는데 data 내부가
    // 이상한" 경우까지 함께 방어하기 위한 두 번째 try/catch다.
    return try {
        when (channel) {
            "trade" -> FeedEvent.Trade(
                symbol,
                TradeData(
                    price = requiredLong(data, "price"),
                    volume = requiredLong(data, "volume"),
                    timestamp = data.get("timestamp")?.asString(),
                ),
            )
            "orderbook" -> FeedEvent.Orderbook(
                symbol,
                OrderbookData(asks = levels(data, "asks"), bids = levels(data, "bids")),
            )
            // channel이 trade/orderbook 둘 다 아니면 우리가 구독한 적 없는
            // 채널이 온 것이므로 조용히 버린다. 이 자리가 나중에 세 번째
            // 채널(예: 체결강도)을 추가할 진입점이다.
            else -> null
        }
    } catch (e: Exception) {
        null   // 필드가 빠졌거나 숫자가 아니어도 이 프레임 하나만 버리고 연결은 계속 산다
    }
}

// node.get(field)는 필드가 없으면 null을 준다. 이게 중요한 이유는,
// Jackson의 다른 API인 path(field)는 필드가 없어도 "빈 노드"를 반환하고,
// 그 빈 노드에 asLong()을 부르면 예외 대신 0을 준다는 함정이 있기
// 때문이다(설계 문서에 이미 적힌 함정). 그러면 "필드가 원래 없는 것"과
// "필드 값이 진짜 0인 것"이 구분이 안 돼서, 예를 들어 가격 필드 이름을
// 오타 내도 에러 없이 "0원 체결"이 조용히 만들어진다. get()을 쓰고 null을
// 직접 체크해서 error()를 던지면, 위쪽의 try/catch가 그 error를 잡아
// 프레임 전체를 버리게 되므로 이 함정을 피할 수 있다.
private fun requiredLong(node: JsonNode, field: String): Long =
    (node.get(field) ?: error("$field 없음")).asString().toLong()

// asks/bids 배열 하나를 OrderbookLevel 리스트로. Kotlin의 Iterable.map
// 확장 함수를 쓰고 싶었지만, JsonNode가 자기 나름의 map 멤버 함수를 갖고
// 있어서 그쪽이 먼저 선택되는 바람에 타입이 안 맞았다(컴파일 에러로 발견).
// 그래서 QuoteClient.kt가 이미 쓰고 있던 "for (level in node)" 스타일로
// 통일했다 — 이 코드베이스에서 이미 검증된 패턴을 그대로 재사용하는 것이,
// 라이브러리의 API 함정을 새로 하나씩 알아가는 것보다 안전하다.
private fun levels(data: JsonNode, field: String): List<OrderbookLevel> {
    val node = data.get(field) ?: error("$field 없음")
    val result = ArrayList<OrderbookLevel>()
    for (level in node) {
        result += OrderbookLevel(price = requiredLong(level, "price"), volume = requiredLong(level, "volume"))
    }
    return result
}

/**
 * 구독 선언 메시지를 JSON 문자열로 만든다.
 *
 * 이 프로토콜은 "구독 추가/삭제"라는 개념이 없고 **full-replace**다 —
 * 연결을 새로 열 때든, 관심종목이 바뀔 때든, 매번 "지금부터 구독할 종목
 * 전체 목록"을 통째로 다시 선언해야 한다. 그래서 symbols가 빈 리스트로
 * 들어오면 trade/orderbook 채널 선언 자체를 아예 안 보내고, 그 결과
 * "id만 있는" 선언이 나가는데, 이게 바로 "전부 구독 해제"라는 뜻이 된다
 * (선언 안 된 채널은 서버가 더 이상 안 보낸다).
 *
 * reqId를 파라미터로 받는 이유: 같은 심볼 목록이라도 호출할 때마다 다른
 * id를 넣어야 서버가 "이건 새 선언이다"라고 구분한다. 호출자(TossFeedClient)가
 * 매번 증가하는 값을 넣어 준다.
 */
fun buildDeclaration(symbols: List<String>, reqId: String): String {
    // ArrayNode/ObjectNode를 직접 조립하는 이유: DTO 클래스를 새로 만들면
    // "id만 있는 원소"와 "type+codes가 있는 원소"가 서로 다른 모양이라
    // 하나의 리스트 타입으로 묶기 애매하다(sealed class를 또 만들어야
    // 함). 어차피 한 번 조립해서 보내고 끝나는 값이라, 트리를 직접
    // 만드는 쪽이 타입 하나 더 늘리는 것보다 싸다 — QuoteClient.kt가
    // 응답을 읽을 때 DTO 대신 readTree를 쓰는 것과 같은 이유의 반대쪽
    // (쓰기) 버전이다.
    val root = mapper.createArrayNode()
    root.addObject().put("id", reqId)
    if (symbols.isNotEmpty()) {
        // trade와 orderbook, 두 채널을 "같은 종목 리스트"로 각각 따로
        // 선언한다. 하나로 합쳐 보낼 수 있는 프로토콜이 아니다.
        root.addObject().apply {
            put("type", "trade:kr")
            putArray("codes").apply { symbols.forEach { add(it) } }
        }
        root.addObject().apply {
            put("type", "orderbook:kr")
            putArray("codes").apply { symbols.forEach { add(it) } }
        }
    }
    return mapper.writeValueAsString(root)
}
