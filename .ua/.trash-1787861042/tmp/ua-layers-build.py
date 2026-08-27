# -*- coding: utf-8 -*-
"""Phase 2 결과를 layers.json으로 쓰고, 28개 노드가 정확히 한 번씩만 배정됐는지 검증한다."""
import json
import sys

LAYERS = [
    {
        "id": "layer:entry",
        "name": "실행 진입점",
        "description": "run.py 단일 CLI가 캔들 로드부터 walk-forward 분할, 신호 생성, 백테스트, 리포트까지 파이프라인 전체를 플래그로 엮어 실행하며, paper.ipynb는 아직 내용이 비어 있는 실매매 스케치다.",
        "nodeIds": [
            "file:run.py",
            "file:paper.ipynb",
        ],
    },
    {
        "id": "layer:data",
        "name": "데이터 레이어",
        "description": "토스증권 OpenAPI에서 분봉 캔들을 받아 SQLite candles 테이블에 증분 적재하고, 미래 구간이 학습에 새지 않도록 시계열을 train/test로 잘라 주는 데이터 공급 단계다.",
        "nodeIds": [
            "file:scrap.py",
            "table:scrap.py:candles",
            "file:validation.py",
        ],
    },
    {
        "id": "layer:strategy",
        "name": "전략 레이어",
        "description": "Strategy 베이스의 entries/exits 상태머신 위에 추세추종·평균회귀·장 시간 기반 전략을 얹고, pkgutil barrel이 하위 패키지를 훑어 전략을 자동 등록한다.",
        "nodeIds": [
            "file:strategies/__init__.py",
            "file:strategies/base.py",
            "file:strategies/mean_reversion/__init__.py",
            "file:strategies/mean_reversion/bollinger_band.py",
            "file:strategies/mean_reversion/rsi_reversion.py",
            "file:strategies/session_based/__init__.py",
            "file:strategies/session_based/opening.py",
            "file:strategies/session_based/session_close.py",
            "file:strategies/trend_following/__init__.py",
            "file:strategies/trend_following/ema_cross.py",
            "file:strategies/trend_following/ema_cross_with_adx.py",
            "file:strategies/trend_following/ema_cross_with_atr.py",
        ],
    },
    {
        "id": "layer:backtest-core",
        "name": "백테스트 코어",
        "description": "신호 시리즈를 비대칭 슬리피지 기준으로 체결 시뮬레이션하는 엔진과, 그 위에서 파라미터 조합마다 백테스트를 반복하는 범용 그리드서치 및 전략별 탐색 범위 선언을 담는다.",
        "nodeIds": [
            "file:backtest_engine.py",
            "file:optimize.py",
            "file:grids.py",
        ],
    },
    {
        "id": "layer:reporting",
        "name": "평가 및 리포팅",
        "description": "백테스트 결과에서 샤프·소르티노·MDD·칼마와 거래 통계를 계산하고, 이를 콘솔 요약과 matplotlib 손익 그래프, 일별 집계 형태로 사람이 읽게 뽑아 준다.",
        "nodeIds": [
            "file:metrics.py",
            "file:print_summary.py",
        ],
    },
    {
        "id": "layer:test",
        "name": "검증 도구",
        "description": "pytest 없이 assert만으로 하네스 전 구간을 훑는 자체 검사와, 리팩터링 전후 전략 신호가 한 비트도 달라지지 않았는지 확인하는 골든 스냅샷 도구로 구성된 회귀 방어선이다.",
        "nodeIds": [
            "file:test_harness.py",
            "file:snapshot_signals.py",
        ],
    },
    {
        "id": "layer:documentation",
        "name": "문서 및 프로젝트 설정",
        "description": "사실상 README 역할을 하는 CLAUDE.md 아키텍처 문서와 하네스 재설계 계획·설계 명세, 그리고 Claude Code 플러그인 설정을 묶은 비코드 자료다.",
        "nodeIds": [
            "document:CLAUDE.md",
            "document:docs/superpowers/plans/2026-08-28-backtest-harness.md",
            "document:docs/superpowers/specs/2026-08-28-backtest-harness-design.md",
            "config:.claude/settings.json",
        ],
    },
]

inp, outp = sys.argv[1], sys.argv[2]
expected = {n["id"] for n in json.load(open(inp, encoding="utf-8"))["fileNodes"]}
assigned = [i for lay in LAYERS for i in lay["nodeIds"]]

assert len(assigned) == len(set(assigned)), "중복 배정된 노드가 있다"
assert set(assigned) == expected, f"누락 {expected - set(assigned)} / 미지 {set(assigned) - expected}"
assert 3 <= len(LAYERS) <= 10, "레이어 개수가 범위를 벗어났다"
assert all(lay["nodeIds"] for lay in LAYERS), "빈 레이어가 있다"

json.dump(LAYERS, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok:", len(LAYERS), "layers,", len(assigned), "nodes ==", len(expected))
for lay in LAYERS:
    print(" ", lay["id"], len(lay["nodeIds"]))
