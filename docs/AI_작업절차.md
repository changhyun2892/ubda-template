# AI 작업 절차 — "OOO 경영 대시보드 만들어줘"

새 대화에서 이 문서를 먼저 읽고 순서대로 진행합니다. (스킬 `ubda-company-dashboard`와 같은 내용)

## 절대 규칙
- 원본 `changhyun2892/vuldak-dashboard`는 수정하거나 덮어쓰지 않는다.
- 공개되지 않은 데이터는 만들지 않는다. 찾지 못하면 `미확인`, 회사가 공개하지 않으면 `미공개`로 두고 숫자를 비운다.
- 회사 전체 매출과 제품군·카테고리 매출을 섞지 않는다. `scope` 열에 범위를 적는다.
- 실행하지 않은 코드, 확인하지 않은 값은 완료라고 말하지 않는다.
- DART API 키는 채팅으로 받지 않는다. 사용자가 GitHub Secrets에 직접 넣는다.

## 순서
1. **기업 식별 (AI 판단)**: 웹 검색으로 정식 회사명, 종목코드 6자리, 시장(코스피 `.KS` / 코스닥 `.KQ`)을 확인한다. 지주사와 사업회사가 나뉘어 있으면 어느 쪽인지 사용자에게 한 번 묻는다. 산업 id는 `industries/`에서 고르고, 카테고리(여러 개 가능)와 경쟁사 2~4개를 정한다.
2. **저장소 준비**: 사용자가 GitHub에 빈 Public 저장소 `<영문약칭>-dashboard`를 만들어 둔다(Claude 앱 권한 필요). `add_repo`(push)로 연결하고, ubda-template 내용을 `.git` 없이 복사한다.
3. **설정**: `company.json`을 새 기업 값으로 채운다(dashboard_url은 비움). `verify_expectations.json`은 company_id만 바꾸고 checks를 `[]`로 비운다. **`data/`에서 `manual/`을 뺀 나머지(템플릿 기준 기업인 삼양식품의 데이터)는 모두 지운다**. 지우지 않으면 새 기업 이름으로 삼양식품 숫자가 표시된다. `data/manual/*.csv`는 헤더만 남긴다.
4. **로컬 점검 후 push**: `python tests/test_pipeline.py`(26개 통과), `python tests/ui_check.py`(빈 상태 화면)를 실행한 뒤 커밋하고 push한다.
5. **사용자 요청**: 새 저장소 Settings → Secrets and variables → Actions에 `DART_API_KEY`를 등록하고, Actions → 데이터 업데이트 → Run workflow를 눌러 달라고 한다.
6. **결과 확인**: `git pull` 후 `data/update_log.json`, `data/verify_report.json`(실패·경고), `data/financials.csv`(`계정 미발견`)를 확인한다. 계정명 차이로 못 찾은 계정이면 `collect_dart.py`의 ACCOUNTS를 보완한다(템플릿에도 반영할지 묻는다).
7. **산업 KPI 조사**: `industries/<industry>.json`의 KPI마다 최신 사업보고서(`source_registry.csv`의 DART 뷰어 URL)를 WebFetch로 열어 해당 표를 찾는다. 찾은 값은 `data/manual/kpi_values.csv`에 넣는다.
   - 상태는 `자동 수집 · 원문 대조 전`(AI가 옮긴 값)으로 둔다. `원문 대조 일치`는 사람이 확인했을 때만 쓴다.
   - 원문의 백만원·천원 단위는 KRW로 환산하고, note에 원래 단위를 적는다.
   - 검색 관심도는 사용자가 CSV를 내려받아야 하며, 판매량으로 해석하지 않는다.
   - 입력한 뒤 `build_dataset.py`와 `verify_data.py`를 실행해 실패가 없을 때 push한다.
8. **배포**: 사용자에게 Render → New → Static Site → 저장소 연결(Build Command 비움, Publish Directory `.`)을 요청한다. 받은 주소를 `company.json`의 `dashboard_url`에 넣고 push한다.
9. **보고**: 결론을 먼저 쓴다. 수집 연도와 점검 결과, 산업 KPI 확보 수와 미확인 목록, 사용자가 할 일(원문 대조 기록법, Render)을 정리하고, 실행하지 않은 것은 따로 표시한다.

## 사람이 원문 대조한 기록
`data/manual/audit_overrides.csv`에 audit_id(예: F-2025-revenue), result(`원문 대조 일치`), verified_value(원 단위), source_location(예: 사업보고서 p.48 연결 손익계산서), checked_on, checked_by를 적는다. 나중에 정정공시로 값이 바뀌면 자동으로 `불일치`가 표시된다.
