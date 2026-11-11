# UBDA 전체 구조

```
 사용자: "오리온 대시보드 만들어줘"
        │
 ① AI 경영분석 엔진 (Claude + 스킬 ubda-company-dashboard)   ← 판단: 기업 식별·산업 분류·KPI 조사·해석
        │  companies/<기업>/company.json 작성, 산업 KPI를 출처와 함께 입력
        ▼
 ② 실행 코드 (이 템플릿 scripts/, GitHub Actions)             ← 기계 작업: 수집·계산·점검 (AI가 숫자를 만들지 않음)
        │  run_all: 기업마다 collect_dart → update_stock → build_dataset → verify_data, 마지막에 build_index → 커밋
        ▼
 ③ 기업별 대시보드 (dashboard.html?c=기업, 같은 저장소·같은 Render 사이트)
        │  companies/<기업>/data/summary.json → companies/index.json (기업 목록 + 그래프)
        ▼
 ④ 3D 뉴런형 포털 (index.html 자리, 다음 단계)                 ← companies/index.json의 graph를 그대로 그림
        CORE → 산업(industries/*.json) → 카테고리(company.json categories) → 기업 → 대시보드 열기
```

## AI가 하는 일과 코드가 하는 일

| 구분 | 담당 | 이유 |
|---|---|---|
| 기업 식별, 종목코드 확인, 산업·카테고리 분류, 경쟁사 선정 | AI | 판단이 필요함 |
| 재무제표 수집, 분기값 계산, 비율 계산, 점검 | 코드 | 같은 입력이면 같은 결과가 나와야 함 |
| 산업 KPI 찾기 (사업보고서 본문 표) | AI가 찾아 출처와 함께 기록 → 코드가 출처 누락 차단 → 사람 검토 | 표 형식이 회사마다 다름 |
| 해석 문장 | AI 초안 → 사람 검토 | 인과관계를 단정하지 않기 위해 |

## 3D 포털과 연결하는 규칙 (companies/index.json)

`scripts/build_index.py`가 모든 기업 폴더를 읽어 `companies/index.json`을 만든다. 포털은 이 파일 하나만 읽는다.
- `graph.nodes`: `core` / `industry`(색 포함) / `category` / `company`(url = `dashboard.html?c=기업`)
- `graph.links`: CORE→산업→카테고리→기업
- 기업이 여러 카테고리에 속하면(예: 롯데웰푸드 = 스낵·아이스크림) 기업 노드는 1개이고 연결선만 2개다.
- `companies[]`: 정보 패널에 쓸 핵심 KPI, 검증 현황, 산업 KPI 확보 수

React Force Graph 3D의 `graphData`는 `{nodes, links}` 형식이라 거의 그대로 넣을 수 있다.

## 산업 모듈 확장

새 산업은 `industries/<id>.json` 파일 하나를 추가하면 됩니다(KPI 목록과 찾을 곳, 주의사항).
은행처럼 손익계산서 구조가 다른 업종은 매출액·매출원가 계정이 없어 '계정 미발견'으로 표시됩니다. 이 경우 은행용 계정(이자수익 등)을 `collect_dart.py`의 ACCOUNTS에 추가하는 작업이 필요합니다. **아직 하지 않았습니다.**
