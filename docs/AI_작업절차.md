# AI 작업 절차 — "OOO 경영 대시보드 만들어줘"

새 대화에서 이 문서를 먼저 읽고 순서대로 진행합니다. (스킬 `ubda-company-dashboard`와 같은 내용)

## 절대 규칙
- 원본 `changhyun2892/vuldak-dashboard`는 수정하거나 덮어쓰지 않는다.
- 공개되지 않은 데이터는 만들지 않는다. 찾지 못하면 `미확인`, 회사가 공개하지 않으면 `미공개`로 두고 숫자를 비운다.
- 회사 전체 매출과 제품군·카테고리 매출을 섞지 않는다. `scope` 열에 범위를 적는다.
- 실행하지 않은 코드, 확인하지 않은 값은 완료라고 말하지 않는다.
- DART API 키는 채팅으로 받지 않는다. 사용자가 GitHub Secrets에 직접 넣는다.
- **3D 포털(`index.html`, `assets/portal3d.*`, `assets/vendor/three/`)은 수정하지 않는다** (사용자 지시 2026-11-12). 기업을 추가하면 노드는 `companies/index.json`으로 자동 반영되므로 손댈 필요가 없다. 화면 점검(ui_check)의 3D 항목은 확인용으로만 돌린다.

## 구조
저장소는 `changhyun2892/ubda-template` **하나**이고, 기업마다 `companies/<영문폴더>/`를 하나씩 둔다. 기업별 저장소는 만들지 않는다.
DART_API_KEY와 Render 연결은 이미 한 번 해 두었으므로 기업을 추가할 때마다 다시 요청하지 않는다.

## 순서
1. **기업 식별 (AI 판단)**: 웹 검색으로 정식 회사명, 종목코드 6자리, 시장(코스피 `.KS` / 코스닥 `.KQ`)을 확인한다. 지주사와 사업회사가 나뉘어 있으면 어느 쪽인지 사용자에게 한 번 묻는다. 산업 id는 `industries/`에서 고르고(없는 산업이면 새 json을 추가), 카테고리(여러 개 가능)와 경쟁사 2~4개를 정한다. 이미 `companies/`에 있는 기업이면 새로 만들지 않고 알린다.
2. **기업 폴더 만들기**: `companies/<영문폴더>/` 아래에 다음을 만든다.
   - `company.json`: 기존 기업 파일을 참고해 작성한다(dashboard_url은 비움).
   - `verify_expectations.json`: `{"company_id": "...", "checks": []}`
   - `data/manual/kpi_values.csv`, `data/manual/audit_overrides.csv`: 헤더만 둔다(다른 기업 파일의 첫 줄을 복사).
   - 다른 기업 폴더의 `data/` 파일은 절대 복사하지 않는다(다른 회사 숫자가 섞임).
3. **로컬 점검**: `python tests/test_pipeline.py`(27개 통과), `python scripts/build_index.py`, `python tests/ui_check.py`(새 기업은 '데이터 없음' 안내가 나오면 정상)를 실행한다.
4. **push**: 커밋하고 push하면 Actions가 자동으로 실행되어 모든 기업을 수집하고 커밋한다(2~3분). 실행 상태는 `https://api.github.com/repos/changhyun2892/ubda-template/actions/runs?per_page=3`으로 확인한다.
5. **결과 확인** (`companies/_runs/last_run.json`에 기업·단계별 소요 시간과 결과가 남는다. 판관비 등 손익 계정을 못 찾으면 `raw/unmatched_accounts.json`에 그 보고서의 계정 이름 목록이 남는다): `git pull` 후 `companies/<기업>/data/update_log.json`, `verify_report.json`(실패·경고), `financials.csv`(`계정 미발견`)를 확인한다. 계정명 차이로 못 찾은 계정이면 `scripts/collect_dart.py`의 ACCOUNTS를 보완한다(모든 기업에 적용되므로 기존 기업 점검도 다시 확인).
6. **산업 KPI 조사 (기본으로 함께 진행 — 사용자 지시 2026-11-12: 따로 묻지 말고 한 번에)**: `industries/<industry>.json`의 KPI마다 최신 사업보고서를 읽는다. `source_registry.csv`에 DART 뷰어 URL이 있고, KIND 원문 `kind.krx.co.kr/external/...htm`이 WebFetch로 읽기 쉽다. 찾은 값은 `companies/<기업>/data/manual/kpi_values.csv`에 넣는다.
   - 상태는 `자동 수집 · 원문 대조 전`(AI가 옮긴 값)으로 둔다. `원문 대조 일치`는 사람이 확인했을 때만 쓴다.
   - 원문의 백만원·천원 단위는 KRW로 환산하고, note에 원래 단위를 적는다.
   - 회사 전체 매출과 제품군 매출을 구분해 scope에 적는다. 관계사(예: 제조 자회사)를 통한 매출 구조도 note에 남긴다.
   - 검색 관심도는 사용자가 CSV를 내려받아야 하며, 판매량으로 해석하지 않는다.
   - 본문은 5단계 자동 실행 후 `companies/<기업>/data/raw/business_<연도>.txt`에 이미 저장되어 있다. 이 파일에서 '부문별 매출', '지역별 매출', '매출처별 판매비중', '종속회사별 요약 재무현황', '주요 원재료', '가동률', '생산실적', '시장점유율' 표를 찾는다.
   - 표의 당기·전기(·전전기) 값을 모두 옮긴다. 합계가 있는 표는 합계 = 연결 매출인지 확인한다(자동 검산도 돈다).
   - 입력한 뒤 `python scripts/run_all.py --only <기업> --steps build,verify`로 실패가 없는지 확인하고 push한다.
7. **보고** (재무 + 산업 KPI를 한 번에): 결론을 먼저 쓴다. 대시보드 주소(`<사이트>/dashboard.html?c=<기업>`), 수집 연도와 점검 결과, 산업 KPI 확보 수와 미확인 목록, 사용자가 할 일(원문 대조 기록법)을 정리하고, 실행하지 않은 것은 따로 표시한다.

## 사람이 원문 대조한 기록
`companies/<기업>/data/manual/audit_overrides.csv`에 audit_id(예: F-2025-revenue), result(`원문 대조 일치`), verified_value(원 단위), source_location(예: 사업보고서 p.48 연결 손익계산서), checked_on, checked_by를 적는다. 나중에 정정공시로 값이 바뀌면 자동으로 `불일치`가 표시된다.
