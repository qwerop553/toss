package com.example.demo.signal

import com.example.demo.trade.Side
import org.springframework.stereotype.Component

/**
 * 보관할 시그널 개수. 50이라는 숫자에 깊은 의미는 없다 — "무한히 쌓지
 * 않는다"가 목적이고, 이 서버는 며칠씩 떠 있을 수 있어서 상한이 없으면
 * 오래 켜 둘수록 메모리를 계속 먹는다. 시그널 하나는 문자열 몇 개짜리라
 * 50개는 사실상 공짜다.
 */
private const val CAPACITY = 50

/**
 * 최근 시그널 보관 + id 채번.
 *
 * **OrderbookStore는 ConcurrentHashMap 하나로 끝났는데 여기는 왜 @Synchronized인가:**
 * OrderbookStore가 하는 일은 "키 하나에 최신 값 덮어쓰기"라서 연산 하나가
 * 곧 원자적 단위였다. 반면 여기는 (1) 번호를 매기고 (2) 큐에 넣고 (3)
 * 넘치면 앞을 버리는 세 동작이 **한 덩어리로** 원자적이어야 한다. 번호만
 * AtomicLong으로 원자적으로 매기면, 두 스레드가 각각 1번과 2번을 받아둔
 * 채 순서가 뒤집혀 큐에는 2,1로 들어가는 상황이 생긴다. 그러면 "최근
 * 시그널"이 사실은 최근이 아니게 된다. 잠금 경합을 걱정할 필요도 없다 —
 * 시그널은 잘해야 초당 몇 건이고, 파이썬이 보내는 HTTP 요청 스레드에서만
 * 호출된다. 가장 단순한 잠금이 가장 옳은 선택인 경우다.
 *
 * nextId를 AtomicLong이 아니라 평범한 var로 둔 것도 같은 이유다. 어차피
 * 잠금 안에서만 만지므로 원자적 타입이 필요 없고, 그 사실 자체가 "채번과
 * 삽입은 같은 잠금 안에서 일어난다"는 걸 코드로 드러낸다.
 *
 * ArrayDeque인 이유: 뒤에 넣고 앞에서 버리는 링버퍼 모양이 필요한데,
 * ArrayList로 하면 removeAt(0)이 매번 전체를 앞으로 밀어야 한다(O(n)).
 * ArrayDeque는 양쪽 끝 삽입·삭제가 O(1)이라 자료구조를 새로 만들 필요가
 * 없다.
 */
@Component
class SignalStore {
    private val recent = ArrayDeque<Signal>()
    private var nextId = 1L

    /**
     * 시그널을 저장하고 id가 매겨진 결과를 돌려준다.
     * 채번은 1부터 시작해 1씩 증가한다(계약).
     */
    @Synchronized
    fun add(
        stockCode: String,
        side: Side,
        price: Long,
        strategy: String,
        timestamp: String,
        note: String?,
    ): Signal {
        val signal = Signal(nextId++, stockCode, side, price, strategy, timestamp, note)
        recent.addLast(signal)
        if (recent.size > CAPACITY) recent.removeFirst()
        return signal
    }

    /**
     * 가장 마지막 시그널. 방금 접속한 브라우저에게 스냅샷으로 한 건
     * 보내주는 데 쓴다(OrderbookStore.latest와 같은 목적).
     *
     * 지금 읽는 쪽은 최신 한 건뿐인데도 50건을 보관하는 이유: 접속 직후에
     * 지난 시그널을 전부 배너로 쏟아내면 오히려 최신 시그널이 순식간에
     * 덮여서 안 보인다. 그래서 "푸시는 최신 한 건"이고, 보관은 나중에
     * 시그널 목록 화면이나 조회 API가 붙을 때의 원천으로 남겨둔다.
     */
    @Synchronized
    fun latest(): Signal? = recent.lastOrNull()
}
