# toss

토스증권 OpenAPI로 만든 KOSPI 50 종목 모의투자사이트**

![모의투자 매매 화면1](pythonversion/docs/screenshots/trading.jpg)
![모의투자 매매 화면2](pythonversion/docs/screenshots/orderbook.jpg)

실제 화면

```bash
pip install fastapi uvicorn websockets requests pandas numpy python-dotenv
python -m uvicorn paper.app:app --reload    # http://localhost:8000
```

가장 상위 디렉토리 `.env`에 client_key, client_secret을 각각 `TOSS_CLIENT_ID` / `TOSS_CLIENT_SECRET`를 저장하고, 토스증권 홈페이지에서 IP를 등록하면 사용할 수 있다.


## 구조

```
toss/
├── paper/          모의투자 앱
├── strategies/     백테스팅
├── backtest.py     매매 전략          
└── DB.py           DB관리 (데이터 받아오기 포함)
```


### 구조

```
브라우저 ──/ws──┐
브라우저 ──/ws──┤  app.py (FastAPI)  ──웹소켓 1개──▶  토스 실시간
브라우저 ──/ws──┘     │                              (trade:kr / orderbook:kr)
                      ├─ feed.py    프레임 파싱 · 재접속 · 구독 선언
                      ├─ broker.py  체결 엔진 · 포트폴리오 (paper.db)
                      ├─ ticks.py   KRX 호가단위
                      └─ toss.py    읽기 전용 REST
```

| 파일 | 역할 |
|---|---|
| `app.py` | FastAPI 서버. REST + `/ws` 팬아웃 + 정적 페이지 |
| `feed.py` | 토스 웹소켓 업스트림 관리 |
| `broker.py` | 체결 엔진과 포트폴리오. |
| `ticks.py` | 호가단위 표와 지정가 유효성 |
| `toss.py` | 읽기 전용 REST 래퍼 |
| `static/index.html` | 화면 전부 (빌드 없음) |


## 데이터

- `market_data.db` — 백테스팅 전용
- `paper.db` — 모의투자 주문·체결.
