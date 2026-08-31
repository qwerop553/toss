# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

한국 주식 분봉 백테스팅 하네스. 토스증권 OpenAPI에서 캔들을 받아 SQLite에 쌓고, 전략을 갈아끼우며 백테스트/그리드서치를 돌린다. 아직 실매매(paper/live) 코드는 없다 (`paper.ipynb`는 빈 스케치).

주석·docstring은 한국어다. 새 코드도 한국어로 맞춰라.

## Commands

프레임워크 없음. 빌드/린트 파이프라인도 없고 `requirements.txt`도 없다 (pandas, numpy, requests, python-dotenv, matplotlib, fastapi, uvicorn, websockets가 전역 설치되어 있다).

```bash
python scrap.py 005930 000660 --interval 1m        # 캔들 수집 → market_data.db (증분)
python run.py EmaCrossStrategy --ticker 005930      # 단일 백테스트
python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
python run.py --all --ticker 005930 000660          # 전략 × 종목 순위표

python results.py                                   # 전 전략 × KOSPI50 증분 평가 + 리포트
python results.py --ticker 005930 --strategy PivotPointStrategy
python results.py --report-only                     # 계산 없이 캐시로 리포트만 재생성
python results.py --selfcheck                       # 증분 = 전량 재계산인지 검증

python -m uvicorn paper.app:app --reload            # 모의투자 웹사이트
```

`run.py`가 실행·최적화·비교를 모두 담당한다. 파일을 열어 고칠 필요 없이 플래그로 제어한다. `--optimize`는 `grids.py`의 탐색 범위로 train 그리드서치를 돌린 뒤 그 파라미터를 test 구간에 적용해 out-of-sample로 보고한다.

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

**공용 지표는 `strategies/indicators.py`에 있다.** ATR·RSI·ADX·스토캐스틱·CCI·MFI·OBV·볼린저·켈트너·돈치안·Aroon·Vortex·TRIX·강도지수·CMF·AO·궁극오실레이터·Fisher, 그리고 세션 헬퍼(`bar_dates`, `is_last_bar_of_day`, `session_vwap`, `prev_day_ohlc`)까지. 새 전략은 지표를 직접 짜지 말고 여기서 가져다 쓴다. 기존 전략(`rsi_reversion` 등)은 자기 파일 안에 지표를 갖고 있다.

**전략 자동 등록**: `strategies/__init__.py`가 `pkgutil.walk_packages`로 하위 패키지를 전부 훑어 `Strategy` 서브클래스를 `globals()`와 `__all__`에 밀어넣는다. 새 전략은 `strategies/<카테고리>/<파일>.py`에 클래스만 만들면 `from strategies import *`로 바로 잡힌다 — 수동 export 불필요. 대신 카테고리 폴더에 `__init__.py`가 있어야 하고, import 시점에 모든 전략 모듈이 실행되므로 모듈 최상단에 무거운 작업을 두면 안 된다.

**전략 카테고리**: `trend_following`(EMA/MACD/돈치안/삼중이평/DMI/슈퍼트렌드/SAR/일목/하이킨아시/Aroon/Vortex/TRIX), `mean_reversion`(볼린저/RSI/Z-Score/스토캐스틱/%R/CCI/켈트너/VWAP/ConnorsRSI2/Fisher/궁극오실레이터), `momentum`(ROC/MFI/OBV/거래량급증/강도지수/CMF/AO), `volatility`(ATR채널돌파/볼린저스퀴즈/NR7돌파), `session_based`(개장·마감 시간 규칙, ORB, 변동성 돌파, 갭 메움, 전일 피봇). 총 41개가 등록되어 있고 `python run.py --all`이 전부 돌린다.

전부 롱 온리다. `run_backtest`에 공매도 경로가 없어서(`sig == -1`은 `holdings > 0`일 때만 처리) 페어 트레이딩처럼 양방향이 필요한 전략은 엔진을 고치기 전까지 구현할 수 없다.

**워밍업 구간**: 지표 기반 전략은 `__init__`에서 `self.warmup`을 설정한다 (보통 가장 긴 지표 기간). `ewm`과 `rolling`은 초기 구간이 신뢰할 수 없어 베이스가 그만큼 신호를 0으로 누른다.

**지표의 백분위·기준선은 `expanding()`으로 계산한다.** `series.rank(pct=True)`나 `series.mean()`을 전체 구간에 걸면 아직 오지 않은 봉이 현재 봉의 값에 반영되어 lookahead bias가 생기고, 백테스트 성과가 실제보다 좋게 나온다. `ema_cross_with_adx`와 `ema_cross_with_atr` 둘 다 `atr.expanding().rank(pct=True)`와 `patr.expanding().mean().shift(1)`을 쓴다 — `shift(1)`은 기준선에서 현재 봉을 빼기 위한 것이다.

**`sharpe_ratio`/`sortino_ratio`는 표본이 0~1개면 0을 낸다.** pandas의 `std()`는 ddof=1이라 표본이 하나면 nan이고, 예전 구현의 `std() == 0` 비교로는 nan이 안 걸러져 지표가 통째로 nan이 됐다. 특히 소르티노는 하락 봉이 하나뿐인 구간에서 바로 터진다. 지금은 `not (std > 0)`으로 nan과 0을 함께 막는다 — 새 지표를 추가할 때도 같은 규칙을 따라라.

**슬리피지가 비대칭**이다: 매수 0.015%, 매도 0.215%. 매도 쪽에 거래세가 들어가 있으니 한쪽만 바꾸지 마라.

**시간 기반 전략**은 분봉 전제다. `session_close.py`는 `timestamp` 컬럼을, `opening.py`는 DatetimeIndex로 변환해서 쓴다 — 두 전략이 인덱스를 다루는 방식이 다르니 참고할 때 주의. 일봉으로는 의미가 없다.

**`max_drawdown`과 `calmar_ratio`는 `capital` 인자를 요구한다.** `equity_curve`는 자본이 아니라 0에서 시작하는 누적 손익이라, 예전처럼 `running_max`로 나누면 분모가 0을 지나가며 `-inf`가 나왔다. 지금은 투입원금(`result.max_book_size`) 대비로 계산한다 — `result.returns`와 분모가 같아서 샤프와 기준이 맞는다. 호출할 때 `max_drawdown(result.equity_curve, result.max_book_size)` 형태로 넘겨라.

## 결과 캐시 (`results.py`)

전 전략 × 전 종목을 매번 처음부터 돌리지 않기 위한 일 단위 캐시다. `run.py`와는 별개 경로이고, `run.py`는 전혀 건드리지 않았다.

**왜 이어붙일 수 있나**: `run_backtest`는 순차 시뮬레이션이고 봉과 봉 사이로 넘어가는 상태가 `holdings` 하나뿐이다. 그래서 엔진에 `holdings0` 인자를 붙여 마지막 저장 지점의 보유량을 되돌려 넣고, 누적 실현현금은 호출자(`results.evaluate`)가 `equity - holdings × close`로 복원해 더한다. 결과는 처음부터 돌린 것과 같다 — 실현현금을 뺄셈으로 복원하는 탓에 마지막 몇 비트만 달라지고, `--selfcheck`가 누적손익·체결·지표를 오차 1e-9 이내로 매번 검증한다.

**캐시 단위가 '거래일'인 이유**: `walk_forward_split`이 비율(70/30)이라 봉이 늘면 분할 지점이 앞으로 밀린다. 분할 경계로 저장하면 어제 캐시가 오늘 캐시의 앞부분이 아니게 되어 애초에 이어붙지 않는다. 저장은 날짜로 하고 train/test 분할은 **읽을 때** 날짜 목록을 잘라서 한다.

**샤프가 일별로 뭉개지지 않는 이유**: 날짜별로 봉 손익의 `합`·`제곱합`·`봉 수`를 함께 저장한다. 셋 다 가산적이라 날짜를 가로질러 더하면 봉 단위 평균·분산이 정확히 복원된다. 이게 없으면 표본이 8600개에서 12개로 줄어 숫자가 의미를 잃는다.

**MDD만 근사다.** 봉마다 누적 최고점을 들고 있어야 정확한데 그러면 캐시할 이유가 없다. 하루 안에서 고점이 저점보다 먼저 왔다고 가정한 **상한**을 낸다 — 실제 낙폭은 이보다 얕거나 같다.

**`run.py`와 숫자가 완전히 같지는 않다.** 전 구간을 끊지 않고 이어서 돌리므로 train에서 들고 있던 포지션이 test 시작 시점에 넘어온다. `run.py`는 test 슬라이스를 무포지션에서 시작한다.

**캐시 무효화**: 행마다 전략 소스 + `indicators.py` + `base.py` + `backtest_engine.py`의 mtime 최댓값(`fp`)을 박아 둔다. 코드를 고치면 그 전략의 행만 버려지고 다시 계산된다. 스키마를 바꿀 때는 `SCHEMA_VERSION`을 올리면 테이블이 통째로 재생성된다.

출력은 `results.db`(기계용, gitignore 대상), `results/report.md`(전략 순위 + 상위 5개 상세), `results/detail.csv`(전 조합). 실측: 2종목 × 41전략 콜드 37초 → 웜 6초. 전량(41전략 × 50종목 = 2050조합) 콜드 약 17분 → 웜 238초.

## 모의투자 웹사이트 (`paper/`)

    pip install fastapi uvicorn websockets     # 최초 1회
    python -m uvicorn paper.app:app --reload   # http://localhost:8000

토스 실시간 시세를 받아 브라우저에서 손으로 주문을 넣고, 체결·잔고·손익을 가짜 돈으로 추적한다. 백테스팅 하네스와는 별개 경로다 — `strategies/`, `run.py`, `results.py`를 건드리지 않는다.

**토스에는 모의투자 sandbox가 없다.** 서버가 실서버 하나뿐이라 `POST /api/v1/orders`를 부르면 실제 돈이 나간다. 그래서 `paper/toss.py`는 읽기 전용 함수만 노출하고, 코드 어디에도 주문·계좌 경로가 등장하지 않는다. 실매매가 필요해지면 별도 결정으로 다뤄라. 이 경계를 지키는 안전 점검은 문자열 검색이 아니라 **구조 검사**다: `paper/`에 GET 외의 HTTP 메서드가 없는지, 그리고 요청 헬퍼에 `orders`·`accounts` 경로가 인자로 넘어가는 자리가 없는지를 본다. 예전에는 `api/v1/orders`라는 문자열 자체를 금지했는데, 그러면 "이 엔드포인트를 부르지 마라"는 경고문이 그 문자열을 담을 수 없어 경고가 무력해졌다 — 위험한 것의 이름을 부르지 못하는 경고는 경고가 아니다.

**브라우저는 토스 웹소켓에 직접 못 붙는다.** 핸드셰이크에 `Authorization` 헤더가 필요한데 브라우저 WebSocket API는 커스텀 헤더를 못 넣고, 넣을 수 있어도 토큰이 프론트로 샌다. 그래서 백엔드가 업스트림 연결 **하나**(계정당 2개 제한)를 물고 팬아웃한다.

**상태는 `paper.db`의 `fills`에서 파생한다.** 현금·보유수량·평균단가를 따로 저장하지 않는다. 두 곳을 맞추다 어긋나면 잔고가 조용히 틀린다.

**체결 규칙**: 시장가는 호가를 다단으로 훑고 소진되면 부분체결로 끝난다(대기하지 않음). 지정가는 `pending`으로 남았다가 `trade:kr` 프린트가 지정가를 지나갈 때 채워지며, 체결가는 내 지정가가 아니라 프린트된 가격이다. 큐 포지션은 모델링하지 않아 실제보다 잘 체결된다.

**`partial`은 종료 상태다.** 부분체결된 채 아직 대기 중인 지정가는 `pending` + `filled_qty > 0`이다. 이 둘을 뭉치면 주문장에서 아직 체결될 수 있는 주문을 못 가린다.

**정규장(09:00~15:30)에서만 체결한다.** 시간외단일가는 체결 규칙이 달라 별도 엔진이 필요하므로 주문을 거부한다.

**업스트림이 끊기면 지정가 체결 판정이 멈춘다.** 조용히 두면 체결됐어야 할 주문이 왜 안 됐는지 알 수 없어서, 화면 상단에 빨간 배너를 띄운다. 이게 이 설계에서 가장 위험한 조용한 실패다.

**`tz_now()`는 절대 네트워크를 타면 안 된다.** 이전 버전은 여기서 장 캘린더 API를 불렀는데, 이 함수가 체결 프린트마다(이벤트 루프 위에서) 불리다 보니 API 호출 한 번만 실패해도 예외가 웹소켓 루프를 뚫고 나가 연결이 끊기고, 재접속마다 같은 자리에서 또 죽어 피드가 영영 살아나지 않는 무한루프가 됐다. 지금은 `datetime.now().astimezone()`만 반환한다 — 다음에 시각 관련 로직을 넣고 싶어지면 이 함수 안이 아니라 다른 곳에 넣어라.

**`app.py`의 `broker_lock`이 브로커에 대한 모든 변경을 직렬화한다.** FastAPI는 동기 `def` 핸들러를 워커 스레드에서 돌리고 피드 콜백은 이벤트 루프 위에서 도는데, 둘 다 같은 SQLite 커넥션과 같은 주문 행을 건드린다. 락이 없으면 시장가 주문이 체결 프린트 스트리밍 도중에 놓이다 `on_trade`에 중간 상태로 보여 피드가 죽을 수 있고, 지정가는 수량을 넘겨 초과체결될 수 있다. 락은 네트워크 호출을 물고 있으면 안 된다 — 걸린 채로 토스에 요청을 보내면 그 요청이 끝날 때까지 피드 콜백이 전부 멈춘다.

**`on_trade`의 조회는 `limit_price IS NOT NULL`을 반드시 걸러야 한다.** `place()`는 스윕하기 전에 대기 행을 먼저 커밋하는데, 시장가 주문의 행은 지정가가 NULL이다. 이 필터가 없으면 `on_trade`가 가격을 `None`과 비교하다 피드를 죽인다.

**`parse_event`는 절대 예외를 던지지 않는다.** 깨졌거나 일부만 온 프레임은 전부 `None`을 반환한다. 여기서 예외가 나면 웹소켓 읽기 루프 밖으로 새어나가 연결이 끊기고, 끊긴 동안에는 대기 중인 지정가 체결 판정도 멈춘다. 프레임 하나 버리는 쪽이 훨씬 싸다.

**예약금액·체결금액은 수수료까지 포함해서 계산한다.** `reserved()`와 `_validate`의 지정가 분기가 둘 다 `round(gross * FEE_RATE)`를 더하고, `_sweep_cost`도 `_record_fill`과 맞춰 호가 단마다 반올림한다. 이걸 빼먹으면 보유 현금을 정확히 다 쓰는 주문이 검증은 통과하고 잔고를 마이너스로 만든다.

테스트: `python paper/test_broker.py` (체결 엔진), `test_ticks.py`, `test_toss.py`, `test_feed.py`. 프레임워크 없이 assert 기반이다.

## 데이터

`market_data.db` (SQLite, 리포에 커밋되어 있음, 14MB). 테이블 `candles`, PK `(ticker, timeframe, timestamp)` — `INSERT OR IGNORE` 증분 수집이라 재실행해도 안전하다. `timestamp`는 TEXT로 저장되고 `load_candles`가 읽을 때 datetime으로 파싱한다.

`scrap.py`는 `.env`의 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`으로 토큰을 자동 발급·캐시한다 (만료 60초 전 갱신). 토큰 401이 아니라 **IP 미등록**으로 실패하는 경우가 많다.

## 리포 위생

`.gitignore`가 `.env`와 `__pycache__/`를 막는다. 14MB `market_data.db`는 여전히 커밋되어 있다.
