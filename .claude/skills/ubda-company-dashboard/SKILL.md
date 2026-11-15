---
name: "ubda-company-dashboard"
description: "기업명만 받아 UBDA 저장소(changhyun2892/ubda-template)에 그 기업의 경영분석 대시보드(재무·산업 KPI·메인 스크린)를 추가할 때 사용. 예: '오리온 경영 대시보드 만들어줘'."
---

# UBDA 기업 경영 대시보드 제작

상세 절차는 `changhyun2892/ubda-template` 저장소의 `docs/AI_작업절차.md`가 기준이다. 먼저 ubda-template을 clone하고 그 문서를 읽은 뒤 순서대로 진행한다. 숫자 수집·계산·점검은 템플릿 코드가 하고, AI는 판단(기업 식별, 산업 분류, 산업 KPI 조사, 해석)만 한다.

## 절대 규칙
- 원본 `changhyun2892/vuldak-dashboard`는 수정하거나 덮어쓰지 않는다.
- 공개되지 않은 데이터는 만들지 않는다. 찾지 못하면 `미확인`, 회사가 공개하지 않으면 `미공개`로 두고 숫자를 비운다.
- 회사 전체 매출과 제품군·카테고리 매출을 섞지 않는다. `scope` 열에 범위를 적는다.
- 실행하지 않은 코드, 확인하지 않은 값은 완료라고 말하지 않는다.
- DART API 키는 채팅으로 받지 않는다. 사용자가 GitHub Secrets에 직접 넣는다.
- 3D 포털(index.html, assets/portal3d.*, assets/vendor/three/)은 수정하지 않는다. 기업 노드는 companies/index.json으로 자동 반영된다.
- 산업 KPI 조사는 따로 묻지 않고 재무 대시보드와 한 번에 진행한다.

## 구조
저장소는 `changhyun2892/ubda-template` 하나이고, 기업마다 `companies/<영문폴더>/`를 하나씩 둔다. 기업별 저장소는 만들지 않는다. DART_API_KEY(GitHub Secrets)와 Render 배포(https://ubda-template.onrender.com)는 이미 연결돼 있으므로 기업을 추가할 때마다 다시 요청하지 않는다. 대시보드 주소는 `dashboard.html?c=<영문폴더>`, 메인 스크린은 `screen.html?c=<영문폴더>`다.

## 순서 요약
1. 기업 식별: 웹 검색으로 정식 회사명, 종목코드 6자리, 시장(코스피 .KS / 코스닥 .KQ, 코스닥은 market_index ^KQ11), 산업 id(industries/ 중 하나, 없으면 새 json 추가), 카테고리, 경쟁사 2~4개를 정한다. 지주사와 사업회사가 헷갈리면 사용자에게 한 번 묻는다. 이미 companies/에 있으면 새로 만들지 않고 알린다.
2. 기업 폴더: `companies/<영문폴더>/`에 company.json(다른 기업 파일 참고, company_id는 기존과 겹치지 않게), verify_expectations.json(`{"company_id": "..", "checks": []}`), data/manual/kpi_values.csv·audit_overrides.csv(헤더만)를 만든다. 다른 기업의 data/ 파일은 절대 복사하지 않는다.
3. 점검 후 push: `python tests/test_pipeline.py`가 전부 통과하면 커밋·push한다. push하면 GitHub Actions(데이터 업데이트, 4묶음 동시 실행)가 DART 재무, 사업보고서 본문(raw/business_<연도>.txt), 종속회사 표(raw/overview_<연도>.txt), 주가를 수집하고 커밋한다(약 5~10분).
4. 결과 확인: git pull 후 verify_report.json(실패·경고), financials.csv의 '계정 미발견', companies/_runs/last_run_*.json을 확인한다. 계정명 차이면 scripts/collect_dart.py의 ACCOUNTS를 보완하고 기존 기업 점검도 다시 확인한다. 은행은 industry = bank로 은행 전용 계정·비율을 쓴다.
5. 산업 KPI 입력(기본으로 함께 진행): DART 원문 사이트는 WebFetch가 막혀 있으므로 raw/business_<연도>.txt를 읽는다. industries/<산업>.json의 KPI마다 부문별·지역별·판매경로 매출, 원재료, 가동률·생산실적, 연구개발비, 시장점유율 표를 찾아 data/manual/kpi_values.csv에 출처 URL·원문 위치·원래 단위와 함께 당기·전기·전전기 값을 모두 넣는다. 상태는 `자동 수집 · 원문 대조 전`. 직접 더한 값은 note에 '합산'을 적는다. 없으면 '미공개', 못 찾으면 '미확인'으로 비우고 이유를 note에 적는다.
6. 재무 점검: `python scripts/build_dataset.py --company <기업>`과 `python scripts/verify_data.py --company <기업>`이 실패 0이어야 한다. 과거 연도 표 합계가 그 해 보고서 값과 다르면(재작성) 그 행 scope에서 '연결'을 빼고 '○○ 보고서 비교 표시(재작성)'로 적고 note에 두 값을 남긴다. 숫자를 맞추려고 고치지 않는다.
7. 원문 대조: `python scripts/crosscheck_kpi.py <기업>`으로 KPI 숫자가 본문에 실제로 있는지, 여러 연도 값이 원문에서 같은 행·연도 순서인지 확인한다. '원문에서 못 찾음'·'연도 순서 의심'은 원문을 다시 읽고 고친다.
8. 화면 점검: `UI_ONLY=<기업> python tests/ui_check.py . <스크린샷폴더>`로 PC·모바일·메인 스크린이 실패 0인지 확인한다(전체는 10분이 넘으므로 기업을 나눠 돌린다). 그다음 data/manual/kpi_values.csv와 설정 파일만 커밋하고(로컬에서 만든 계산 결과 파일은 `git checkout -- companies`로 되돌림), `git pull --rebase` 후 push한다. Actions가 다시 계산·배포한다.
9. 보고: 결론 우선. 대시보드 주소, 재무 점검·원문 대조·화면 점검 결과, 산업 KPI 확보 현황과 미공개·미확인 목록과 이유, 사용자가 할 일, 실행하지 않은 것(예: 공개 사이트 직접 확인)을 구분한다.