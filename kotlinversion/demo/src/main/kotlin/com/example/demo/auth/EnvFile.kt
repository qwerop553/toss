package com.example.demo.auth

import java.io.File

// 저장소 최상위(.env가 있는 곳)까지 몇 단계나 거슬러 올라갈지의 상한.
// kotlinversion/demo에서 저장소 루트까지는 2단계(demo -> kotlinversion -> toss)
// 지만, Gradle/IntelliJ가 앱을 어디서 실행하느냐에 따라 시작 위치가 달라질
// 수 있어 여유 있게 6단계까지 찾아본다. 못 찾으면 무한 루프 대신 확실히
// 실패하도록 상한을 둔다.
private const val MAX_PARENT_LEVELS = 6

/**
 * 저장소 최상위 .env 파일 파서.
 *
 * 왜 필요한가:
 *   Spring은 application.properties나 OS 환경변수는 읽어도 .env 파일
 *   포맷 자체는 모른다. 이 저장소의 .env는 pythonversion과 kotlinversion이
 *   함께 쓰는 위치(저장소 최상위)에 있고, 시크릿(TOSS_CLIENT_ID/
 *   TOSS_CLIENT_SECRET)을 거기 하나에만 두는 이유는 그 파일 하나만
 *   .gitignore에 걸면 두 버전 다 안전해지기 때문이다(실제로 루트
 *   .gitignore에 이미 .env가 걸려 있다).
 *
 * 왜 별도 라이브러리(spring-dotenv 등)를 안 쓰는가:
 *   포맷이 "KEY=VALUE" 줄 몇 개뿐이라 파싱에 라이브러리가 필요할 정도로
 *   복잡하지 않다. 의존성 하나를 새로 끌어오는 비용이 이 몇 줄짜리 파싱
 *   로직보다 크다.
 */
object EnvFile {

    /**
     * 현재 작업 디렉토리에서 시작해 위로 올라가며 .env를 찾아 파싱한다.
     *
     * 작업 디렉토리 기준 고정 상대경로("../../.env")를 하드코딩하지 않는
     * 이유: 앱을 저장소 루트에서 실행하는지, kotlinversion/demo 모듈
     * 디렉토리에서 실행하는지(Gradle/IntelliJ의 기본값)에 따라 실제 시작
     * 위치가 달라질 수 있다. 위로 몇 단계 찾아 올라가는 쪽이 실행 방식이
     * 바뀌어도 깨지지 않는다.
     */
    fun load(): Map<String, String> {
        var dir: File? = File(".").canonicalFile
        repeat(MAX_PARENT_LEVELS) {
            val candidate = File(dir, ".env")
            if (candidate.isFile) return parse(candidate)
            dir = dir?.parentFile
        }
        error(
            ".env 파일을 찾을 수 없습니다. 저장소 최상위에 " +
                "TOSS_CLIENT_ID/TOSS_CLIENT_SECRET을 담은 .env가 있어야 합니다."
        )
    }

    // 주석(#으로 시작)과 빈 줄은 건너뛴다. value 쪽에 "="이 또 들어있을 수
    // 있으니(예: base64 값) split의 limit을 2로 줘서 첫 번째 "="에서만 자른다.
    private fun parse(file: File): Map<String, String> =
        file.readLines()
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") && it.contains("=") }
            .associate { line ->
                val (key, value) = line.split("=", limit = 2)
                key.trim() to value.trim()
            }
}
