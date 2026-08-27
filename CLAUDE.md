# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

한국 주식 분봉 백테스팅 하네스. 토스증권 OpenAPI에서 캔들을 받아 SQLite에 쌓고, 전략을 갈아끼우며 백테스트/그리드서치를 돌린다. 아직 실매매(paper/live) 코드는 없다 (`paper.ipynb`는 빈 스케치).

주석·docstring은 한국어다. 새 코드도 한국어로 맞춰라.

## Commands

프레임워크 없음. 빌드/린트 파이프라인도 없고 `requirements.txt`도 없다 (pandas, numpy, requests, python-dotenv, matplotlib이 전역 설치되어 있다).

```bash
python scrap.py 005930 000660 --interval 1m        # 캔들 수집 → market_data.db (증분)
python run.py EmaCrossStrategy --ticker 005930      # 단일 백테스트
python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
python run.py --all --ticker 005930 000660          # 전략 × 종목 순위표
python test_harness.py                              # 하네스 자체 검사 (assert 기반)
python snapshot_signals.py verify                   # 전략 신호가 안 바뀌었는지 확인
```

`run.py`가 실행·최적화·비교를 모두 담당한다. 파일을 열어 고칠 필요 없이 플래그로 제어한다. `--optimize`는 `grids.py`의 탐색 범위로 train 그리드서치를 돌린 뒤 그 파라미터를 test 구간에 적용해 out-of-sample로 보고한다.

전략을 리팩터링할 때는 `python snapshot_signals.py capture`로 먼저 신호를 떠 두고, 고친 뒤 `verify`로 한 비트도 안 바뀌었는지 확인한다.

## 파이프라인

```
scrap.load_candles(ticker, interval)  →  DataFrame[timestamp, open, high, low, close, volume]
validation.walk_forward_split(df)     →  (train 70%, test 30%), 둘 다 인덱스 리셋됨
Strategy.generate_signals(df)         →  Series of {-1, 0, 1}
backtest_engine.run_backtest(df, sig) →  BacktestResult
metrics.* / print_summary.*           →  지표, 콘솔 리포트, matplotlib figure, 일별 집계
optimize.grid_search(...)             →  위 4단계를 파라미터 조합마다 반복
```

## 핵심 계약과 함정

**Strategy 인터페이스** (`strategies/base.py`): `generate_signals(df) -> Series` 하나뿐. 값은 매수 1 / 유지 0 / 매도 -1.

**신호는 상태가 아니라 이벤트다.** `run_backtest`는 1이 나올 때마다 무조건 1주를 더 산다 — 보유량 상한이 없다. 그래서 `Strategy` 베이스가 `to_signals()`로 상태머신을 한 번만 구현하고, 전략은 `entries(df)` / `exits(df)` 불리언 조건식만 쓴다. 중복 진입 차단과 워밍업 절단은 베이스가 처리한다.

쿨다운·트레일링 스톱처럼 진짜 순차 상태가 필요한 전략만 `generate_signals`를 직접 오버라이드한다 (`ema_cross_with_atr`가 유일한 예). 그 경우 중복 진입은 스스로 막아야 한다. `ema_cross.py`는 크로스 전환 시점에만 1을 내는 벡터화 구현이라 그대로 두었다.

동시 신호 규칙: 미보유면 진입이 이기고, 보유 중이면 청산이 이긴다. 마지막 봉에서 강제 청산하지 않으며, 미청산 포지션은 왕복 거래로 집계하지 않고 리포트에 따로 표시한다.

**전략 자동 등록**: `strategies/__init__.py`가 `pkgutil.walk_packages`로 하위 패키지를 전부 훑어 `Strategy` 서브클래스를 `globals()`와 `__all__`에 밀어넣는다. 새 전략은 `strategies/<카테고리>/<파일>.py`에 클래스만 만들면 `from strategies import *`로 바로 잡힌다 — 수동 export 불필요. 대신 카테고리 폴더에 `__init__.py`가 있어야 하고, import 시점에 모든 전략 모듈이 실행되므로 모듈 최상단에 무거운 작업을 두면 안 된다.

**워밍업 구간**: 지표 기반 전략은 `__init__`에서 `self.warmup`을 설정한다 (보통 가장 긴 지표 기간). `ewm`과 `rolling`은 초기 구간이 신뢰할 수 없어 베이스가 그만큼 신호를 0으로 누른다.

**슬리피지가 비대칭**이다: 매수 0.015%, 매도 0.215%. 매도 쪽에 거래세가 들어가 있으니 한쪽만 바꾸지 마라.

**시간 기반 전략**은 분봉 전제다. `session_close.py`는 `timestamp` 컬럼을, `opening.py`는 DatetimeIndex로 변환해서 쓴다 — 두 전략이 인덱스를 다루는 방식이 다르니 참고할 때 주의. 일봉으로는 의미가 없다.

**`metrics.max_drawdown`은 손익 곡선에 쓰면 `-inf`가 나온다.** `equity_curve`는 자본이 아니라 0 근처에서 시작하는 누적 손익이라 `(equity - running_max) / running_max`의 분모가 0에 가까워진다. 그래서 리포트의 MDD와 Calmar가 현재 `-inf` / `nan`이다. 아직 안 고쳤다.

## 데이터

`market_data.db` (SQLite, 리포에 커밋되어 있음, 14MB). 테이블 `candles`, PK `(ticker, timeframe, timestamp)` — `INSERT OR IGNORE` 증분 수집이라 재실행해도 안전하다. `timestamp`는 TEXT로 저장되고 `load_candles`가 읽을 때 datetime으로 파싱한다.

`scrap.py`는 `.env`의 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`으로 토큰을 자동 발급·캐시한다 (만료 60초 전 갱신). 토큰 401이 아니라 **IP 미등록**으로 실패하는 경우가 많다.

## 리포 위생

`.gitignore`가 `.env`와 `__pycache__/`를 막는다. 14MB `market_data.db`는 여전히 커밋되어 있다.
