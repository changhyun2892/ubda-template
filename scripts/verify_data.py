#!/usr/bin/env python3
"""
3단계 · 데이터 점검 → 화면 출력 + data/verify_report.json

    python scripts/verify_data.py --company <기업폴더>

data/ 파일을 읽기만 하고 고치지 않습니다. 결과는 통과 / 실패 / 경고 / 미실행으로 나눕니다.
 - 실패: 숫자가 서로 맞지 않거나 출처가 없는 값 → 반드시 확인
 - 경고: 회계상 그럴 수 있지만 사람이 한 번 볼 항목
실패가 하나라도 있으면 종료 코드 1 (GitHub Actions에서 빨간 X로 보임).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from ubda_common import (CDIR, DATA, ST_AUTO, ST_MISMATCH, ST_UNCONFIRMED, ST_UNDISCLOSED, ST_VERIFIED,
                         load_config, now_kst, num, read_csv)

results: list[dict] = []


def add(state: str, name: str, detail: str = "") -> None:
    results.append({"state": state, "name": name, "detail": detail})


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
    add("통과" if ok else ("경고" if warn_only else "실패"), name, detail)


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def restated_evidence(y: int, m: str) -> str:
    """같은 해 반기·3분기 보고서의 누적값이 앞 보고서 값 + 이번 3개월 값과 다르면, 뒤 보고서가 앞 분기를 재작성한 것.
    근거 문자열을 돌려주고, 재작성이 보이지 않으면 빈 문자열."""
    rows = {}
    for r in read_csv(CDIR / "data" / "raw" / "dart_financials.csv"):
        if int(r["bsns_year"]) == y and r["metric"] == m and not (m == "cost_of_sales" and r.get("account_nm", "").strip() == "영업비용"):
            v, cum = num(r["value"]), num(r["value_cumulative"])
            if m in ("interest_expense", "general_admin", "credit_loss"):  # build_dataset과 같게 금액 기준
                v, cum = (None if v is None else abs(v)), (None if cum is None else abs(cum))
            rows[r["reprt_code"]] = (v, cum)
    q1, h1, q3 = rows.get("11013"), rows.get("11012"), rows.get("11014")
    out = []
    for name, prev, cur in (("반기", q1, h1), ("3분기", h1, q3)):
        if prev and cur and None not in (prev[1], cur[0], cur[1]):
            expect = prev[1] + cur[0]
            if abs(cur[1] - expect) > 0.001 * max(abs(cur[1]), 1):
                out.append(f"{name}보고서 누적 {cur[1]:,} ≠ 앞 보고서 누적+3개월 {expect:,}")
    return "; ".join(out)


def main() -> int:
    cfg = load_config()
    need = ["financials.csv", "quarterly.csv", "metrics.csv", "audit_ledger.csv", "source_registry.csv", "research_status.csv", "summary.json"]
    missing = [n for n in need if not (DATA / n).exists()]
    check("필수 데이터 파일", not missing, "없음: " + ", ".join(missing) if missing else f"{len(need)}개")
    if missing:
        return finish()

    fin = read_csv(DATA / "financials.csv")
    F = defaultdict(dict)
    for r in fin:
        F[int(r["year"])][r["metric"]] = num(r["value"])
    years = sorted(F)
    check("연간 재무 연도 수", len(years) >= 2, f"{years}")

    # 1) 재무상태표 항등식: 자산 = 부채 + 자본
    for y in years:
        a, l, e = F[y].get("total_assets"), F[y].get("total_liabilities"), F[y].get("total_equity")
        if None in (a, l, e):
            add("미실행", f"{y} 자산 = 부채 + 자본", "계정 일부 없음")
        else:
            check(f"{y} 자산 = 부채 + 자본", a == l + e, f"차이 {a - (l + e):,}원")

    # 2) 매출 − 원가 − 판관비 ≈ 영업이익 (기타영업손익이 있는 회사는 다를 수 있어 경고만)
    for y in years:
        r, c, s, o = (F[y].get(k) for k in ("revenue", "cost_of_sales", "sga", "operating_profit"))
        if None in (r, c, s, o):
            add("미실행", f"{y} 매출−원가−판관비 = 영업이익", "계정 일부 없음 (업종 특성일 수 있음)")
        else:
            d = r - c - s - o
            check(f"{y} 매출−원가−판관비 = 영업이익", d == 0, f"차이 {d:,}원 (기타영업손익 계정이 있는지 원문 확인)", warn_only=True)

    # 3) 분기 4개 합 = 연간 (Q1~Q3 3개월 값과 3분기 누적이 서로 맞는지 확인하는 효과)
    q = defaultdict(dict)
    for r in read_csv(DATA / "quarterly.csv"):
        q[(int(r["year"]), r["metric"])][int(r["quarter"])] = num(r["value"])
    for (y, m), qs in sorted(q.items()):
        if len(qs) == 4 and F.get(y, {}).get(m) is not None and None not in qs.values():
            s, a = sum(qs.values()), F[y][m]
            if s == a:
                check(f"{y} {m} 분기 합 = 연간", True)
            elif abs(s - a) <= 0.005 * abs(a):  # 0.5% 이내: 후속 보고서의 재분류·정정 가능성 → 사람 확인
                check(f"{y} {m} 분기 합 = 연간", False, f"차이 {s - a:,}원 — 이후 보고서에서 분기값이 재분류·정정됐을 수 있음. 원문 비교열 확인", warn_only=True)
            else:
                ev = restated_evidence(y, m)
                if ev:  # 같은 해 뒤 보고서가 앞 분기를 다시 계산(중단영업 재분류 등) — 공시 원문끼리 기준이 달라 생긴 차이
                    check(f"{y} {m} 분기 합 = 연간", False, f"분기합 {s:,} / 연간 {a:,} — 보고서 간 재작성 감지: {ev}. "
                          "각 값은 원문과 같으나 기준이 섞임(분기 화면 해석 주의)", warn_only=True)
                else:
                    check(f"{y} {m} 분기 합 = 연간", False, f"분기합 {s:,} / 연간 {a:,}")

    # 4) 재무비율 재계산
    recompute = {
        "operating_margin_pct": lambda f: 100 * f["operating_profit"] / f["revenue"],
        "debt_ratio_pct": lambda f: 100 * f["total_liabilities"] / f["total_equity"],
        "current_ratio_pct": lambda f: 100 * f["current_assets"] / f["current_liabilities"],
    }
    for r in read_csv(DATA / "metrics.csv"):
        fn = recompute.get(r["metric"])
        if fn and r["value"] != "":
            try:
                want = fn(F[int(r["year"])])
                check(f"{r['year']} {r['label']} 재계산", close(float(r["value"]), want, 1e-4), f"CSV {float(r['value']):.4f} / 재계산 {want:.4f}")
            except (TypeError, ZeroDivisionError, KeyError):
                add("미실행", f"{r['year']} {r['label']} 재계산", "입력 계정 없음")

    # 5) 출처 연결: 모든 값 → 검증장부 → 출처 등록부
    ledger = {r["audit_id"]: r for r in read_csv(DATA / "audit_ledger.csv")}
    reg = {r["source_id"] for r in read_csv(DATA / "source_registry.csv")}
    no_audit = [r["audit_id"] for r in fin if r["value"] != "" and r["audit_id"] not in ledger]
    check("모든 재무 값에 검증번호", not no_audit, ", ".join(no_audit[:5]))
    no_src = [a for a, r in ledger.items() if r["value"] != "" and r["source_id"] and r["source_id"] not in reg]
    check("검증장부 출처가 등록부에 있음", not no_src, ", ".join(no_src[:5]))
    bad = [a for a, r in ledger.items() if r["result"] == ST_MISMATCH]
    check("사람 대조값과 불일치 없음", not bad, "; ".join(f"{a}: {ledger[a]['note']}" for a in bad[:5]))

    # 6) 산업 KPI: 출처 없는 숫자 금지
    allowed = {ST_VERIFIED, ST_AUTO, ST_UNCONFIRMED, ST_UNDISCLOSED}
    kpis = read_csv(DATA / "manual" / "kpi_values.csv")
    nosrc = [f"{r['kpi_key']} {r['year']}" for r in kpis if r.get("value") not in ("", None) and not r.get("source_url")]
    check("산업 KPI 값마다 출처 URL", not nosrc, ", ".join(nosrc[:5]) or f"{len(kpis)}행")
    badst = [f"{r['kpi_key']} {r['year']}: {r.get('status')}" for r in kpis if r.get("status") not in allowed]
    check("산업 KPI 상태값 형식", not badst, ", ".join(badst[:5]) + (" (허용: " + " / ".join(sorted(allowed)) + ")" if badst else ""))
    estimated = [f"{r['kpi_key']} {r['year']}" for r in kpis if r.get("status") in (ST_UNCONFIRMED, ST_UNDISCLOSED) and r.get("value") not in ("", None)]
    check("미확인·미공개 항목에 숫자 없음 (추정값 금지)", not estimated, ", ".join(estimated[:5]))

    # 6-1) 합계 검산: 연결 기준 구성 매출(부문·지역·판매경로)의 합 = 연결 매출액 (원문 숫자끼리 맞는지)
    groups = defaultdict(list)
    for r in kpis:
        if r.get("unit") == "KRW" and "연결" in (r.get("scope") or "") and r.get("value") not in ("", None) and r.get("kpi_key") in ("product_segment_revenue", "export_revenue", "sales_channels", "segment_revenue", "region_revenue"):
            groups[(r["kpi_key"], int(r["year"]))].append(num(r["value"]))
    for (k, y), vals in sorted(groups.items()):
        rev = F.get(y, {}).get("revenue")
        if rev is None:
            continue
        s = sum(vals)
        diff = abs(s - rev) / rev
        check(f"{y} {k} 합계 = 연결 매출액", diff <= 0.001, f"합계 {s:,} / 매출 {rev:,} (차이 {diff:.3%}, 원문 단위 반올림은 0.1% 이내 허용)", warn_only=True)

    # 7) 이미 사람이 원문 대조한 기준값과 비교 (verify_expectations.json, 같은 기업일 때만)
    ep = CDIR / "verify_expectations.json"
    if ep.exists():
        exp = json.loads(ep.read_text(encoding="utf-8"))
        if exp.get("company_id") == cfg["company_id"]:
            n_ok = 0
            for c in exp.get("checks", []):
                got = F.get(c["year"], {}).get(c["metric"])
                if got is None:
                    add("미실행", f"기준값 {c['year']} {c['metric']}", "자동 수집값 없음")
                elif got == c["value"]:
                    n_ok += 1
                else:
                    add("실패", f"기준값 {c['year']} {c['metric']}", f"자동 {got:,} / 기준 {c['value']:,} ({c.get('evidence', '')})")
            add("통과" if n_ok else "미실행", "사람이 대조한 기준값과 일치", f"{n_ok}/{len(exp.get('checks', []))}개")
        else:
            add("미실행", "사람이 대조한 기준값과 비교", f"기준 파일은 {exp.get('company_id')}용")
    return finish()


def finish() -> int:
    order = {"실패": 0, "경고": 1, "미실행": 2, "통과": 3}
    cnt = defaultdict(int)
    for r in results:
        cnt[r["state"]] += 1
    (DATA / "verify_report.json").write_text(json.dumps({"checked_at": now_kst(), "counts": cnt, "results": sorted(results, key=lambda r: order[r["state"]])},
                                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for r in sorted(results, key=lambda r: order[r["state"]]):
        print(f"[{r['state']}] {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))
    print(f"\n통과 {cnt['통과']} · 실패 {cnt['실패']} · 경고 {cnt['경고']} · 미실행 {cnt['미실행']}")
    return 1 if cnt["실패"] else 0


if __name__ == "__main__":
    sys.exit(main())
