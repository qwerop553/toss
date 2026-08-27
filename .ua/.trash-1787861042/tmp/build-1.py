# -*- coding: utf-8 -*-
import json

N = []
E = []

def n(id, type, name, summary, tags, complexity, filePath=None, lineRange=None, languageNotes=None):
    d = {"id": id, "type": type, "name": name}
    if filePath: d["filePath"] = filePath
    if lineRange: d["lineRange"] = lineRange
    d["summary"] = summary; d["tags"] = tags; d["complexity"] = complexity
    if languageNotes: d["languageNotes"] = languageNotes
    N.append(d)

def e(s, t, ty, w):
    if s == t: return
    E.append({"source": s, "target": t, "type": ty, "direction": "forward", "weight": w})

# ---------- file nodes ----------
n("file:backtest_engine.py", "file", "backtest_engine.py",
  "신호 시리즈를 받아 1주 단위로 체결을 시뮬레이션하는 백테스트 엔진. 비대칭 슬리피지(매수 0.015% / 매도 0.215%)를 반영해 누적 손익, 보유량, 거래 원장, 벤치마크를 담은 BacktestResult를 만든다.",
  ["backtest-engine", "simulation", "core", "data-model"], "moderate", filePath="backtest_engine.py",
  languageNotes="dataclass로 결과 스키마를 고정하고, 체결 루프만 파이썬 for문으로 남긴 뒤 나머지 집계는 pandas 벡터 연산으로 처리한다.")

n("file:grids.py", "file", "grids.py",
  "전략별 그리드서치 탐색 범위(GRIDS)와 무효 조합 필터(VALID)를 모아 둔 선언적 설정 모듈. 전략 코드를 순수하게 유지하려고 어느 범위를 뒤질지만 이 파일 한 곳에 분리했다.",
  ["configuration", "optimization", "parameter-grid", "declarative"], "simple", filePath="grids.py",
  languageNotes="함수와 클래스가 없는 순수 데이터 모듈이라 import 시점 부작용이 없다. VALID의 값은 파라미터 dict를 받아 bool을 돌려주는 lambda다.")

n("file:metrics.py", "file", "metrics.py",
  "백테스트 결과를 평가하는 성과지표 모음. 샤프, 소르티노, MDD, 칼마 비율과 거래 통계(승률, 손익비, 미청산 포지션 분리)를 계산한다.",
  ["metrics", "statistics", "utility", "evaluation"], "moderate", filePath="metrics.py",
  languageNotes="MDD와 칼마는 equity_curve가 0에서 시작하는 누적 손익이라 running_max로 나누면 분모가 0을 지나며 -inf가 나온다. 그래서 투입원금(capital)을 별도 인자로 요구한다.")

n("file:optimize.py", "file", "optimize.py",
  "전략에 종속되지 않는 범용 그리드서치 모듈. 파라미터 조합마다 전략을 만들어 백테스트를 돌리고, 선택한 지표 기준으로 정렬된 순위표와 최적 파라미터를 돌려준다.",
  ["optimization", "grid-search", "hyperparameter", "factory"], "moderate", filePath="optimize.py",
  languageNotes="strategy_factory 콜백과 itertools.product 조합으로 전략 종류에 무관하게 동작한다. mdd는 작을수록 좋으므로 부호를 반전해 최대화 문제로 통일한다.")

n("file:print_summary.py", "file", "print_summary.py",
  "백테스트 결과를 사람이 읽는 형태로 뽑아 주는 리포팅 모듈. 콘솔 요약 출력, matplotlib 손익/보유량 그래프, 일별 집계 DataFrame 세 가지를 제공한다.",
  ["reporting", "visualization", "console-output", "aggregation"], "moderate", filePath="print_summary.py",
  languageNotes="BacktestResult를 타입 힌트용으로만 쓰지 않고 실제로 import한다. PEP 649 지연 annotation 평가에 기대면 하위 버전에서 NameError가 나기 때문이다.")

n("file:run.py", "file", "run.py",
  "실행, 자동 최적화, 전략 비교를 모두 담당하는 통합 CLI 진입점. 캔들 로드에서 walk-forward 분할, 신호 생성, 백테스트, 리포트까지 이어지는 파이프라인을 argparse 플래그로 제어한다.",
  ["entry-point", "cli", "orchestration", "pipeline"], "complex", filePath="run.py",
  languageNotes="--optimize는 train 구간에서만 그리드서치를 돌리고 그 파라미터를 test 구간에 적용해 out-of-sample로 보고한다. 같은 데이터로 튜닝하고 성과를 자랑하는 자기기만을 막는 구조다.")

n("file:strategies/__init__.py", "file", "__init__.py",
  "strategies 패키지의 전략 자동 등록 barrel. pkgutil.walk_packages로 하위 모듈을 전부 훑어 Strategy 서브클래스를 globals(), __all__, REGISTRY에 동적으로 밀어넣는다.",
  ["entry-point", "barrel", "registry", "plugin-loader"], "simple", filePath="strategies/__init__.py",
  languageNotes="정적 import가 아니라 런타임 반영(importlib + inspect.getmembers)이라 새 전략은 파일만 추가하면 잡힌다. 대신 import 시점에 모든 전략 모듈이 실행되므로 모듈 최상단에 무거운 작업을 두면 안 된다.")

n("file:test_harness.py", "file", "test_harness.py",
  "pytest 없이 assert만으로 하네스 전체를 검증하는 자체 검사 스크립트. 신호 상태머신, 슬리피지 체결가, 거래 통계, 일별 집계, MDD/칼마 유한성, 전략 레지스트리, 그리드 정합성을 훑는다.",
  ["test", "assertion-based", "regression-check", "self-check"], "complex", filePath="test_harness.py",
  languageNotes="테스트 함수 이름이 한국어이고, _run_all이 globals()를 훑어 test_로 시작하는 함수를 자동 수집한다. 테스트 러너 의존성 없이 등록 누락을 방지하는 방식이다.")

n("file:validation.py", "file", "validation.py",
  "시계열 데이터를 train/test로 시간 순서대로 자르는 walk-forward 분할 헬퍼. 미래 구간이 학습에 섞이지 않도록 무작위 셔플 없이 앞뒤로만 나눈다.",
  ["utility", "validation", "data-split", "time-series"], "simple", filePath="validation.py")

# ---------- function / class nodes ----------
n("class:backtest_engine.py:BacktestResult", "class", "BacktestResult",
  "백테스트 한 회차의 산출물을 담는 dataclass. 비용 차감 전후 손익곡선, 총 슬리피지 비용, 보유량, 최대 투입원금, 거래 원장, 수익률, 벤치마크(첫날 매수 후 마지막날 매도) 결과를 한 덩어리로 묶는다.",
  ["data-model", "dataclass", "result-container"], "simple", filePath="backtest_engine.py", lineRange=[17, 28])
n("function:backtest_engine.py:run_backtest", "function", "run_backtest",
  "신호 시리즈를 순회하며 1이면 1주 매수, -1이면 전량 매도로 체결을 시뮬레이션한다. 매수와 매도에 서로 다른 슬리피지를 적용해 체결가를 만들고 현금흐름, 보유량, 거래 원장을 누적해 BacktestResult로 반환한다.",
  ["backtest-engine", "simulation", "core", "slippage"], "complex", filePath="backtest_engine.py", lineRange=[31, 112])

n("function:metrics.py:sharpe_ratio", "function", "sharpe_ratio",
  "수익률 시리즈의 평균을 표준편차로 나눈 뒤 연율화해 샤프 비율을 계산한다.",
  ["metrics", "statistics", "risk-adjusted-return"], "simple", filePath="metrics.py", lineRange=[4, 7])
n("function:metrics.py:sortino_ratio", "function", "sortino_ratio",
  "하방 변동성(음수 수익률의 표준편차)만 분모로 써서 소르티노 비율을 계산한다. 상방 변동을 위험으로 치지 않는다는 점이 샤프와 다르다.",
  ["metrics", "statistics", "downside-risk"], "simple", filePath="metrics.py", lineRange=[9, 13])
n("function:metrics.py:max_drawdown", "function", "max_drawdown",
  "누적 손익곡선의 고점 대비 최대 낙폭을 투입원금(capital) 기준으로 계산한다. capital을 분모로 쓰는 이유는 equity_curve가 0에서 시작해 running_max로 나누면 -inf가 나오기 때문이다.",
  ["metrics", "risk", "drawdown"], "simple", filePath="metrics.py", lineRange=[15, 29])
n("function:metrics.py:calmar_ratio", "function", "calmar_ratio",
  "연율화 수익률을 최대낙폭으로 나눈 칼마 비율을 계산한다. max_drawdown과 같은 capital 기준을 써서 샤프와 분모를 맞춘다.",
  ["metrics", "risk-adjusted-return", "drawdown"], "simple", filePath="metrics.py", lineRange=[31, 49])
n("function:metrics.py:trade_stats", "function", "trade_stats",
  "거래 원장에서 매수와 매도를 짝지어 왕복 거래 단위 통계를 뽑는다. 승률, 평균 손익, 손익비, 평균 보유 봉 수를 계산하고 미청산 포지션은 왕복에서 제외해 따로 보고한다.",
  ["metrics", "trade-analysis", "aggregation", "statistics"], "complex", filePath="metrics.py", lineRange=[51, 112])

n("class:optimize.py:OptimizationResult", "class", "OptimizationResult",
  "그리드서치 산출물을 담는 dataclass. 최적 파라미터, 그때의 점수, 모든 조합의 성능을 지표 기준으로 정렬한 순위표 DataFrame을 보관한다.",
  ["data-model", "dataclass", "optimization"], "simple", filePath="optimize.py", lineRange=[14, 17])
n("function:optimize.py:grid_search", "function", "grid_search",
  "파라미터 조합을 itertools.product로 펼쳐 조합마다 전략을 만들고 백테스트를 돌린 뒤 선택한 지표로 점수를 매긴다. valid_combo로 무효 조합을 건너뛰고 정렬된 순위표와 최고 파라미터를 반환한다.",
  ["optimization", "grid-search", "hyperparameter", "core"], "complex", filePath="optimize.py", lineRange=[29, 89])

n("function:print_summary.py:print_summary", "function", "print_summary",
  "BacktestResult를 콘솔 리포트로 출력한다. 손익, 비용, 거래 통계, 위험조정지표, 벤치마크 대비 성과를 한 화면에 정리한다.",
  ["reporting", "console-output", "formatting"], "moderate", filePath="print_summary.py", lineRange=[11, 52])
n("function:print_summary.py:plot_backtest", "function", "plot_backtest",
  "matplotlib으로 가격과 매매 시점 산점도, 손익곡선과 보유량을 2단 서브플롯으로 그린다. 분봉 정수 인덱스를 사람이 읽는 시각 라벨로 바꿔 x축에 얹는다.",
  ["visualization", "matplotlib", "reporting"], "moderate", filePath="print_summary.py", lineRange=[55, 91])
n("function:print_summary.py:to_daily_summary", "function", "to_daily_summary",
  "분봉 단위 결과를 날짜별로 groupby해 일별 종가 기준 자산, 손익, 보유량, 거래 횟수 표를 만든다.",
  ["aggregation", "reporting", "time-series"], "moderate", filePath="print_summary.py", lineRange=[93, 128])

n("function:run.py:run_one", "function", "run_one",
  "전략 하나를 종목 하나에 돌리는 핵심 실행 단위. 캔들 로드, walk-forward 분할, 선택적 train 그리드서치, test 구간 백테스트 순서로 진행하고 (test df, 결과, 사용 파라미터, 순위표)를 반환한다.",
  ["orchestration", "pipeline", "core", "walk-forward"], "moderate", filePath="run.py", lineRange=[28, 68])
n("function:run.py:cmd_single", "function", "cmd_single",
  "단일 전략과 단일 종목 실행 서브커맨드. run_one 결과를 콘솔 요약, --plot 그래프 저장, --daily 일별 표로 풀어낸다.",
  ["cli", "command-handler", "reporting"], "moderate", filePath="run.py", lineRange=[71, 101])
n("function:run.py:cmd_compare", "function", "cmd_compare",
  "--all 모드에서 등록된 모든 전략과 종목 조합을 돌려 샤프, MDD, 거래 통계를 모은 순위표를 출력한다.",
  ["cli", "command-handler", "comparison", "leaderboard"], "moderate", filePath="run.py", lineRange=[104, 138])
n("function:run.py:main", "function", "main",
  "argparse로 CLI 인자를 파싱하고 --all 여부에 따라 cmd_single 또는 cmd_compare로 분기하는 진입점.",
  ["entry-point", "cli", "argparse"], "moderate", filePath="run.py", lineRange=[141, 173])

n("function:validation.py:walk_forward_split", "function", "walk_forward_split",
  "DataFrame을 train_ratio 비율로 앞뒤 두 구간으로 자르고 각각 인덱스를 리셋해 반환한다. 셔플하지 않아 시간 순서가 보존된다.",
  ["utility", "data-split", "time-series", "validation"], "simple", filePath="validation.py", lineRange=[3, 7])

n("function:test_harness.py:test_trade_stats_손으로_계산한_값과_일치", "function", "test_trade_stats_손으로_계산한_값과_일치",
  "손으로 계산한 왕복 거래 손익, 승률, 손익비 기대값과 trade_stats 출력이 정확히 일치하는지 검증하는 골든 테스트.",
  ["test", "assertion-based", "metrics-validation"], "moderate", filePath="test_harness.py", lineRange=[107, 126])
n("function:test_harness.py:test_daily_summary_일별_손익", "function", "test_daily_summary_일별_손익",
  "여러 날에 걸친 분봉 데이터로 to_daily_summary가 날짜별 손익과 거래 횟수를 올바르게 집계하는지 확인한다.",
  ["test", "assertion-based", "aggregation-validation"], "moderate", filePath="test_harness.py", lineRange=[151, 175])
n("function:test_harness.py:_run_all", "function", "_run_all",
  "globals()를 훑어 test_로 시작하는 함수를 전부 모아 순서대로 실행하는 미니 테스트 러너. 테스트를 새로 만들어도 별도 등록이 필요 없다.",
  ["test", "test-runner", "entry-point", "reflection"], "simple", filePath="test_harness.py", lineRange=[234, 241])

# ---------- imports (1:1, 19 total) ----------
IMPORTS = {
    "backtest_engine.py": [], "grids.py": [], "metrics.py": [],
    "optimize.py": ["backtest_engine.py", "metrics.py"],
    "print_summary.py": ["backtest_engine.py", "metrics.py"],
    "run.py": ["backtest_engine.py", "grids.py", "metrics.py", "optimize.py",
               "print_summary.py", "scrap.py", "strategies/__init__.py", "validation.py"],
    "strategies/__init__.py": ["strategies/base.py"],
    "test_harness.py": ["backtest_engine.py", "grids.py", "metrics.py",
                        "print_summary.py", "strategies/__init__.py", "strategies/base.py"],
    "validation.py": [],
}
_imp = 0
for src, tgts in IMPORTS.items():
    for t in tgts:
        e("file:" + src, "file:" + t, "imports", 0.7)
        _imp += 1
assert _imp == sum(len(v) for v in IMPORTS.values()) == 19, _imp

# ---------- contains ----------
for nd in N:
    if nd["type"] in ("function", "class"):
        e("file:" + nd["filePath"], nd["id"], "contains", 1.0)

# ---------- exports ----------
EXPORTS = [
    ("backtest_engine.py", "class:backtest_engine.py:BacktestResult"),
    ("backtest_engine.py", "function:backtest_engine.py:run_backtest"),
    ("metrics.py", "function:metrics.py:sharpe_ratio"),
    ("metrics.py", "function:metrics.py:sortino_ratio"),
    ("metrics.py", "function:metrics.py:max_drawdown"),
    ("metrics.py", "function:metrics.py:calmar_ratio"),
    ("metrics.py", "function:metrics.py:trade_stats"),
    ("optimize.py", "class:optimize.py:OptimizationResult"),
    ("optimize.py", "function:optimize.py:grid_search"),
    ("print_summary.py", "function:print_summary.py:print_summary"),
    ("print_summary.py", "function:print_summary.py:plot_backtest"),
    ("print_summary.py", "function:print_summary.py:to_daily_summary"),
    ("run.py", "function:run.py:run_one"),
    ("run.py", "function:run.py:cmd_single"),
    ("run.py", "function:run.py:cmd_compare"),
    ("run.py", "function:run.py:main"),
    ("validation.py", "function:validation.py:walk_forward_split"),
]
for f, t in EXPORTS:
    e("file:" + f, t, "exports", 0.8)

# ---------- calls ----------
CALLS = [
    ("function:optimize.py:grid_search", "function:backtest_engine.py:run_backtest"),
    ("function:optimize.py:grid_search", "function:metrics.py:sharpe_ratio"),
    ("function:optimize.py:grid_search", "function:metrics.py:sortino_ratio"),
    ("function:optimize.py:grid_search", "function:metrics.py:max_drawdown"),
    ("function:optimize.py:grid_search", "function:metrics.py:calmar_ratio"),
    ("function:print_summary.py:print_summary", "function:metrics.py:sharpe_ratio"),
    ("function:print_summary.py:print_summary", "function:metrics.py:sortino_ratio"),
    ("function:print_summary.py:print_summary", "function:metrics.py:max_drawdown"),
    ("function:print_summary.py:print_summary", "function:metrics.py:calmar_ratio"),
    ("function:print_summary.py:print_summary", "function:metrics.py:trade_stats"),
    ("function:metrics.py:calmar_ratio", "function:metrics.py:max_drawdown"),
    ("function:run.py:run_one", "function:backtest_engine.py:run_backtest"),
    ("function:run.py:run_one", "function:optimize.py:grid_search"),
    ("function:run.py:run_one", "function:validation.py:walk_forward_split"),
    ("function:run.py:run_one", "function:scrap.py:load_candles"),
    ("function:run.py:cmd_single", "function:run.py:run_one"),
    ("function:run.py:cmd_single", "function:print_summary.py:print_summary"),
    ("function:run.py:cmd_single", "function:print_summary.py:plot_backtest"),
    ("function:run.py:cmd_single", "function:print_summary.py:to_daily_summary"),
    ("function:run.py:cmd_single", "function:metrics.py:max_drawdown"),
    ("function:run.py:cmd_single", "function:metrics.py:trade_stats"),
    ("function:run.py:cmd_compare", "function:run.py:run_one"),
    ("function:run.py:cmd_compare", "function:metrics.py:sharpe_ratio"),
    ("function:run.py:cmd_compare", "function:metrics.py:max_drawdown"),
    ("function:run.py:cmd_compare", "function:metrics.py:trade_stats"),
    ("function:run.py:main", "function:run.py:cmd_single"),
    ("function:run.py:main", "function:run.py:cmd_compare"),
    ("function:test_harness.py:_run_all", "function:test_harness.py:test_trade_stats_손으로_계산한_값과_일치"),
    ("function:test_harness.py:_run_all", "function:test_harness.py:test_daily_summary_일별_손익"),
    ("function:test_harness.py:test_daily_summary_일별_손익", "function:print_summary.py:to_daily_summary"),
    ("function:test_harness.py:test_daily_summary_일별_손익", "function:backtest_engine.py:run_backtest"),
    ("function:test_harness.py:test_trade_stats_손으로_계산한_값과_일치", "function:metrics.py:trade_stats"),
]
for s, t in CALLS:
    e(s, t, "calls", 0.8)

# ---------- tested_by (production -> test) ----------
for p in ["backtest_engine.py", "metrics.py", "print_summary.py", "grids.py",
          "strategies/__init__.py", "strategies/base.py"]:
    e("file:" + p, "file:test_harness.py", "tested_by", 0.5)

# ---------- dynamic strategy registration (pkgutil.walk_packages) ----------
for m in ["strategies/mean_reversion/__init__.py", "strategies/mean_reversion/bollinger_band.py",
          "strategies/mean_reversion/rsi_reversion.py",
          "strategies/session_based/__init__.py", "strategies/session_based/opening.py",
          "strategies/session_based/session_close.py",
          "strategies/trend_following/__init__.py", "strategies/trend_following/ema_cross.py",
          "strategies/trend_following/ema_cross_with_adx.py",
          "strategies/trend_following/ema_cross_with_atr.py"]:
    e("file:strategies/__init__.py", "file:" + m, "depends_on", 0.6)

# grids.py keys reference strategy class names resolved through the registry
e("file:grids.py", "file:strategies/__init__.py", "related", 0.5)

ids = [x["id"] for x in N]
assert len(ids) == len(set(ids)), "duplicate node ids"
node_ids = set(ids)
with open(".ua/intermediate/batch-1.json", "w", encoding="utf-8") as f:
    json.dump({"nodes": N, "edges": E}, f, ensure_ascii=False, indent=2)
print("nodes", len(N), "edges", len(E), "imports", _imp)
