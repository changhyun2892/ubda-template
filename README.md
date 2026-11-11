# UBDA 기업 경영분석 대시보드 템플릿

**기업 정보는 `company.json` 한 파일에만 있습니다.** 이 파일을 바꾸면 같은 구조의 대시보드가 다른 기업으로 만들어집니다.
불닭(삼양식품) 대시보드의 제작 과정인 DART 수집 → 원문 대조 기록 → 재무비율 계산 → 자동 점검 → GitHub Actions 자동 업데이트 → Render 배포를 기업과 무관하게 쓸 수 있도록 만든 템플릿입니다.

> 수업용 경영분석이며 투자 추천이 아닙니다. 원본인 `vuldak-dashboard`는 수정하지 않았습니다.

## 새 기업 대시보드 만드는 법

AI 스킬(`ubda-company-dashboard`)이 2~4번과 산업 KPI 조사를 대신합니다. 아래는 사람이 직접 할 때의 순서입니다.

| 순서 | 할 일 | 누가 |
|---|---|---|
| 1 | GitHub에서 이 저장소를 **Use this template → Create a new repository** (예: `orion-dashboard`, Public) | 사람 (또는 AI가 빈 저장소에 복사) |
| 2 | `company.json` 수정: 이름, 종목코드 6자리, `yahoo_ticker`(코스피 `.KS` / 코스닥 `.KQ`), 산업, 카테고리, 경쟁사, 색상 | AI |
| 3 | `verify_expectations.json`의 `company_id`를 새 기업 것으로 바꾸고 `checks`를 비움 | AI |
| 4 | 저장소 **Settings → Secrets and variables → Actions → New repository secret**: 이름 `DART_API_KEY`, 값 = 발급받은 키 | **사람** (키는 채팅에 붙여넣지 않기) |
| 5 | **Actions → 데이터 업데이트 → Run workflow** (push하면 자동 실행) | 사람 또는 자동 |
| 6 | 산업 KPI를 공시 원문에서 찾아 `data/manual/kpi_values.csv`에 출처와 함께 입력 | AI → 사람 검토 |
| 7 | Render → New → **Static Site** → 저장소 연결, Build Command 비움, Publish Directory `.` | **사람** |
| 8 | 배포 주소를 `company.json`의 `dashboard_url`에 기록 (3D 포털이 이 값을 읽음) | AI |

## 내 컴퓨터에서 보기

```bat
py -m http.server 8000        (Mac·Linux: python3 -m http.server 8000)
```
그다음 http://localhost:8000 을 엽니다. `index.html`을 더블클릭해서 열면 브라우저가 CSV 읽기를 막아 화면이 나오지 않습니다.

데이터를 직접 만들 때는 아래 순서로 실행합니다. 표준 라이브러리만 쓰므로 pip 설치가 필요 없습니다.
```bat
set DART_API_KEY=발급키
py scripts\collect_dart.py      1. DART 정기보고서 수집 → data/raw/
py scripts\update_stock.py      2. 주가 → data/stock_daily.csv
py scripts\build_dataset.py     3. 화면용 CSV·재무비율·검증장부·summary.json
py scripts\verify_data.py       4. 점검 (실패가 있으면 종료코드 1)
py tests\test_pipeline.py       (선택) 인터넷 없이 가짜 DART 서버로 전체 흐름 시험
```

## 데이터 상태 표시 (임의 생성 금지)

| 상태 | 뜻 |
|---|---|
| 원문 대조 일치 | 사람이 사업보고서 원문(PDF·DART 뷰어)과 직접 대조함 → `data/manual/audit_overrides.csv` |
| 자동 · 대조 전 | OpenDART 공식 API 값 그대로. 사람이 원문과 대조하기 전 |
| 불일치 | 사람이 대조한 값과 현재 값이 다름 (정정공시 가능성) → 점검 실패 |
| 미확인 | 찾지 못했거나 출처가 불충분 — **숫자를 넣지 않음** |
| 미공개 | 회사가 공개하지 않는 항목 — **숫자를 넣지 않음** |

`verify_data.py`는 출처 URL이 없는 산업 KPI 값, 그리고 '미확인'이나 '미공개'인데 숫자가 들어 있는 항목을 **실패**로 처리합니다.

## 자동으로 되는 것 / 사람이 해야 하는 것

- **자동 (무료)**: 연간·분기 연결재무(손익·재무상태·현금흐름 14개 계정), 재무비율 15개, 분기 단일 실적, 정정공시 반영, 주가·시장지수, 출처 목록, 점검
- **AI가 찾되 사람이 검토**: 제품군 매출, 수출, 해외법인, 원재료 가격, 가동률, 시장점유율 같은 산업 KPI. 사업보고서 본문 표의 형식이 회사마다 달라 완전 자동화가 어렵습니다.
- **사람만 가능**: API 키 등록, Render 연결, 원문 대조 확인, Google Trends·네이버 데이터랩 CSV 다운로드

## 비용

GitHub 공개 저장소와 Actions, Render 정적 사이트, OpenDART API(하루 20,000건)는 모두 무료입니다.
주가는 Yahoo Finance의 비공식 무료 경로를 씁니다. 경로가 바뀌거나 막히면 수집이 실패할 수 있으며, 그때는 기존 파일을 그대로 유지합니다.

## 폴더 구조

```
company.json              ← 기업마다 바뀌는 유일한 설정
industries/*.json         산업별 KPI 목록 (식품·은행·반도체·자동차·유통·플랫폼)
scripts/                  수집·계산·점검 (Python 표준 라이브러리)
data/raw/                 API에서 받은 원값 (자동 생성)
data/manual/              사람·AI가 출처와 함께 입력하는 값 (빌드해도 유지)
data/*.csv, summary.json  화면용 데이터 (자동 생성)
index.html, assets/       대시보드 화면 (외부 라이브러리 없음)
tests/                    가짜 DART 서버 테스트, 브라우저 화면 점검
verify_expectations.json  사람이 원문 대조한 기준값 (자동 수집 결과와 비교)
docs/ARCHITECTURE.md      전체 시스템(AI 엔진·산업 모듈·대시보드·3D 포털) 연결 구조
```
