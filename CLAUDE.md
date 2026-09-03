# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

토스증권 OpenAPI 기반 한국 주식 **모의투자 웹사이트**(`paper/`)와, 전략을 검증하는 분봉 **백테스팅 하네스**(`backtest/`). 중심은 모의투자 쪽이다. 실매매(live) 코드는 없고, 넣어서도 안 된다 — 아래 `paper/` 절의 sandbox 부재 경고를 읽어라.

```
toss/
├── paper/          모의투자 웹앱 (FastAPI + 체결 시뮬레이션). 프로젝트의 중심
│   ├── app.py broker.py feed.py toss.py ticks.py
│   ├── static/index.html
│   └── tests/                 assert 기반, 네트워크 없이 돈다
├── backtest/       백테스팅 하네스
│   ├── engine.py metrics.py optimize.py validation.py report.py grids.py
│   └── run.py results.py      CLI 진입점
├── strategies/     전략 56개 + indicators.py (paper·backtest가 공유)
├── data/           candles.py(수집·조회) auth.py(토큰) tickers.py (양쪽 공유)
└── docs/
```

`strategies/`와 `data/`가 두 패키지 바깥에 있는 이유: 전략을 골라 자동매매를 붙일 때 `paper/`가 `backtest/`를 거치지 않고 전략을 직접 import할 수 있어야 한다. **`paper/`는 `backtest/`를 import하지 않는다** — 이 방향을 뒤집지 마라.

`data/auth.py`를 `data/candles.py`에서 떼어 둔 이유도 같다. candles는 pandas·sqlite를 끌고 오는데, `paper/`는 토큰만 필요하다.

주석·docstring은 한국어다. 새 코드도 한국어로 맞춰라.

## Commands

프레임워크 없음. 빌드/린트 파이프라인도 없고 `requirements.txt`도 없다 (pandas, numpy, requests, python-dotenv, matplotlib, fastapi, uvicorn, websockets가 전역 설치되어 있다).

```bash
python -m data.candles 005930 000660 --interval 1m   # 캔들 수집 → market_data.db (증분)
python -m data.candles --kospi50 --check             # tickers.KOSPI50 종목코드 유효성만 확인
python -m data.candles --kospi50 --interval 1m       # 50종목 전량 수집 (1시간 이상)
python -m backtest.run EmaCrossStrategy --ticker 005930      # 단일 백테스트
python -m backtest.run EmaCrossStrategy --ticker 005930 --optimize --plot --daily
python -m backtest.run EmaCrossStrategy --ticker 005930 --full   # walk-forward 없이 전 구간 (in-sample)
python -m backtest.run --all --ticker 005930 000660          # 전략 × 종목 순위표

python -m backtest.results                                   # 전 전략 × KOSPI50 증분 평가 + 리포트
python -m backtest.results --ticker 005930 --strategy PivotPointStrategy
python -m backtest.results --report-only                     # 계산 없이 캐시로 리포트만 재생성
python -m backtest.results --selfcheck                       # 증분 = 전량 재계산인지 검증

python -m data.candles --kospi50 --interval 1d       # 일봉 수집 (몇 분이면 끝난다)
python -m backtest.run Alpha006Strategy --ticker 005930 --interval 1d   # 정식 알파는 일봉으로 본다

python -m uvicorn paper.app:app --reload            # 모의투자 웹사이트
```

`backtest/run.py`가 실행·최적화·비교를 모두 담당한다. 파일을 열어 고칠 필요 없이 플래그로 제어한다. `--optimize`는 `backtest/grids.py`의 탐색 범위로 train 그리드서치를 돌린 뒤 그 파라미터를 test 구간에 적용해 out-of-sample로 보고한다.

## 파이프라인

```
data.candles.load_candles(ticker, interval)  →  DataFrame[timestamp, open, high, low, close, volume]
backtest.validation.walk_forward_split(df)     →  (train 70%, test 30%), 둘 다 인덱스 리셋됨
Strategy.generate_signals(df)         →  Series of {-1, 0, 1}
backtest.engine.run_backtest(df, sig) →  BacktestResult
backtest.metrics / backtest.report           →  지표, 콘솔 리포트, matplotlib figure, 일별 집계
backtest.optimize.grid_search(...)             →  위 4단계를 파라미터 조합마다 반복
```

## 핵심 계약과 함정

**Strategy 인터페이스** (`strategies/base.py`): `generate_signals(df) -> Series` 하나뿐. 값은 매수 1 / 유지 0 / 매도 -1.

**신호는 상태가 아니라 이벤트다.** `run_backtest`는 1이 나올 때마다 무조건 1주를 더 산다 — 보유량 상한이 없다. 그래서 `Strategy` 베이스가 `to_signals()`로 상태머신을 한 번만 구현하고, 전략은 `entries(df)` / `exits(df)` 불리언 조건식만 쓴다. 중복 진입 차단과 워밍업 절단은 베이스가 처리한다.

쿨다운·트레일링 스톱처럼 진짜 순차 상태가 필요한 전략만 `generate_signals`를 직접 오버라이드한다 (`ema_cross_with_atr`가 유일한 예). 그 경우 중복 진입은 스스로 막아야 한다. `ema_cross.py`는 크로스 전환 시점에만 1을 내는 벡터화 구현이라 그대로 두었다.

동시 신호 규칙: 미보유면 진입이 이기고, 보유 중이면 청산이 이긴다. 마지막 봉에서 강제 청산하지 않으며, 미청산 포지션은 왕복 거래로 집계하지 않고 리포트에 따로 표시한다.

**공용 지표는 `strategies/indicators.py`에 있다.** ATR·RSI·ADX·스토캐스틱·CCI·MFI·OBV·볼린저·켈트너·돈치안·Aroon·Vortex·TRIX·강도지수·CMF·AO·궁극오실레이터·Fisher, 그리고 세션 헬퍼(`bar_dates`, `bar_of_day`, `day_open`, `is_last_bar_of_day`, `session_vwap`, `prev_day_ohlc`)까지. 새 전략은 지표를 직접 짜지 말고 여기서 가져다 쓴다. 기존 전략(`rsi_reversion` 등)은 자기 파일 안에 지표를 갖고 있다.

**전략 자동 등록**: `strategies/__init__.py`가 `pkgutil.walk_packages`로 하위 패키지를 전부 훑어 `Strategy` 서브클래스를 `globals()`와 `__all__`에 밀어넣는다. **`inspect.isabstract`인 클래스는 뺀다** — 전략 모듈이 자기 중간 베이스를 import하면 `inspect.getmembers`가 그 베이스도 잡아서 전략으로 등록해 버리고, `--all`이 그걸 인스턴스화하다 터진다(`Strategy` 자신은 `obj is not Strategy`로 이미 빠지지만 `formulaic.base.FormulaicAlpha` 같은 중간 베이스는 그 조건에 안 걸린다). 중간 베이스를 만들 때는 확장점에 `@abstractmethod`를 붙여라 — 그게 '이건 전략이 아니라 뼈대다'라고 말하는 방법이다. 모듈명이 `base`면 walk 자체에서도 빠진다(`_EXCLUDED`). 새 전략은 `strategies/<카테고리>/<파일>.py`에 클래스만 만들면 `from strategies import *`로 바로 잡힌다 — 수동 export 불필요. 대신 카테고리 폴더에 `__init__.py`가 있어야 하고, import 시점에 모든 전략 모듈이 실행되므로 모듈 최상단에 무거운 작업을 두면 안 된다.

**전략 카테고리**: `trend_following`(EMA/MACD/돈치안/삼중이평/DMI/슈퍼트렌드/SAR/일목/하이킨아시/Aroon/Vortex/TRIX), `mean_reversion`(볼린저/RSI/Z-Score/스토캐스틱/%R/CCI/켈트너/VWAP/ConnorsRSI2/Fisher/궁극오실레이터), `momentum`(ROC/MFI/OBV/거래량급증/강도지수/CMF/AO), `volatility`(ATR채널돌파/볼린저스퀴즈/NR7돌파), `session_based`(개장·마감 시간 규칙, ORB, 변동성 돌파, 갭 메움, 전일 피봇, 갭 하락 개장 페이드, 오후 VWAP 회복, 갭 상승 페이드 회복), `formulaic`(WorldQuant 101 알파 중 5개), `microstructure`(스프레드·유동성·주문흐름 추정량). 총 56개가 등록되어 있고 `python -m backtest.run --all`이 전부 돌린다.

**분봉 알파는 거래당 23bp를 넘겨야 존재한다.** 슬리피지가 매수 0.015% + 매도 0.215%라 왕복 23bp가 고정으로 나간다. 기존 41개 전략의 결과를 `거래당 비용 전 총수익`으로 다시 세워 보면 이 선을 넘는 건 세션 계열 몇 개뿐이고, 지표 크로스오버 계열은 총수익이 양수여도 거래 수에 비용을 곱하는 순간 전부 죽는다. 새 전략을 평가할 때 수익률·샤프보다 먼저 볼 숫자는 `총수익 / 왕복 수`다 — 이 값이 23bp 근처면 표본이 늘었을 때 뒤집힌다.

**오후 되돌림 전략군** (`AfternoonOversold`, `AfternoonRangeBottom`, `AfternoonVwapRecovery`, `GapUpFadeRecovery`, `GapDownOpenFade`)은 1분봉 이벤트 스터디에서 나왔다. 공통 형태는 '개장 후 N봉 이후에 진입 → 그날 마지막 봉에 청산, 오버나잇 없음'이다. 가장 민감한 파라미터는 임계값이 아니라 **진입 허용 시각(`after_bar`)**이고, 눌림을 사는 셋은 늦을수록(≈13:30) 좋아지고 회복을 사는 `AfternoonVwapRecovery`만 이를수록(≈12:00) 좋아진다. 중간 손절을 달면 알파가 사라진다 — 이 알파는 진입 조건이 아니라 '진입부터 종가까지'라는 구간에 붙어 있다(`afternoon_vwap_recovery.py` 참고).

다섯 중 종목 out-of-sample까지 통과한 것은 둘뿐이다. 거래당 비용 전 총수익(왕복비용 23bp) 기준:

| 전략 | 튜닝에 쓴 30종목 | 안 쓴 20종목 | 종목양수 | 판정 |
|---|---|---|---|---|
| `GapUpFadeRecovery` | +51.6bp (t=4.7) | +65.9bp (t=5.1) | 90% | 통과 |
| `AfternoonRangeBottom` | +49.5bp (t=4.8) | +46.9bp (t=4.3) | 85% | 통과 |
| `AfternoonOversold` | +36.8bp (t=4.8) | +24.1bp (t=3.7) | 55% | 경계선(비용 후 본전) |
| `GapDownOpenFade` | +37.7bp (t=3.2) | +25.6bp (t=1.8) | 45% | 탈락 |
| `AfternoonVwapRecovery` | +32.9bp (t=4.0) | +12.1bp (t=1.5) | 35% | 탈락 |

**전략 검증은 종목축으로 갈라라. 시간축(train/test)은 이 데이터에서 OOS 구실을 못 한다.** 거래일이 종목당 28일뿐이라 뒤 30%는 8~9일이고, 그 구간에 시장이 반등하면 전략 품질과 무관하게 거의 모든 전략의 test 숫자가 좋아진다 — 실제로 `OpeningRangeBreakout`은 train −44.9bp / test +22.0bp로 뒤집힌다. 종목을 갈라 재는 쪽은 이런 공통 요인이 양쪽에 똑같이 걸려서 상쇄된다.

**이벤트 스터디 숫자는 실현 엣지의 두 배쯤으로 나온다.** 스터디는 조건을 만족한 '모든 봉'을 평균하는데 전략은 그날의 '첫 봉'에서만 산다. 눌림이 깊을수록 조건이 오래 참이라 스터디는 더 극단적인 지점들을 함께 세고, 전략은 그 구간의 가장 이른 지점에 붙는다. 스터디에서 23bp를 겨우 넘는 조건은 전략으로 만들면 반드시 죽는다 — 후보를 거를 때 문턱을 두 배로 잡아라.

**`bars_left` 같은 '그날 총 봉 수' 기반 조건은 lookahead다.** 하루의 봉 개수는 장이 끝나야 확정되므로 오후 진입 조건에 쓰면 미래를 보는 셈이 된다. 마감 직전 진입을 막고 싶으면 `bar_of_day(df) <= max_entry_bar`처럼 순번 상한으로 잘라라. `strategies/tests/test_session_alpha.py`의 truncation invariance 검사가 이걸 잡는다.

전부 롱 온리다. `run_backtest`에 공매도 경로가 없어서(`sig == -1`은 `holdings > 0`일 때만 처리) 페어 트레이딩처럼 양방향이 필요한 전략은 엔진을 고치기 전까지 구현할 수 없다.

**워밍업 구간**: 지표 기반 전략은 `__init__`에서 `self.warmup`을 설정한다 (보통 가장 긴 지표 기간). `ewm`과 `rolling`은 초기 구간이 신뢰할 수 없어 베이스가 그만큼 신호를 0으로 누른다.

**지표의 백분위·기준선은 `expanding()`으로 계산한다.** `series.rank(pct=True)`나 `series.mean()`을 전체 구간에 걸면 아직 오지 않은 봉이 현재 봉의 값에 반영되어 lookahead bias가 생기고, 백테스트 성과가 실제보다 좋게 나온다. `ema_cross_with_adx`와 `ema_cross_with_atr` 둘 다 `atr.expanding().rank(pct=True)`와 `patr.expanding().mean().shift(1)`을 쓴다 — `shift(1)`은 기준선에서 현재 봉을 빼기 위한 것이다.

**`sharpe_ratio`/`sortino_ratio`는 표본이 0~1개면 0을 낸다.** pandas의 `std()`는 ddof=1이라 표본이 하나면 nan이고, 예전 구현의 `std() == 0` 비교로는 nan이 안 걸러져 지표가 통째로 nan이 됐다. 특히 소르티노는 하락 봉이 하나뿐인 구간에서 바로 터진다. 지금은 `not (std > 0)`으로 nan과 0을 함께 막는다 — 새 지표를 추가할 때도 같은 규칙을 따라라.

**슬리피지가 비대칭**이다: 매수 0.015%, 매도 0.215%. 매도 쪽에 거래세가 들어가 있으니 한쪽만 바꾸지 마라.

**시간 기반 전략**은 분봉 전제다. `session_close.py`는 `timestamp` 컬럼을, `opening.py`는 DatetimeIndex로 변환해서 쓴다 — 두 전략이 인덱스를 다루는 방식이 다르니 참고할 때 주의. 일봉으로는 의미가 없다.

**`max_drawdown`과 `calmar_ratio`는 `capital` 인자를 요구한다.** `equity_curve`는 자본이 아니라 0에서 시작하는 누적 손익이라, 예전처럼 `running_max`로 나누면 분모가 0을 지나가며 `-inf`가 나왔다. 지금은 투입원금(`result.max_book_size`) 대비로 계산한다 — `result.returns`와 분모가 같아서 샤프와 기준이 맞는다. 호출할 때 `max_drawdown(result.equity_curve, result.max_book_size)` 형태로 넘겨라.

## WorldQuant 정식 알파 (`strategies/formulaic/`)

출처: Zura Kakushadze, 「101 Formulaic Alphas」(2016, arXiv:1601.00991). Appendix A의 수식은 WorldQuant LLC의 명시적 허가로 공개된 것이고 저작권은 WorldQuant LLC에 있다.

**101개 중 14개만 이 엔진으로 옮길 수 있다.** WorldQuant의 알파는 '한 종목의 매매 규칙'이 아니라 '2000종목 달러중립 롱숏 포트폴리오의 가중치'다. 수식에 `rank(x)`(그날 전 종목 중 몇 등), `indneutralize(x, g)`(같은 섹터 평균 차감), `scale(x, a)`, `adv{d}`, `cap`이 들어가면 종목 하나만 보고는 계산 자체가 불가능하다. 87개가 이 중 하나 이상을 쓴다. 나머지 87개를 하려면 엔진을 종목별 루프에서 '날짜 × 종목 매트릭스'로 바꾸고 공매도 경로를 넣어야 한다.

**횡단면 rank를 시계열 rank로 갈음한다.** `FormulaicAlpha`가 연속 알파값을 `rolling(window).rank(pct=True)`로 자기 과거 분포의 백분위로 바꾸고, 진입/청산 문턱을 따로 둬(히스테리시스) `{-1,0,1}`을 만든다. 문턱을 하나로 두면 경계에서 신호가 떨며 왕복비용만 나간다. 알파값의 절대 수준이 가격 단위에 의존해 종목 간 비교가 안 되므로 이 정규화 없이는 임계값 하나를 전 종목에 걸 수 없다.

**연산자는 필요한 것만 있다** (`formulaic/base.py`: `delta`, `correlation`, `ts_rank`, `ts_max`). 나머지(`delay`, `ts_min`, `ts_argmax`, `decay_linear`, `signedpower`)는 전부 rolling 한 줄이니 필요해질 때 추가하라. `ts_rank`는 `pct=True`로 [0,1]을 낸다 — 논문 알파들이 `(1 - Ts_Rank(...))` 형태로 쓰는 걸 보면 원본도 그 스케일을 전제한다.

### 검증 결과 (코스피 대형주 43종목 **일봉**, 1975~2026, train ~2014 / test 2015~)

| 알파 | 수식의 뜻 | train 순알파 | test 순알파 | 판정 |
|---|---|---|---|---|
| #6 | `-corr(open, volume, 10)` | +3.12bp/봉 | **+0.90bp/봉** (t=1.5) | 유일한 생존, 약함 |
| #12 | `sign(Δvolume) × -Δclose` | +3.35 | −0.34 (초과 +10.2, t=3.6) | 예측력은 살아남고 비용에 죽음 |
| #101 | `(close-open)/(high-low)` | +4.83 (초과 t=**11.8**) | **−21.56** (초과 t=**−5.8**) | 부호 역전 |
| #35 | 3중 ts_rank 곱 | −5.28 | −3.83 | 부호가 반대 (train 18개 조합 전부 음수) |
| #26 | ts_rank 중첩 상관 | 진입 69회 | 표본 없음 | 신호가 안 나옴 |

**일봉에서는 '거래당 수익'으로 재면 안 된다.** 오래 들고 있는 전략이 시장 상승을 그대로 먹어 무조건 좋아 보인다(Alpha#26은 거래당 +4193bp인데 보유가 340봉이다). 노출을 상쇄하려면 시간 단위로 나눠라 — **보유 중 봉당 수익 − 미보유 봉당 수익**이 이 리포의 일봉 판정 기준이고, 비용은 `23bp × 진입횟수 / 보유봉수`로 봉당으로 환산해 뺀다.

**Alpha#101이 이 리포 최고의 교훈이다.** (아래 train/test 숫자는 레짐 오염이 있다 — microstructure 절의 대조군 이야기를 같이 읽어라.) in-sample t=+11.8로 여기서 본 어떤 신호보다 강했고, out-of-sample에서 t=−5.8로 부호까지 뒤집혔다. t가 크다는 것은 지속성을 전혀 보장하지 않는다.

**회전율과 엣지는 맞바꿀 수 없다.** #101·#12는 초과수익이 10~16bp/봉으로 크지만 평균 보유가 2봉이라 왕복 23bp가 봉당 11bp로 얹힌다. 히스테리시스를 넓혀 보유를 10봉으로 늘리면 비용은 2.3bp로 떨어지지만 초과수익이 함께 사라진다(#101은 −2.9bp로 음전). 엣지가 1~2봉짜리면 비용을 회피할 방법이 없다. 논문이 명시한 대로 원본은 2000종목 포트폴리오 안에서 반대 주문을 상계해("automatic internal crossing of trades") 비용을 아낀다 — 그 구조가 없으면 이 알파들은 성립하지 않는다.

## 시장미시구조 (`strategies/microstructure/`)

Citadel은 수식을 하나도 공개한 적이 없다(WorldQuant와 다른 점이다). 공개된 것은 사업 구조뿐이다 — Citadel Securities는 미국 주식 거래량의 약 25%를 체결하는 마켓메이커로 호가차·PFOF·리베이트로 벌고 방향성 순노출을 0에 가깝게 유지하며, 핵심 난제는 역선택이다. Citadel LLC는 팟 구조의 멀티스트래티지이고 주식 팟 대부분이 순노출 -20%~+20%의 시장중립이다.

**둘 다 이 엔진과 구조가 맞지 않는다.** 마켓메이킹은 방향성 베팅이 아니라 양쪽 호가를 걸고 스프레드를 먹는 일이라 호가창·큐 포지션·마이크로초 지연이 필요하고, 시장중립은 공매도가 필요하다. 그래서 이 패키지는 **'유동성 공급자가 대가를 받는 그 양을 학술 문헌의 추정량으로 재고, 단일 종목 롱으로 옮긴 것'**이다. 출처는 Citadel이 아니라 Roll(1984)·Amihud(2002)·Cont-Kukanov-Stoikov(2014)다. 파일 주석도 그렇게 적혀 있으니 'Citadel 전략'으로 인용하지 마라.

**호가 이력이 없다.** `paper/feed.py`가 `orderbook:kr`을 실시간으로 받지만 브라우저로 흘려보내고 버린다 — `market_data.db`에는 `candles` 테이블 하나뿐이다. 미시구조를 제대로 하려면 그 스트림을 적재하는 것이 첫 단계이고, 그 전까지 이 패키지는 봉 모양으로 근사한 대용치일 뿐이다.

### 검증 결과 (코스피 43종목 일봉, train ~2014 / test 2015~, 순알파 bp/봉)

숫자 하나가 아니라 **파라미터 격자 18조합 중 몇 %가 양수인지**를 함께 본다.

| 전략 | train양수 | train중앙 | test양수 | test중앙 | 판정 |
|---|---|---|---|---|---|
| `AmihudIlliquidity` | 83% | +0.96 | 33% | −0.72 | 레짐을 안 타는 유일한 것, 그래서 정직하게 실패 |
| `RollSpread` | 22% | −1.29 | 100% | +6.91 | 레짐 효과 |
| `OrderFlowImbalance` | 6% | −1.03 | 100% | +1.40 | 레짐 효과 |
| `AdverseSelection` | 0% | −16.21 | 61% | +0.28 | train 전멸 |
| **대조군** `RsiReversion` | **100%** | **+6.11** | **100%** | **+6.91** | 기존 전략 |
| **대조군** `BollingerBand` | 0% | −0.37 | 100% | +2.26 | 기존 전략 |

`OvernightInventory`는 분봉 전용이라 따로 쟀다(50종목 × 28일, 1,395회): 오버나잇 +21.3bp vs 같은 종목 장중 −12.9bp로 **효과는 실재하나** 왕복비용 23bp를 2bp 차이로 못 넘어 비용 후 −1.8bp다.

**일봉 train/test 분할도 레짐에 오염돼 있다.** 앞서 '25년을 걸치니 시간축 분할이 진짜 OOS'라고 적었는데 그건 과신이었다. 2015년 이후 한국 대형주가 평균회귀적으로 변해서, 평균회귀 성격을 띤 것은 새것이든 헌것이든 전부 test에서 좋아진다 — 아무것도 안 한 `BollingerBand`조차 −0.37에서 +2.26으로 뒤집힌다. **그래서 train/test 숫자만 보지 말고 반드시 기존 전략을 대조군으로 같이 돌려라.** 이 패키지에서 test가 가장 좋은 `RollSpread`(+6.91)는 원래 있던 `RsiReversion`(+6.91)과 같은 값이고, 그쪽은 train에서도 양수다. 새로 얻은 것이 없다는 뜻이다.

**`rolling`의 `min_periods`를 반드시 지정하라.** pandas는 `min_periods` 기본값이 `window`라, 창 안에 NaN이 하나만 있어도 결과가 통째로 NaN이다. 점수가 드문드문 정의되는 전략(`RollSpread`는 정의 비율이 44%다 — Roll 추정량은 공분산이 양수면 정의되지 않고 그게 정상이다)은 이러면 신호가 **하나도** 안 나는데, 예외가 아니라 '거래 0회'로 조용히 끝나서 알아채기 어렵다. `Alpha#026`이 실제로 이 함정에 빠져 '신호가 안 나오는 알파'로 잘못 판정됐다가, 고치고 나니 진입이 69회에서 6,256회로 늘고 판정이 'OOS 실패'로 바뀌었다. **신호가 안 나오는 것과 신호가 나쁜 것은 다른 결론이고, 전자는 대개 버그다.** `strategies/tests/test_microstructure.py`의 `test_signals_actually_fire`가 이걸 잡는다.

**점수형 전략의 공통 뼈대는 `strategies/score_base.py`의 `PercentileScoreStrategy`다.** 연속 점수를 자기 과거 백분위로 바꿔 문턱을 거는 기계 부분이고, `formulaic`과 `microstructure`가 함께 쓴다. 점수의 절대 수준이 가격·거래량 단위에 의존해 종목 간 비교가 안 되기 때문에 이 정규화 없이는 임계값 하나를 전 종목에 걸 수 없다.

## 결과 캐시 (`backtest/results.py`)

전 전략 × 전 종목을 매번 처음부터 돌리지 않기 위한 일 단위 캐시다. `backtest/run.py`와는 별개 경로이고, `backtest/run.py`는 전혀 건드리지 않았다.

**왜 이어붙일 수 있나**: `run_backtest`는 순차 시뮬레이션이고 봉과 봉 사이로 넘어가는 상태가 `holdings` 하나뿐이다. 그래서 엔진에 `holdings0` 인자를 붙여 마지막 저장 지점의 보유량을 되돌려 넣고, 누적 실현현금은 호출자(`results.evaluate`)가 `equity - holdings × close`로 복원해 더한다. 결과는 처음부터 돌린 것과 같다 — 실현현금을 뺄셈으로 복원하는 탓에 마지막 몇 비트만 달라지고, `--selfcheck`가 누적손익·체결·지표를 오차 1e-9 이내로 매번 검증한다.

**캐시 단위가 '거래일'인 이유**: `walk_forward_split`이 비율(70/30)이라 봉이 늘면 분할 지점이 앞으로 밀린다. 분할 경계로 저장하면 어제 캐시가 오늘 캐시의 앞부분이 아니게 되어 애초에 이어붙지 않는다. 저장은 날짜로 하고 train/test 분할은 **읽을 때** 날짜 목록을 잘라서 한다.

**샤프가 일별로 뭉개지지 않는 이유**: 날짜별로 봉 손익의 `합`·`제곱합`·`봉 수`를 함께 저장한다. 셋 다 가산적이라 날짜를 가로질러 더하면 봉 단위 평균·분산이 정확히 복원된다. 이게 없으면 표본이 8600개에서 12개로 줄어 숫자가 의미를 잃는다.

**MDD만 근사다.** 봉마다 누적 최고점을 들고 있어야 정확한데 그러면 캐시할 이유가 없다. 하루 안에서 고점이 저점보다 먼저 왔다고 가정한 **상한**을 낸다 — 실제 낙폭은 이보다 얕거나 같다.

**`backtest/run.py`와 숫자가 완전히 같지는 않다.** 전 구간을 끊지 않고 이어서 돌리므로 train에서 들고 있던 포지션이 test 시작 시점에 넘어온다. `backtest/run.py`는 test 슬라이스를 무포지션에서 시작한다.

**캐시 무효화**: 행마다 전략 소스 + `indicators.py` + `base.py` + `backtest/engine.py`의 mtime 최댓값(`fp`)을 박아 둔다. 코드를 고치면 그 전략의 행만 버려지고 다시 계산된다. 스키마를 바꿀 때는 `SCHEMA_VERSION`을 올리면 테이블이 통째로 재생성된다.

**`backtest/results.py`를 일봉으로 돌리지 마라.** 캐시 단위가 '거래일'이라 1분봉에서는 행 하나가 390봉을 요약하지만 일봉에서는 행 하나가 봉 하나다. 현재 1분봉 전량이 68,678행에 151MB인데, 일봉(49종목 × 6,377일 × 51전략)이면 약 1,600만 행 — 230배다. 일봉 검증은 `backtest/run.py --interval 1d`나 별도 스크립트로 하고, results.py는 분봉 전용으로 둬라.

출력은 `results.db`(기계용, gitignore 대상), `results/report.md`(전략 순위 + 상위 5개 상세), `results/detail.csv`(전 조합). 실측: 2종목 × 41전략 콜드 37초 → 웜 6초. 전량(41전략 × 50종목 = 2050조합) 콜드 약 17분 → 웜 238초.

## 모의투자 웹사이트 (`paper/`)

    pip install fastapi uvicorn websockets     # 최초 1회
    python -m uvicorn paper.app:app --reload   # http://localhost:8000

토스 실시간 시세를 받아 브라우저에서 손으로 주문을 넣고, 체결·잔고·손익을 가짜 돈으로 추적한다. 백테스팅 하네스와는 별개 경로다 — `strategies/`, `backtest/run.py`, `backtest/results.py`를 건드리지 않는다.

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

테스트: `python paper/tests/test_broker.py` (체결 엔진), `tests/test_ticks.py`, `tests/test_toss.py`, `tests/test_feed.py`. 프레임워크 없이 assert 기반이다.

전략 쪽 테스트도 같은 형식이다: `python strategies/tests/test_session_alpha.py` (세션 기반 전략 5개의 lookahead·오버나잇 검사), `python strategies/tests/test_formulaic.py` (WorldQuant 알파의 연산자 손계산 대조 + lookahead·워밍업 검사), `python strategies/tests/test_microstructure.py` (미시구조 추정량 손계산 대조 + 신호가 실제로 나는지).

## 데이터

`market_data.db` (SQLite, gitignore 대상, 현재 245MB — 코스피50 전 종목 1분봉). 테이블 `candles`, PK `(ticker, timeframe, timestamp)` — `INSERT OR IGNORE` 증분 수집이라 재실행해도 안전하다. **1분봉은 코스피50 전 종목이 있지만 종목당 거래일이 28일뿐이고, 일봉(49종목)은 1975년까지 올라간다.** 전략 검증의 검정력은 거의 전부 일봉에서 나온다 — `python -m data.candles --kospi50 --interval 1d`는 1분봉 수집과 달리 몇 분이면 끝난다. `timestamp`는 TEXT로 저장되고 `load_candles`가 읽을 때 datetime으로 파싱한다.

`data/auth.py`가 `.env`의 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`으로 토큰을 자동 발급·캐시한다 (만료 60초 전 갱신). 토큰 401이 아니라 **IP 미등록**으로 실패하는 경우가 많다.

## 리포 위생

`.gitignore`가 `.env`, `__pycache__/`, 그리고 `market_data.db`·`results.db`·`paper.db`·`results/`·`graph/` 같은 생성물을 전부 막는다. 데이터는 커밋하지 않으므로 새 환경에서는 `python -m data.candles --kospi50 --interval 1m`으로 다시 받아야 한다 — **토스 API가 429를 자주 던지고 `update_multiple`에 재시도가 없어서 한 번에 다 못 받는다.** 실측으로 50종목 중 17종목이 rate limit으로 실패했다. 수집이 증분이라 그냥 실패한 종목만 다시 돌리면 되고, 미수집 종목은 `KOSPI50`과 DB를 비교해 뽑으면 된다.
