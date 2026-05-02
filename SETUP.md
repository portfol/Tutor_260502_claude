# 버핏 봇 — DART + pykrx + GPT + FastAPI

`Readme.txt`의 워렌 버핏 8원칙을 코드로 옮긴 **분석 + 백테스팅** 웹앱.
실거래 없이 데이터 분석에만 집중합니다.

## 데이터 소스

| 데이터 | 소스 | 인증 |
|---|---|---|
| 재무제표 (10년치) | DART OpenAPI | API 키 필요 (무료) |
| 주가 (KRX 일봉) | pykrx | 불필요 |
| 정성 평가 (해자/경영진/30초 설명) | OpenAI GPT | API 키 필요 |

## 구조

```
Readme.txt              # 버핏 철학 (이 앱이 따르는 원칙)
config.py               # .env 설정 로더
dart_client.py          # DART OpenAPI 재무제표 자동조회
price_client.py         # pykrx KRX 일봉 조회
buffett_strategy.py     # 정량 스크리닝 + 내재가치(DCF) + 신호
gpt_analyst.py          # GPT 정성 평가
backtest_engine.py      # 분할매수 + 매도 트리거 백테스트
watchlist_store.py      # JSON 영속화
main.py                 # FastAPI 앱 + 라우트
templates/index.html    # 웹 대시보드 (4탭)
static/app.{css,js}     # 프론트엔드
data/                   # 런타임 (watchlist.json, corp_code_map.json)
```

## 설치

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 환경 변수

`.env.example` 을 `.env` 로 복사 후 채우세요:

| 키 | 설명 |
|---|---|
| `DART_API_KEY` | https://opendart.fss.or.kr 에서 무료 발급 |
| `OPENAI_API_KEY` | GPT 정성 평가용 |
| `MARGIN_OF_SAFETY` | 0.25 = 내재가치 대비 25% 이상 할인일 때만 매수 |
| `SPLIT_BUY_COUNT` | 백테스트 분할매수 횟수 (기본 3회) |

## 실행

```powershell
uvicorn main:app --reload
```

브라우저에서 http://127.0.0.1:8000

## 사용 흐름

1. **종목 등록 탭** → 티커(예: `005930`) 입력 → **📡 DART에서 자동조회** 클릭 → 10년치 재무 자동 채움 → 검토 후 **저장**
2. **분석 탭** → 종목 선택 → **분석 실행** → 정량 스크리닝 + 내재가치 + 현재가 비교 + GPT 정성평가
3. **백테스트 탭** → 종목 선택 → 초기자본/일수 설정 → KRX 일봉 데이터로 안전마진 분할매수 시뮬레이션 → CAGR/MDD/거래내역 출력

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/fetch-fundamentals/{ticker}` | DART 자동조회 |
| GET | `/api/watchlist` | 관찰리스트 조회 |
| POST | `/api/watchlist` | 등록/갱신 |
| DELETE | `/api/watchlist/{ticker}` | 삭제 |
| POST | `/api/analyze/{ticker}` | 정량 + GPT 분석 |
| POST | `/api/backtest/{ticker}` | 백테스트 실행 |
| GET | `/api/health` | 헬스체크 |

## 버핏 원칙 매핑

| 원칙 | 구현 |
|---|---|
| 이해의 영역 | `screen_company()` 의 `industry_whitelist` (선택적) |
| 경쟁우위 (해자) | GPT 가 0~10점 평가 |
| 사업의 체력 | 매출/영업이익 우상향, ROE 12%+, 부채비율, 이자보상배율, FCF 안정 |
| 안전마진 | `MARGIN_OF_SAFETY` 환경변수, 내재가치 대비 할인된 목표가 |
| 오너 마인드 | GPT 의 `management_score` |
| 장기 복리 | 백테스트는 분할매수 후 매도 트리거 외엔 보유 |

## ⚠️ 주의

- 학습/연구용 도구입니다. 실제 매매에 사용하기 전 충분히 백테스트하세요.
- DART 사업보고서는 **연간** 데이터, 작년치까지 가능. 분기 데이터는 미사용.
- 일부 회사는 영업CF/투자CF 계정명 표기 차이로 FCF 가 0 으로 잡힐 수 있음. `dart_client._ACCOUNT_KEYS` 후보 추가로 보완 가능.
- pykrx 는 KRX 비공식 스크래핑이라 거래소 사이트 구조 변경 시 동작 안 할 수 있음.
- 펀더멘털은 점-인-타임이 아닌 현재 스냅샷이라, 백테스트는 "과거 가격 vs 현재 펀더멘털 기준 내재가치" 비교임.
