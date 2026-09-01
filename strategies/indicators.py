"""
전략들이 공유하는 지표 계산 모음.

왜 따로 두나:
  ATR·RSI·ADX 같은 지표는 여러 전략이 똑같은 식으로 쓴다. 파일마다 복붙해 두면
  한쪽만 고쳐졌을 때 두 전략의 신호가 조용히 갈라진다. 계산은 여기 한 번만 둔다.

lookahead 규약:
  모든 함수는 '현재 봉까지의 정보'만 쓴다 (rolling / ewm / expanding / cumsum).
  미래 봉이 섞이면 백테스트 성과가 실제보다 좋게 나온다 — CLAUDE.md의
  expanding() 규약과 같은 이유다. 채널(donchian)처럼 '직전 봉까지'의 값이어야
  의미가 있는 지표는 함수 안에서 shift(1)을 이미 걸어 두었다.

기존 전략(rsi_reversion 등)은 자기 파일 안에 지표를 갖고 있다. 스냅샷 신호를
한 비트도 바꾸지 않기 위해 일부러 손대지 않았다. 새 전략만 여기를 쓴다.
"""
import numpy as np
import pandas as pd


def wilder(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder 평활. ATR·RSI·ADX가 전부 쓰는 '지수평균의 느린 버전'이다.
    span=period인 EMA가 아니라 alpha=1/period라서 같은 period라도 훨씬 완만하다.
    min_periods를 걸어 창이 다 차기 전에는 NaN을 낸다 (워밍업 구간 보호).
    """
    return series.ewm(alpha=1 / period, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """
    TR = max(고가-저가, |고가-전일종가|, |저가-전일종가|).
    단순 (고가-저가)와 달리 갭(전 봉 종가에서 훌쩍 뛴 구간)을 변동성에 포함한다.
    """
    prev_close = df["close"].shift(1)
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """평균 진폭. 손절폭·채널폭을 '가격 단위'로 잡을 때 쓴다."""
    return wilder(true_range(df), period)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """0~100. 상승분 평균 대비 하락분 평균의 비율. 50이 중립."""
    delta = close.diff()
    avg_gain = wilder(delta.clip(lower=0), period)
    avg_loss = wilder(-delta.clip(upper=0), period)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    """(중심선, 상단, 하단). 중심선은 단순이동평균, 폭은 표준편차 배수."""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid, mid + num_std * std, mid - num_std * std


def keltner(df: pd.DataFrame, ema_period: int = 20, atr_period: int = 10,
            mult: float = 2.0):
    """
    (중심선, 상단, 하단). 볼린저와 모양은 같지만 폭을 표준편차가 아니라 ATR로 잡는다.
    표준편차는 종가만 보고 ATR은 고가·저가·갭까지 보므로, 장중 급등락에 더 정직하다.
    """
    mid = df["close"].ewm(span=ema_period).mean()
    band = mult * atr(df, atr_period)
    return mid, mid + band, mid - band


def donchian(df: pd.DataFrame, period: int = 20):
    """
    (상단, 하단) = 직전 period봉의 최고가 / 최저가.

    shift(1)이 핵심이다. 현재 봉을 포함해서 최고가를 구하면 '현재 고가 >= 현재까지
    최고가'가 거의 항상 참이라 돌파 신호가 의미를 잃는다. 터틀 트레이딩의 원래
    정의대로 '어제까지의 채널을 오늘 뚫었는가'를 본다.
    """
    return (df["high"].rolling(period).max().shift(1),
            df["low"].rolling(period).min().shift(1))


def adx(df: pd.DataFrame, period: int = 14):
    """
    (ADX, +DI, -DI).
      +DI/-DI: 상승 방향 힘 / 하락 방향 힘.
      ADX    : 방향과 무관한 '추세의 세기'. 보통 20~25 위면 추세장으로 본다.
    """
    up = df["high"].diff()
    down = -df["low"].diff()

    # 그 봉이 위로 더 밀었으면 +DM만, 아래로 더 밀었으면 -DM만 남긴다.
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)

    tr_n = wilder(true_range(df), period)
    plus_di = 100 * wilder(plus_dm, period) / tr_n
    minus_di = 100 * wilder(minus_dm, period) / tr_n

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder(dx, period), plus_di, minus_di


def stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    """
    (%K, %D). 최근 k_period봉 고저 범위에서 현재 종가가 몇 %에 있는가.
    0이면 구간 최저, 100이면 구간 최고. %D는 %K의 이동평균(신호선).
    """
    low_n = df["low"].rolling(k_period).min()
    high_n = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan)
    return k, k.rolling(d_period).mean()


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """-100~0. 스토캐스틱 %K를 위아래 뒤집은 것과 같다 (%R = %K - 100)."""
    high_n = df["high"].rolling(period).max()
    low_n = df["low"].rolling(period).min()
    return -100 * (high_n - df["close"]) / (high_n - low_n).replace(0, np.nan)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    전형가격이 이동평균에서 평균편차의 몇 배나 떨어졌는가.
    ±100을 과열/침체 기준으로 쓴다. 상수 0.015는 원 논문의 스케일 보정값이다.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(period).mean()
    mad = (tp - ma).abs().rolling(period).mean()
    return (tp - ma) / (0.015 * mad.replace(0, np.nan))


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    거래대금 가중 RSI. 전형가격이 오른 봉의 거래대금과 내린 봉의 거래대금을 비교한다.
    RSI가 '얼마나 올랐나'만 본다면 MFI는 '얼마의 돈이 실려서 올랐나'까지 본다.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3
    raw = tp * df["volume"]
    up = tp.diff() > 0
    pos = raw.where(up, 0.0).rolling(period).sum()
    neg = raw.where(~up, 0.0).rolling(period).sum()
    ratio = pos / neg.replace(0, np.nan)
    return (100 - 100 / (1 + ratio)).fillna(50)


def obv(df: pd.DataFrame) -> pd.Series:
    """
    On Balance Volume. 오른 봉의 거래량은 더하고 내린 봉의 거래량은 뺀 누적값.
    가격은 안 움직이는데 OBV만 오르면 '조용히 매집 중'으로 읽는다.
    """
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def bar_dates(df: pd.DataFrame) -> pd.Series:
    """
    각 봉이 속한 '거래일'. 세션 단위로 리셋되는 지표(VWAP, 시가 기준선)에 쓴다.
    timestamp 컬럼을 우선 쓰고, 없으면 DatetimeIndex를 본다. 반환 Series의
    인덱스는 df와 같다 — 다르면 엔진이 .iloc으로 엉뚱한 봉과 짝지어 버린다.
    """
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = pd.Series(df.index, index=df.index)
    else:
        raise ValueError("df에 'timestamp' 컬럼이나 DatetimeIndex가 필요합니다.")
    return ts.dt.date


def is_last_bar_of_day(df: pd.DataFrame) -> pd.Series:
    """그날의 마지막 봉이면 True. 오버나잇을 하지 않는 전략의 강제 청산에 쓴다."""
    d = bar_dates(df)
    flags = d != d.shift(-1)
    flags.iloc[-1] = True  # 데이터 전체의 마지막 봉도 그날의 마지막 봉이다
    return flags


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """
    당일 누적 거래량가중평균가. 매일 장 시작에 리셋된다.
    기관 체결 기준선으로 통해서, 장중 '비싸게 샀나 싸게 샀나'의 사실상 표준이다.
    cumsum이라 미래 봉을 보지 않는다.
    """
    tp = (df["high"] + df["low"] + df["close"]) / 3
    d = bar_dates(df)
    cum_pv = (tp * df["volume"]).groupby(d).cumsum()
    cum_v = df["volume"].groupby(d).cumsum().replace(0, np.nan)
    return cum_pv / cum_v


def aroon(df: pd.DataFrame, period: int = 25):
    """
    (Aroon Up, Aroon Down). 0~100.

    다른 추세지표와 재료가 다르다. 이동평균 계열이 '가격이 얼마나 움직였나'를 본다면
    Aroon은 '최근 고점/저점이 얼마나 최근인가'만 본다 — 값이 아니라 시간이다.
    창 안의 최고가가 바로 이번 봉이면 Up=100, 창의 맨 끝(가장 오래된 봉)이면 Up=0.

    그래서 횡보 후 추세가 막 시작되는 국면을 이동평균보다 빨리 잡는다. 반대로
    가격의 크기를 무시하므로 1원짜리 신고가에도 100이 나온다 — 단독으로 쓰기보다
    Up/Down 교차나 문턱과 함께 쓰는 게 원래 용법이다.
    """
    # ponytail: rolling.apply(argmax)는 창마다 파이썬 호출이 아니라 numpy 호출이라
    # 10만 봉에 1초 남짓이다. 그리드서치가 체감상 느려지면 stride_tricks로 올린다.
    since_high = df["high"].rolling(period).apply(np.argmax, raw=True)
    since_low = df["low"].rolling(period).apply(np.argmin, raw=True)
    # argmax는 창 안에서의 위치(0=가장 오래된 봉, period-1=현재 봉)를 준다.
    # 위치가 곧 '얼마나 최근인가'라서 period-1로 나누면 그대로 0~100이 된다.
    up = 100 * since_high / (period - 1)
    down = 100 * since_low / (period - 1)
    return up, down


def vortex(df: pd.DataFrame, period: int = 14):
    """
    (VI+, VI-). 두 선의 교차로 추세 전환을 잡는다.

    ADX의 +DI/-DI와 목적은 같지만 재료가 다르다. DI는 '고가끼리, 저가끼리'의 차이를
    보는데, Vortex는 대각선으로 본다 — 이번 고가와 전 봉 저가의 거리(상승 소용돌이),
    이번 저가와 전 봉 고가의 거리(하락 소용돌이). 방향 전환이 일어나면 이 대각선
    거리가 먼저 벌어지기 때문에 DI 교차보다 반응이 빠른 편이다.

    TR로 나눠 정규화하므로 종목 가격대와 무관하게 1.0 근처에서 논다.
    """
    vm_plus = (df["high"] - df["low"].shift(1)).abs()
    vm_minus = (df["low"] - df["high"].shift(1)).abs()
    tr_sum = true_range(df).rolling(period).sum().replace(0, np.nan)
    return (vm_plus.rolling(period).sum() / tr_sum,
            vm_minus.rolling(period).sum() / tr_sum)


def trix(close: pd.Series, period: int = 15, signal_period: int = 9):
    """
    (TRIX, 신호선). EMA를 세 번 겹쳐 건 뒤의 변화율(%)이다.

    EMA를 세 번 통과시키면 잔 노이즈가 거의 다 죽는다. 그 매끈해진 선의 기울기만
    보므로 MACD보다 신호가 훨씬 드물고 늦다 — 분봉의 톱니에 당하지 않는 대신
    전환점을 놓친다. 0선 위/아래가 추세 방향, 신호선 교차가 진입 타이밍이다.
    """
    e1 = close.ewm(span=period, min_periods=period).mean()
    e2 = e1.ewm(span=period, min_periods=period).mean()
    e3 = e2.ewm(span=period, min_periods=period).mean()
    line = 100 * e3.pct_change()
    return line, line.ewm(span=signal_period, min_periods=signal_period).mean()


def force_index(df: pd.DataFrame, period: int = 13) -> pd.Series:
    """
    Elder의 강도지수. (종가 변화) x (거래량)을 EMA로 다듬은 값.

    OBV가 방향(+1/-1)에만 거래량을 곱한다면, 이쪽은 '얼마나 움직였는지'까지 곱한다.
    거래량 없이 오른 봉과 대량 거래로 오른 봉을 구분하는 게 핵심이다.
    부호가 방향, 절대값이 세기. 0선 교차를 진입 신호로 쓴다.
    """
    return (df["close"].diff() * df["volume"]).ewm(span=period, min_periods=period).mean()


def cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Chaikin Money Flow. -1~+1.

    봉 하나마다 '종가가 그 봉의 고저 범위 어디에서 끝났나'를 -1~+1로 매기고
    거래량을 곱해 누적한다. 고가 근처에서 끝나면 매집, 저가 근처면 분산으로 본다.
    MFI가 봉과 봉 사이의 방향을 본다면 이쪽은 봉 하나의 '내부'를 본다 — 그래서
    갭 없이 장중에서만 밀리는 흐름을 더 잘 잡는다.
    """
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mf_multiplier = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mf_volume = (mf_multiplier * df["volume"]).fillna(0.0)
    return (mf_volume.rolling(period).sum()
            / df["volume"].rolling(period).sum().replace(0, np.nan))


def awesome_oscillator(df: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """
    Bill Williams의 AO. 중간가((고+저)/2)의 단순이동평균 5 - 34.

    MACD와 식은 닮았지만 두 군데가 다르다. 종가가 아니라 중간가를 쓰고(장중 꼬리를
    반영), EMA가 아니라 SMA를 쓴다(최근 봉에 가중치를 더 주지 않는다). 그래서
    MACD보다 둔하고 덜 흔들린다. 0선 위/아래가 단기와 중기의 힘 비교다.
    """
    median_price = (df["high"] + df["low"]) / 2
    return (median_price.rolling(fast).mean() - median_price.rolling(slow).mean())


def ultimate_oscillator(df: pd.DataFrame, short: int = 7, mid: int = 14,
                        long: int = 28) -> pd.Series:
    """
    Larry Williams의 궁극 오실레이터. 0~100.

    단일 기간 오실레이터(RSI 등)의 고질병은 기간을 짧게 잡으면 시끄럽고 길게 잡으면
    늦다는 것이다. 이 지표는 7/14/28을 4:2:1 가중으로 한 번에 섞어 그 선택을 없앤다.
    분자 BP(매수 압력)는 '종가 - 그 봉의 진짜 저점'이고, 분모는 TR이다.
    """
    prev_close = df["close"].shift(1)
    true_low = pd.concat([df["low"], prev_close], axis=1).min(axis=1)
    true_high = pd.concat([df["high"], prev_close], axis=1).max(axis=1)
    bp = df["close"] - true_low
    tr = true_high - true_low

    def avg(n):
        return bp.rolling(n).sum() / tr.rolling(n).sum().replace(0, np.nan)

    return 100 * (4 * avg(short) + 2 * avg(mid) + avg(long)) / 7


def fisher_transform(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """
    Fisher Transform. 가격 분포를 억지로 정규분포에 가깝게 편 값.

    왜 쓰나: 가격은 꼬리가 두꺼워서 '2시그마 이탈' 같은 문턱이 잘 안 먹는다.
    최근 period봉 범위에서의 위치를 -1~+1로 정규화한 뒤 0.5*ln((1+x)/(1-x))를
    걸면 극단값이 크게 벌어진다 — 전환점이 뭉툭한 곡선이 아니라 뾰족한 스파이크로
    나와서 문턱 비교가 훨씬 선명해진다.

    원 정의는 두 개의 재귀식이지만 둘 다 정확히 EWM이다 (v = 0.33x + 0.67v_prev는
    alpha=0.33인 ewm과 같은 식). 루프를 돌 이유가 없어 ewm으로 그대로 옮겼다.
    """
    median_price = (df["high"] + df["low"]) / 2
    low_n = median_price.rolling(period).min()
    high_n = median_price.rolling(period).max()
    raw = 2 * ((median_price - low_n) / (high_n - low_n).replace(0, np.nan) - 0.5)

    value = raw.ewm(alpha=0.33, min_periods=period).mean()
    # ln((1+v)/(1-v))는 v가 ±1에 닿으면 발산한다. 원 구현도 같은 이유로 잘라 쓴다.
    value = value.clip(-0.999, 0.999)
    return (0.5 * np.log((1 + value) / (1 - value))).ewm(alpha=0.5).mean()


def prev_day_ohlc(df: pd.DataFrame):
    """
    (전일 고가, 전일 저가, 전일 종가)를 봉 단위로 펼쳐 돌려준다.

    lookahead 주의: groupby(날짜).transform("max")를 그냥 쓰면 그날 장 마감까지의
    고가가 아침 봉에 들어간다 — 미래를 보는 것이다. 그래서 '일별로 집계 → 하루
    shift → 다시 봉에 매핑' 순서로 간다. 각 봉은 이미 끝난 어제 값만 본다.
    """
    d = bar_dates(df)
    daily = df.groupby(d).agg(high=("high", "max"), low=("low", "min"),
                              close=("close", "last")).shift(1)
    return (d.map(daily["high"]), d.map(daily["low"]), d.map(daily["close"]))
