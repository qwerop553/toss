package com.example.demo.signal

import com.example.demo.trade.Side

/**
 * 파이썬 전략 프로세스가 보내온 매매 시그널 한 건.
 *
 * **Side를 새로 만들지 않고 trade.Side를 그대로 재사용한다.** trade 패키지에
 * 있다고 해서 그게 "주문 전용" 타입인 건 아니다 — Side는 BUY/SELL 두 값만
 * 가진 순수 enum이고, JPA 애노테이션은 Side 자체가 아니라 그걸 쓰는 Order
 * 엔티티 쪽(@Enumerated)에 붙어 있다. 즉 이 enum을 import한다고 signal
 * 패키지가 JPA나 영속성에 엮이지 않는다. 반대로 signal.Side를 따로 만들면
 * "같은 의미인데 타입만 다른" enum이 두 개가 되고, 나중에 시그널을 실제
 * 주문으로 넘기는 순간(이 프로젝트의 방향상 거의 확실하다) 두 enum 사이를
 * 오가는 변환 함수가 필요해진다. 그 변환 함수가 지금 감수하는 패키지
 * 의존 한 줄보다 훨씬 지저분하다.
 *
 * **timestamp를 OffsetDateTime이 아니라 String으로 들고 있는 이유:**
 * 우리는 이 값을 계산에 쓰지 않는다. 컨트롤러가 형식이 ISO-8601인지만
 * 검증하고, 브라우저로는 파이썬이 보낸 문자열을 글자 그대로 되돌려준다.
 * OffsetDateTime으로 파싱해서 보관하면 직렬화할 때 Jackson이 어떤 모양으로
 * 쓸지(오프셋을 유지할지, UTC로 바꿀지, 밀리초를 붙일지)를 또 따져야 하고,
 * 그러다 보면 "파이썬이 보낸 시각"과 "브라우저가 보는 시각"의 문자열이
 * 미묘하게 달라진다. 계약이 요구하는 건 그냥 그대로 흘려보내는 것이므로,
 * 파싱 결과를 버리는 쪽이 오히려 계약에 충실하다.
 *
 * **note가 nullable인 이유:** 계약상 note는 선택 필드이고, 없으면 필드
 * 자체가 생략되어 온다. 여기서 빈 문자열("")로 정규화하지 않는 건, 아래
 * 단계(브라우저 푸시)에서 "note가 없으면 필드 자체를 생략"해야 하는데
 * ""와 null을 구분해 두지 않으면 그 판단을 할 수 없기 때문이다.
 */
data class Signal(
    val id: Long,
    val stockCode: String,
    val side: Side,
    val price: Long,
    val strategy: String,
    val timestamp: String,
    val note: String?,
)
