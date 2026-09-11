# 백테스팅 하네스 재설계 — 신호 생성과 성과 리포트 간소화

날짜: 2026-08-28
상태: 승인됨 (구현 대기)

## 문제

현재 하네스는 네 가지 지점에서 손이 많이 간다.

1. **전략 작성** — 7개 전략 중 5개가 동일한 `holding` 불리언 for-루프를 복붙하고 있다. 진입/청산 조건은 각각 한 줄인데 그것을 감싸는 상태머신이 매번 15줄씩 반복된다.
2. **실행** — 종목·전략·파라미터를 바꾸려면 `backtest.py`와 `run_optimize.py` 파일 본문을 직접 편집해야 한다.
3. **비교** — 여러 전략 × 여러 종목을 한 번에 돌려 표로 비교할 수단이 없다.
4. **성과 리포트** — 일별 손익(누적이 아닌 그날의 손익), 거래별 승률, 수익 평균·분산이 없다. `result.trades`는 buy/sell이 뒤섞인 평평한 목록이라 왕복 거래 단위 통계를 낼 수 없다.

추가 요구: 전략을 만들면 자동으로 최적화 → 백테스트까지 이어지는 흐름.

## 범위에서 제외

- lookahead bias 자동 탐지
- 과적합 경고 (train/test 샤프 괴리, 그리드 경계 접촉 등)
- 실매매(paper/live) 연동

필요해지면 별도 사이클로 다룬다.

## 접근

**덧붙이기(additive) 방식을 택한다.** `Strategy`에 선언적 경로(`entries`/`exits`)를 추가하되, 기존 `generate_signals` 오버라이드도 계속 유효하게 둔다. 쿨다운·트레일링스톱처럼 진짜 순차 상태가 필요한 전략(`ema_cross_with_atr`)이 있으므로 전면 교체는 표현력을 잃는다.

## 설계

### 1. 상태머신 — `strategies/base.py`

```python
class Strategy(ABC):
    warmup = 0   # 서브클래스가 __init__에서 self.warmup = slow 처럼 덮어씀

    def entries(self, df) -> pd.Series: raise NotImplementedError
    def exits(self, df)   -> pd.Series: raise NotImplementedError

    def generate_signals(self, df) -> pd.Series:
        return to_signals(self.entries(df), self.exits(df), self.warmup)
```

`to_signals(entries, exits, warmup)` 규칙:

- `warmup` 미만 구간은 무조건 `0`
- 미보유 + `entries[i]` → `1` (보유 상태로 전환)
- 보유 + `exits[i]` → `-1` (미보유 상태로 전환)
- 최대 1주. 중복 진입이 원천적으로 불가능

**결정 1 — 동시 신호:** 한 봉에서 진입·청산이 모두 참이면 미보유 상태에서는 진입, 보유 상태에서는 청산이 우선한다(`elif` 구조에서 자연히 따라옴). 평균회귀 전략은 두 조건이 동시에 참일 수 없고, 가능한 전략이라면 다음 봉에서 반대 신호가 다시 발생한다.

**결정 2 — 마지막 봉:** 강제 청산하지 않는다. 미청산 포지션은 왕복 거래로 집계하지 않고 리포트에 `미청산: n주`로 별도 표기한다. 강제 청산하면 기존 백테스트 수치가 달라진다.

기타: `entries`/`exits`의 NaN은 `False`로 취급한다. 인덱스가 `df`와 다르면 즉시 `ValueError`를 낸다.

성능: 파이썬 루프 1회(10만 봉 기준 약 50ms). 지금도 전략마다 같은 루프를 돌고 있어 손해가 없다. 그리드 조합이 수천 개로 커질 때를 대비해 `ponytail:` 주석으로 벡터화 천장을 남긴다.

### 2. 트레이드 통계 — `backtest_engine.py` + `metrics.py`

승률을 정확히 내려면 슬리피지가 반영된 체결가가 필요하나 현재 `trades`에는 원가격만 있다.

**엔진 수정:** `trades` 행에 `fill_price`를 추가한다. 매수는 `price + step_cost`, 매도는 `price - step_cost`. 이렇게 하면 하위 소비자 전부가 자동으로 올바른 수치를 사용한다.

**`trade_stats(trades) -> dict`:** k번째 매수와 k번째 매도를 FIFO로 짝지어 왕복 거래표를 만든 뒤 아래를 반환한다.

| 항목 | 정의 |
|---|---|
| 왕복 거래 수 | 짝지어진 buy/sell 쌍의 개수 |
| 승률 | `pnl > 0` 인 왕복의 비율 |
| 평균 수익률 / 표준편차 / 분산 | 왕복 `pnl ÷ 매수 체결가` 기준 |
| 평균 이익 · 평균 손실 | 이긴 거래 / 진 거래 각각의 평균 |
| 손익비 (Profit Factor) | 총이익 ÷ 총손실 |
| 평균 보유 봉 수 | 청산 위치 − 진입 위치 |
| 미청산 | 짝을 찾지 못한 매수 수 |

**결정 3 — 수익률 분모:** 해당 거래의 매수 체결가(거래당 1주 기준). 기존 `result.returns`(최대 투입원금 대비 일별 변동)와 의미가 다르며, 둘 다 리포트에 표시한다. 전자는 "이 거래가 몇 % 먹었나", 후자는 "투입 원금 대비 변동성"이다.

**일별 손익:** `to_daily_summary`에 `daily_pnl` 컬럼을 추가한다. 현재는 누적(`end_of_day_equity`)만 나와 그날의 손익이 보이지 않는다.

### 3. CLI — `run.py`, `grids.py`

```bash
python run.py EmaCrossStrategy --ticker 005930
python run.py EmaCrossStrategy --ticker 005930 --optimize --plot --daily
python run.py --all --ticker 005930 000660 035420 --optimize
```

- `--optimize`: `grids.py`의 `GRIDS[클래스명]`으로 train 그리드서치 → best 파라미터를 test에 적용 → out-of-sample 리포트. 그리드가 없으면 기본 파라미터 1회 실행으로 조용히 넘어간다.
- `--all`: (전략 × 종목) 전부 실행 후 한 장의 순위표. 컬럼: 샤프, MDD, 승률, 왕복 거래 수, 순손익, 벤치마크 대비.
- 플래그: `--interval`(기본 `1m`), `--metric`(기본 `sharpe`), `--optimize`, `--plot`, `--daily`, `--all`

`grids.py`는 전략 클래스명을 키로 하는 단일 `GRIDS` 딕셔너리를 갖는다. 무효 조합 필터(`fast < slow` 등)는 `VALID` 딕셔너리에 함께 둔다.

이름 → 클래스 조회를 위해 `strategies/__init__.py`에 `REGISTRY` 딕셔너리를 추가한다. 이미 클래스를 수집 중이므로 한 줄이면 된다.

### 4. 마이그레이션

`entries`/`exits`로 이전: `bollinger_band`, `rsi_reversion`, `session_close`, `opening`, `ema_cross_with_adx`.

그대로 유지: `ema_cross`(이미 상태 없이 벡터화됨), `ema_cross_with_atr`(쿨다운이라는 순차 상태 보유).

곁다리 수정: `ema_cross_with_adx`의 백분위 ATR 계산이 O(n²) 중첩 루프인데 `atr.expanding().rank(pct=True)` 한 줄과 동치다. 해당 파일을 수정하는 김에 함께 고친다.

삭제: `backtest.py`, `run_optimize.py`, `test.py`, `test1.py` — 전부 `run.py`가 대체한다.

### 5. 체크

`test_harness.py`에 assert 기반 검사를 둔다. 프레임워크 없이 `python test_harness.py`로 실행한다.

- 상태머신이 중복 진입을 막는지
- 워밍업 구간이 정확히 `0`인지
- 동시 신호가 결정 1대로 처리되는지
- FIFO 짝짓기가 알려진 손익을 정확히 재현하는지
- `trade_stats`의 승률·손익비가 손으로 계산한 값과 일치하는지

## 코딩 규약

주석과 docstring은 한국어로 쓰고, 비자명한 계산(슬리피지 복원, FIFO 짝짓기, 상태머신 분기)에는 의도와 근거를 함께 적는다. 기존 코드의 설명형 톤을 따른다.
