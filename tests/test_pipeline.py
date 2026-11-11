#!/usr/bin/env python3
"""
파이프라인 오프라인 테스트 — 인터넷 없이 가짜 DART·Yahoo 서버로 전체 흐름을 시험합니다.

    python tests/test_pipeline.py

저장소 파일은 건드리지 않고 임시 폴더에 복사해서 실행합니다.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import mock_server  # noqa: E402

passed, failed = [], []


def ok(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + (f" — {detail}" if detail else ""))


def workdir(company: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp(prefix="ubda_test_"))
    for n in ("scripts", "industries"):
        shutil.copytree(REPO / n, d / n)
    for n in ("company.json", "verify_expectations.json"):
        shutil.copy(REPO / n, d / n)
    if company:
        cfg = json.loads((d / "company.json").read_text(encoding="utf-8"))
        cfg.update(company)
        (d / "company.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return d


def run(d: Path, script: str, base: str, key="TESTKEY") -> subprocess.CompletedProcess:
    env = {**os.environ, "DART_BASE_URL": base + "/api", "YAHOO_HOSTS": base, "DART_API_KEY": key,
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    return subprocess.run([sys.executable, str(d / "scripts" / script)], env=env, capture_output=True, text=True, cwd=d, timeout=120)


def rows(p: Path):
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    data = mock_server.Data()
    srv, base = mock_server.start(data)

    print("\n[1] 삼양식품 전체 실행 (수집 → 주가 → 계산 → 검증)")
    d = workdir()
    for s in ("collect_dart.py", "update_stock.py", "build_dataset.py"):
        r = run(d, s, base)
        ok(f"{s} 정상 종료", r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "")
    v = run(d, "verify_data.py", base)
    rep = json.loads((d / "data" / "verify_report.json").read_text(encoding="utf-8"))
    fails = [f"{x['name']}: {x['detail']}" for x in rep["results"] if x["state"] == "실패"]
    ok("검증 실패 0건", v.returncode == 0 and not fails, "; ".join(fails[:3]) or str(rep["counts"]))
    exp = next((x for x in rep["results"] if x["name"] == "사람이 대조한 기준값과 일치"), {})
    ok("사람이 원문 대조한 기준값 48개 모두 일치", exp.get("detail") == "48/48개", exp.get("detail", ""))
    fin = rows(d / "data" / "financials.csv")
    ok("연간 연도 2022~2025", sorted({r["year"] for r in fin}) == ["2022", "2023", "2024", "2025"])
    q = rows(d / "data" / "quarterly.csv")
    ok("분기 실적 12개 이상 (2023Q1~2025Q4)", len({r["period"] for r in q}) >= 12, f"{len({r['period'] for r in q})}개")
    capex = next(r for r in fin if r["year"] == "2025" and r["metric"] == "capex")
    met = {(r["year"], r["metric"]): r for r in rows(d / "data" / "metrics.csv")}
    ok("2025 영업이익률 22.29%", round(float(met[("2025", "operating_margin_pct")]["value"]), 2) == 22.29, met[("2025", "operating_margin_pct")]["value"])
    ok("2022 증가율은 전기 자료 없어 빈칸", met[("2022", "revenue_growth_pct")]["value"] == "")
    fcf = int(met[("2025", "simple_fcf")]["value"])
    ok("음수로 온 유형자산 취득액을 절대값으로 FCF 계산", fcf == 309287213625 - 448988219606, f"capex 원값 {capex['value']} · FCF {fcf:,}")
    st = rows(d / "data" / "research_status.csv")
    ok("식품 산업 KPI 8개가 '미확인'으로 표시 (임의 생성 없음)", sum(1 for r in st if r["status"] == "미확인") == 8)
    sm = json.loads((d / "data" / "summary.json").read_text(encoding="utf-8"))
    ok("summary.json에 산업·카테고리·핵심 KPI", sm["industry"] == "food" and sm["categories"] == ["라면"] and sm["kpis"]["revenue"] == 2351785163786)
    stock = rows(d / "data" / "stock_daily.csv")
    ok("주가 940행 + 코스피 지수", len(stock) == 940 and stock[0]["index_close"] != "", f"{len(stock)}행")
    reg = rows(d / "data" / "source_registry.csv")
    ok("정기공시가 아닌 공시는 제외", not any("주요사항" in r["title"] for r in reg))

    print("\n[2] 다시 실행 — 새 보고서가 없으면 재무 API를 다시 부르지 않음")
    before = data.calls["/api/fnlttSinglAcntAll.json"]
    r = run(d, "collect_dart.py", base)
    ok("재실행 시 새로 반영 0건", "새로 반영 0건" in r.stdout, r.stdout.strip().splitlines()[0])
    ok("재무 API 추가 호출 없음", data.calls["/api/fnlttSinglAcntAll.json"] == before)

    print("\n[3] 사람 대조 기록 반영과 불일치 감지")
    man = d / "data" / "manual" / "audit_overrides.csv"
    with man.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["F-2025-revenue", "원문 대조 일치", "2351785163786", "사업보고서 p.48 연결 IS", "2026-11-12", "사용자", ""])
        w.writerow(["F-2024-revenue", "원문 대조 일치", "1700000000000", "사업보고서 p.48", "2026-11-12", "사용자", ""])
    run(d, "build_dataset.py", base)
    led = {r["audit_id"]: r for r in rows(d / "data" / "audit_ledger.csv")}
    ok("대조 일치 기록이 재빌드 후에도 유지", led["F-2025-revenue"]["result"] == "원문 대조 일치")
    ok("대조값과 다르면 '불일치'", led["F-2024-revenue"]["result"] == "불일치", led["F-2024-revenue"]["note"])
    ok("불일치가 있으면 검증 실패(종료코드 1)", run(d, "verify_data.py", base).returncode == 1)

    print("\n[4] 산업 KPI: 출처 없는 숫자·추정값 차단")
    d4 = workdir()
    for s in ("collect_dart.py", "build_dataset.py"):
        run(d4, s, base)
    kp = d4 / "data" / "manual" / "kpi_values.csv"
    with kp.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["export_revenue", "2025", "2025", "면스낵 수출", "100", "KRW", "제품군", "", "", "자동 수집 · 원문 대조 전", "", ""])
        w.writerow(["market_share", "2025", "2025", "라면", "15", "%", "", "", "", "미확인", "", "추정"])
    run(d4, "build_dataset.py", base)
    v4 = run(d4, "verify_data.py", base)
    ok("출처 없는 KPI 값 → 실패", "[실패] 산업 KPI 값마다 출처 URL" in v4.stdout)
    ok("'미확인'에 숫자를 넣으면 → 실패", "[실패] 미확인·미공개 항목에 숫자 없음" in v4.stdout)

    print("\n[5] 연결재무제표가 없는 회사 → 별도(OFS)로 자동 전환")
    srv.shutdown()
    data2 = mock_server.Data(stock_code="123456", corp_code="00999999", corp_name="테스트식품", no_cfs=True)
    srv, base = mock_server.start(data2)
    d5 = workdir({"company_id": "TS", "name": "테스트식품", "stock_code": "123456", "yahoo_ticker": "123456.KS"})
    run(d5, "collect_dart.py", base)
    run(d5, "build_dataset.py", base)
    f5 = rows(d5 / "data" / "financials.csv")
    ok("범위 '별도'로 기록", f5 and all(r["scope"] == "별도" for r in f5 if r["value"]), f"{len(f5)}행")
    v5 = run(d5, "verify_data.py", base)
    ok("다른 회사에는 삼양 기준값을 적용하지 않음", "기준 파일은 SY용" in v5.stdout)

    print("\n[6] 실패해도 사이트가 깨지지 않음")
    d6 = workdir({"stock_code": "000000"})
    r6 = run(d6, "collect_dart.py", base)
    log = json.loads((d6 / "data" / "update_log.json").read_text(encoding="utf-8"))
    ok("없는 종목코드 → 경고만, 종료코드 0", r6.returncode == 0 and log["dart"]["status"] == "실패", log["dart"]["message"][:60])
    d7 = workdir()
    r7 = run(d7, "collect_dart.py", base, key="")
    ok("API 키 없음 → 경고만, 종료코드 0", r7.returncode == 0 and "DART_API_KEY가 없습니다" in r7.stderr)
    r8 = run(d7, "collect_dart.py", base, key="WRONG")
    ok("잘못된 API 키 → 경고만", r8.returncode == 0 and "등록되지 않은 키" in r8.stderr)
    srv.shutdown()

    print(f"\n결과: 통과 {len(passed)} · 실패 {len(failed)}")
    for n in failed:
        print("  실패:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
