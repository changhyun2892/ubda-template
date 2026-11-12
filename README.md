# UBDA 기업 경영분석 플랫폼

DART 공시를 바탕으로 만든 기업별 경영분석 대시보드를 **저장소 하나, 사이트 하나**에 모아 둔 플랫폼입니다.
불닭(삼양식품) 대시보드의 제작 과정인 DART 수집 → 원문 대조 기록 → 재무비율 계산 → 자동 점검 → 자동 업데이트 → 배포를 어느 기업에나 적용할 수 있게 일반화했습니다.

> 수업용 경영분석이며 투자 추천이 아닙니다. 원본인 `vuldak-dashboard`는 수정하지 않았습니다.

- **공개 주소: https://ubda-template.onrender.com/** (Render 정적 사이트, push하면 자동 재배포)
- 첫 화면 `index.html`: **3D 뉴런 포털** — CORE → 산업 → 카테고리 → 기업 구체를 눌러 펼치고, 기업을 누르면 핵심 KPI와 '대시보드 열기'. 드래그 회전·휠/핀치 확대·검색. WebGL이 안 되는 기기는 `list.html`(목록형)
- 기업 대시보드: `dashboard.html?c=<기업폴더>` (예: `dashboard.html?c=ottogi`)

## 새 기업 추가하기

대화창에서 "OOO 경영 대시보드 만들어줘"라고 하면 AI 스킬 `ubda-company-dashboard`가 아래 과정을 진행합니다. 자세한 순서는 [docs/AI_작업절차.md](docs/AI_작업절차.md)에 있습니다.

1. `companies/<영문폴더>/company.json` 만들기: 이름, 종목코드, `yahoo_ticker`(코스피 `.KS` / 코스닥 `.KQ`), 산업, 카테고리, 경쟁사, 색상
2. 같은 폴더에 `verify_expectations.json`(처음에는 checks 비움)과 `data/manual/` 헤더 파일 2개 만들기
3. push → GitHub Actions가 **모든 기업**을 수집·계산·점검한 뒤 `companies/index.json`(기업 목록)을 갱신 → Render 자동 배포
4. 산업 KPI(제품군 매출, 수출 등)를 공시 원문에서 찾아 `data/manual/kpi_values.csv`에 출처와 함께 입력

**처음 한 번만** 사람이 하면 되는 일:
- 저장소 Secrets에 `DART_API_KEY` 등록 (완료)
- Render 정적 사이트 1개 연결 (완료 — https://ubda-template.onrender.com/)

## 내 컴퓨터에서 보기 / 실행

```bat
py -m http.server 8000                         → http://localhost:8000
set DART_API_KEY=발급키
py scripts\run_all.py                          모든 기업: 수집 → 주가 → 계산 → 점검 → 기업 목록
py scripts\run_all.py --only ottogi            한 기업만
py scripts\run_all.py --steps build,verify     인터넷 없이 계산·점검만
py tests\test_pipeline.py                      가짜 DART 서버로 전체 흐름 시험 (27개)
py tests\ui_check.py                           (선택, playwright 필요) 목록·모든 기업 화면 점검
```
`index.html`을 더블클릭해서 열면 브라우저가 파일 읽기를 막아 화면이 나오지 않습니다. 위처럼 로컬 서버로 여세요. 스크립트는 Python 표준 라이브러리만 사용합니다.

## 대시보드 기능
개요(연간/분기) · 기업 비교 · 손익 · 분기 · 재무비율 · 재무상태·현금 · 주가 · 산업 KPI · DART 자동 업데이트 · 출처·검증 · **메인 스크린**(발표용, F 전체화면) · **데이터 질의**(규칙 기반 CSV 계산, AI 호출 없음) · **배치 편집**(카드 끌기)

## 데이터 상태 표시 (임의 생성 금지)

| 상태 | 뜻 |
|---|---|
| 원문 대조 일치 | 사람이 사업보고서 원문과 직접 대조함 → `data/manual/audit_overrides.csv` |
| 자동 · 대조 전 | OpenDART 공식 API 값, 또는 AI가 공시 원문에서 옮긴 값. 사람 대조 전 |
| 불일치 | 사람이 대조한 값과 현재 값이 다름 (정정공시 가능성) → 점검 실패 |
| 미확인 / 미공개 | 찾지 못했거나 회사가 공개하지 않음 — **숫자를 넣지 않음** |

## 비용
GitHub 공개 저장소와 Actions, Render 정적 사이트, OpenDART API(하루 20,000건, 기업 1곳 첫 수집에 약 20건)는 모두 무료입니다.
주가는 Yahoo Finance의 비공식 무료 경로를 씁니다. 수집이 실패하면 기존 파일을 그대로 유지합니다.

## 폴더 구조

```
index.html                 3D 뉴런 포털 (Three.js, assets/portal3d.js)
list.html                  기업 목록 (목록형, 3D를 못 쓰는 기기용)
dashboard.html             공용 기업 대시보드 (?c=기업폴더)
assets/                    화면 코드·스타일 · assets/vendor/three = Three.js r170 (MIT, 저장소에 포함해 외부 접속 없이 동작)
companies/index.json       기업 목록 + 그래프(CORE→산업→카테고리→기업) — 포털이 읽음 (자동 생성)
companies/<기업>/          company.json · verify_expectations.json · data/(자동 생성) · data/manual/(사람·AI 입력)
industries/*.json          산업별 KPI 목록 (식품·은행·반도체·자동차·유통·플랫폼)
scripts/                   collect_dart · update_stock · build_dataset · verify_data · run_all · build_index
tests/                     가짜 DART 서버 테스트, 브라우저 화면 점검
docs/                      전체 구조, AI 작업 절차
```
