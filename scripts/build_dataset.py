#!/usr/bin/env python3
"""
2단계 · 화면용 데이터 만들기 → data/*.csv, data/summary.json

    python scripts/build_dataset.py

입력
  data/raw/dart_financials.csv     collect_dart.py가 받은 보고서별 계정 값
  data/raw/dart_reports.csv        보고서 목록 (출처 등록부의 원천)
  data/manual/audit_overrides.csv  사람이 공시 원문과 대조한 기록 (다시 빌드해도 유지)
  data/manual/kpi_values.csv       산업별 KPI (제품군 매출·수출·NIM 등) — 출처 필수
  industries/<industry>.json       산업별로 확인해야 할 KPI 목록

출력
  financials.csv     연간 재무 (계정 1개 = 1행, 검증번호 audit_id 포함)
  quarterly.csv      분기 단일 실적 (Q4 = 사업보고서 연간 − 3분기 누적)
  metrics.csv        재무비율 (산식·입력값·기준 함께 저장)
  source_registry.csv / audit_ledger.csv / research_status.csv
  summary.json       3D 포털이 읽을 요약 (기업·산업·카테고리·핵심 KPI·검증 현황)

이 스크립트는 '계산'만 합니다. 값을 새로 지어내지 않으며, 입력이 없으면 빈칸으로 둡니다.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

from ubda_common import (DATA, RAW, ROOT, ST_AUTO, ST_MISMATCH, ST_UNCONFIRMED, ST_UNDISCLOSED, ST_VERIFIED,
                         load_config, now_kst, num, read_csv, write_csv)

MANUAL = DATA / "manual"
FLOW = ["revenue", "cost_of_sales", "sga", "operating_profit", "net_income"]
EXPENSE_ABS = {"interest_expense", "general_admin", "credit_loss"}  # 은행 비용 계정: 회사·보고서마다 부호가 달라 금액(절댓값)으로 통일
BANK_FLOW = ["interest_income", "interest_expense", "net_interest_income", "net_fee_income", "general_admin", "credit_loss", "net_income_owners"]
STATUS_RANK = {ST_VERIFIED: 4, ST_AUTO: 3, ST_UNDISCLOSED: 2, ST_UNCONFIRMED: 1, ST_MISMATCH: 0}
KPI_COLS = ["kpi_key", "year", "period", "item", "value", "unit", "scope", "source_url", "source_location", "status", "checked_on", "note"]
OVR_COLS = ["audit_id", "result", "verified_value", "source_location", "checked_on", "checked_by", "note"]


def safe_div(a, b):
    return None if a is None or b in (None, 0) else a / b


def avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def growth(cur, prev):
    if cur is None or prev is None or prev <= 0:  # 전년 적자·0이면 증가율 의미 없음 → 비교 불가
        return None
    return (cur / prev - 1) * 100


def main() -> int:
    cfg = load_config()
    cid, cname = cfg["company_id"], cfg["name"]
    ind_path = ROOT / "industries" / f"{cfg['industry']}.json"
    industry = json.loads(ind_path.read_text(encoding="utf-8")) if ind_path.exists() else {"id": cfg["industry"], "name": cfg["industry"], "kpis": []}

    min_year = int(cfg.get("start_year", 0)) - 1  # 전년 대비 계산용 1년 포함, 그 이전(옛 보고서 기재정정 등)은 제외
    raw = [r for r in read_csv(RAW / "dart_financials.csv") if int(r["bsns_year"]) >= min_year
           # 예전 수집분에 '영업비용'(성격별 표시 회사의 영업비용 합계)이 매출원가로 들어간 경우 제외 — 매출원가가 아님
           and not (r["metric"] == "cost_of_sales" and r.get("account_nm", "").strip() == "영업비용")]
    reports = [r for r in read_csv(RAW / "dart_reports.csv") if int(r["bsns_year"]) >= min_year]
    MANUAL.mkdir(parents=True, exist_ok=True)
    if not (MANUAL / "kpi_values.csv").exists():
        write_csv(MANUAL / "kpi_values.csv", KPI_COLS, [])
    if not (MANUAL / "audit_overrides.csv").exists():
        write_csv(MANUAL / "audit_overrides.csv", OVR_COLS, [])
    overrides = {r["audit_id"]: r for r in read_csv(MANUAL / "audit_overrides.csv")}
    kpi_rows = read_csv(MANUAL / "kpi_values.csv")

    by = {(r["bsns_year"], r["reprt_code"], r["metric"]): r for r in raw}
    ledger: list[dict] = []

    def audit(aid: str, dataset: str, value, r: dict | None, location: str, method: str) -> str:
        """검증 장부 1행. 사람 대조 기록(overrides)이 있으면 그 결과를 우선한다."""
        result = ST_AUTO if r and value not in ("", None) else ST_UNCONFIRMED
        o = overrides.get(aid)
        note = ""
        if o and o.get("result"):
            vv = num(o.get("verified_value"))
            if vv is not None and value not in ("", None) and int(value) != vv:
                result, note = ST_MISMATCH, f"사람 대조값 {vv:,} ≠ 현재값 {int(value):,} (정정공시 여부 확인)"
            else:
                result = o["result"]
            location = o.get("source_location") or location
        ledger.append({"audit_id": aid, "dataset": dataset, "value": value, "source_id": r["rcept_no"] if r else "", "source_location": location,
                       "method": method, "result": result, "checked_on": (o or {}).get("checked_on", "") if o else (r or {}).get("fetched_at", ""),
                       "checked_by": (o or {}).get("checked_by", "") if o else "자동(OpenDART API)", "note": note or (o or {}).get("note", "")})
        return result

    # ---------- 연간 재무
    years = sorted({int(r["bsns_year"]) for r in raw if r["reprt_code"] == "11011"})
    fin_rows, F = [], defaultdict(dict)
    labels = {r["metric"]: r["label"] for r in raw}
    metrics_order = list(dict.fromkeys(r["metric"] for r in raw))
    for y in years:
        for m in metrics_order:
            r = by.get((str(y), "11011", m))
            v = num(r["value"]) if r else None
            if m == "capex" and v is not None:
                v = abs(v)  # 회사마다 음수(유출)·양수로 표기가 달라 '지출 금액'으로 통일
            if m in EXPENSE_ABS and v is not None:
                v = abs(v)  # 은행 비용 계정도 회사마다 부호가 달라(BNK·JB는 음수) '비용 금액'으로 통일
            aid = f"F-{y}-{m}"
            loc = f"{r['report_nm']} · {r['fs_div']} · {r['sj_div']} · {r['account_nm']}" if r and r["account_nm"] else "계정 미발견"
            st = audit(aid, "financials.csv", "" if v is None else v, r if v is not None else None, loc, "OpenDART fnlttSinglAcntAll 값 그대로")
            F[y][m] = v
            fin_rows.append({"company_id": cid, "year": y, "metric": m, "label": labels.get(m, m) + (" (지출액)" if m == "capex" else ""), "value": "" if v is None else v, "unit": "KRW",
                             "scope": {"CFS": "연결", "OFS": "별도"}.get(r["fs_div"], "") if r else "", "source_id": r["rcept_no"] if r else "",
                             "source_url": r["viewer_url"] if r else "", "account_nm": r["account_nm"] if r else "", "audit_id": aid, "status": st})

    # 은행: 순이자이익 줄이 없는 회사(카카오뱅크 등)는 이자수익 − 이자비용으로 계산해 넣고 계산값임을 표시
    if cfg.get("industry") == "bank":
        for y in years:
            ii, ie = F[y].get("interest_income"), F[y].get("interest_expense")
            if F[y].get("net_interest_income") is None and ii is not None and ie is not None:
                v = ii - abs(ie)
                aid = f"F-{y}-net_interest_income"
                ledger[:] = [x for x in ledger if x["audit_id"] != aid]
                r = by.get((str(y), "11011", "interest_income"))
                st = audit(aid, "financials.csv", v, r, "계산: 이자수익 − 이자비용 (손익계산서에 순이자이익 줄 없음)", "이자수익 − 이자비용(금액)")
                F[y]["net_interest_income"] = v
                for row in fin_rows:
                    if row["year"] == y and row["metric"] == "net_interest_income":
                        row.update(value=v, label="순이자이익 (계산: 이자수익−이자비용)", account_nm="계산", status=st)

    # ---------- 분기 단일 실적
    q_rows = []
    for y in sorted({int(r["bsns_year"]) for r in raw}):
        for m in FLOW + (BANK_FLOW if cfg.get("industry") == "bank" else []):
            for q, code, method in ((1, "11013", "1분기보고서 3개월"), (2, "11012", "반기보고서 3개월"), (3, "11014", "3분기보고서 3개월")):
                r = by.get((str(y), code, m))
                v = num(r["value"]) if r else None
                if v is None:
                    continue
                if m in EXPENSE_ABS:
                    v = abs(v)
                aid = f"Q-{y}Q{q}-{m}"
                st = audit(aid, "quarterly.csv", v, r, f"{r['report_nm']} · {r['account_nm']} 3개월", method)
                q_rows.append({"year": y, "quarter": q, "period": f"{y}-Q{q}", "metric": m, "label": labels.get(m, m), "value": v, "method": method,
                               "source_ids": r["rcept_no"], "audit_id": aid, "status": st})
            a, c3 = by.get((str(y), "11011", m)), by.get((str(y), "11014", m))
            av, cv = (num(a["value"]) if a else None), (num(c3["value_cumulative"]) if c3 else None)
            if m in EXPENSE_ABS:  # 보고서마다 부호가 달라도 금액 기준으로 맞춘 뒤 Q4 계산
                av, cv = (None if av is None else abs(av)), (None if cv is None else abs(cv))
            if av is not None and cv is not None:
                aid = f"Q-{y}Q4-{m}"
                st = audit(aid, "quarterly.csv", av - cv, a, f"{a['report_nm']} 연간 − {c3['report_nm']} 누적", "연간 − 3분기 누적 (결산조정 포함)")
                q_rows.append({"year": y, "quarter": 4, "period": f"{y}-Q4", "metric": m, "label": labels.get(m, m), "value": av - cv,
                               "method": "연간 − 3분기 누적 (결산조정 포함)", "source_ids": f"{a['rcept_no']};{c3['rcept_no']}", "audit_id": aid, "status": st})
    q_rows.sort(key=lambda r: (r["year"], r["quarter"], r["metric"]))

    # ---------- 재무비율 (산식은 화면에도 그대로 표시)
    DEFS = [
        ("operating_margin_pct", "영업이익률", "%", "영업이익 ÷ 매출액 × 100", lambda c, p: safe_div(c.get("operating_profit"), c.get("revenue")), ["operating_profit", "revenue"]),
        ("net_margin_pct", "순이익률", "%", "당기순이익 ÷ 매출액 × 100", lambda c, p: safe_div(c.get("net_income"), c.get("revenue")), ["net_income", "revenue"]),
        ("cost_ratio_pct", "매출원가율", "%", "매출원가 ÷ 매출액 × 100", lambda c, p: safe_div(c.get("cost_of_sales"), c.get("revenue")), ["cost_of_sales", "revenue"]),
        ("sga_ratio_pct", "판관비율", "%", "판매비와관리비 ÷ 매출액 × 100", lambda c, p: safe_div(c.get("sga"), c.get("revenue")), ["sga", "revenue"]),
        ("revenue_growth_pct", "매출 증가율", "%", "(당기 매출 ÷ 전기 매출 − 1) × 100", None, ["revenue"]),
        ("op_growth_pct", "영업이익 증가율", "%", "(당기 영업이익 ÷ 전기 영업이익 − 1) × 100 · 전기 적자면 비교 불가", None, ["operating_profit"]),
        ("debt_ratio_pct", "부채비율", "%", "부채총계 ÷ 자본총계 × 100", lambda c, p: safe_div(c.get("total_liabilities"), c.get("total_equity")), ["total_liabilities", "total_equity"]),
        ("current_ratio_pct", "유동비율", "%", "유동자산 ÷ 유동부채 × 100", lambda c, p: safe_div(c.get("current_assets"), c.get("current_liabilities")), ["current_assets", "current_liabilities"]),
        ("equity_ratio_pct", "자기자본비율", "%", "자본총계 ÷ 자산총계 × 100", lambda c, p: safe_div(c.get("total_equity"), c.get("total_assets")), ["total_equity", "total_assets"]),
        ("roe_pct", "ROE", "%", "당기순이익 ÷ 평균 자본총계 × 100 (평균 = (기초+기말)÷2)", lambda c, p: safe_div(c.get("net_income"), avg(c.get("total_equity"), p.get("total_equity"))), ["net_income", "total_equity"]),
        ("roa_pct", "ROA", "%", "당기순이익 ÷ 평균 자산총계 × 100", lambda c, p: safe_div(c.get("net_income"), avg(c.get("total_assets"), p.get("total_assets"))), ["net_income", "total_assets"]),
        ("asset_turnover", "총자산회전율", "회", "매출액 ÷ 평균 자산총계", lambda c, p: safe_div(c.get("revenue"), avg(c.get("total_assets"), p.get("total_assets"))), ["revenue", "total_assets"]),
        ("inventory_turnover", "재고자산회전율", "회", "매출원가 ÷ 평균 재고자산", lambda c, p: safe_div(c.get("cost_of_sales"), avg(c.get("inventories"), p.get("inventories"))), ["cost_of_sales", "inventories"]),
        ("capex_to_revenue_pct", "설비투자 비중", "%", "유형자산 취득액 ÷ 매출액 × 100", lambda c, p: safe_div(c.get("capex"), c.get("revenue")), ["capex", "revenue"]),
        ("simple_fcf", "단순 잉여현금흐름", "KRW", "영업활동현금흐름 − 유형자산 취득액", lambda c, p: None if c.get("operating_cashflow") is None or c.get("capex") is None else c["operating_cashflow"] - c["capex"], ["operating_cashflow", "capex"]),
    ]
    if cfg.get("industry") == "bank":  # 은행: 매출 기반 비율 대신 은행 지표 (비용 계정은 회사마다 부호가 달라 금액(절댓값)으로 통일)
        ex = lambda v: None if v is None else abs(v)  # noqa: E731
        toi = lambda c: None if None in (c.get("operating_profit"), c.get("general_admin"), c.get("credit_loss")) else c["operating_profit"] + ex(c["general_admin"]) + ex(c["credit_loss"])  # noqa: E731
        bank_only = {"debt_ratio_pct", "equity_ratio_pct", "roe_pct", "roa_pct", "op_growth_pct"}
        DEFS = [d for d in DEFS if d[0] in bank_only] + [
            ("total_operating_income", "총영업이익(계산)", "KRW", "영업이익 + 일반관리비 + 신용손실충당금전입액 (충당금 적립 전·경비 차감 전 이익, 비용은 금액 기준)", lambda c, p: toi(c), ["operating_profit", "general_admin", "credit_loss"]),
            ("nii_share_pct", "순이자이익 비중", "%", "순이자이익 ÷ 총영업이익(계산) × 100", lambda c, p: safe_div(c.get("net_interest_income"), toi(c)), ["net_interest_income", "operating_profit", "general_admin", "credit_loss"]),
            ("cir_pct", "영업이익경비율(CIR, 계산)", "%", "일반관리비 ÷ 총영업이익(계산) × 100 · 회사 공시 CIR과 산식이 다를 수 있음", lambda c, p: safe_div(ex(c.get("general_admin")), toi(c)), ["general_admin", "operating_profit", "credit_loss"]),
            ("credit_cost_pct", "대손비용률(계산)", "%", "신용손실충당금전입액 ÷ 평균 대출채권 × 100 (평균 = (기초+기말)÷2)", lambda c, p: safe_div(ex(c.get("credit_loss")), avg(c.get("loans"), p.get("loans"))), ["credit_loss", "loans"]),
            ("nii_to_assets_pct", "순이자이익/평균총자산(NIM 대용)", "%", "순이자이익 ÷ 평균 자산총계 × 100 · 공시 NIM(이자수익자산 기준)이 아님", lambda c, p: safe_div(c.get("net_interest_income"), avg(c.get("total_assets"), p.get("total_assets"))), ["net_interest_income", "total_assets"]),
            ("loan_deposit_pct", "단순 예대율(계산)", "%", "대출채권 ÷ 예수부채 × 100 · 규제 예대율(원화예대율) 산식이 아님", lambda c, p: safe_div(c.get("loans"), c.get("deposits")), ["loans", "deposits"]),
            ("nii_growth_pct", "순이자이익 증가율", "%", "(당기 순이자이익 ÷ 전기 순이자이익 − 1) × 100", None, ["net_interest_income"]),
            ("ni_growth_pct", "순이익 증가율", "%", "(당기 순이익 ÷ 전기 순이익 − 1) × 100 · 전기 적자면 비교 불가", None, ["net_income"]),
        ]
    met_rows = []
    for y in years:
        cur, prev = F[y], F.get(y - 1, {})
        for key, label, unit, formula, fn, inputs in DEFS:
            if key == "revenue_growth_pct":
                v = growth(cur.get("revenue"), prev.get("revenue"))
            elif key == "op_growth_pct":
                v = growth(cur.get("operating_profit"), prev.get("operating_profit"))
            elif key == "nii_growth_pct":
                v = growth(cur.get("net_interest_income"), prev.get("net_interest_income"))
            elif key == "ni_growth_pct":
                v = growth(cur.get("net_income"), prev.get("net_income"))
            else:
                v = fn(cur, prev)
                if v is not None and unit == "%":
                    v *= 100
            uses_prev = key.endswith("growth_pct") or "평균" in formula
            basis = "전기 자료 없음 → 계산 불가" if v is None and uses_prev and not prev else ""
            ins = [f"F-{y}-{m}" for m in inputs] + ([f"F-{y-1}-{m}" for m in inputs] if uses_prev else [])
            met_rows.append({"year": y, "metric": key, "label": label, "value": "" if v is None else round(v, 4) if unit != "KRW" else round(v),
                             "unit": unit, "formula": formula, "input_audit_ids": ";".join(ins), "note": basis})

    # ---------- 출처 등록부
    registry = [{"source_id": r["rcept_no"], "title": f"{cname} {r['report_nm']}", "source_url": r["viewer_url"], "source_date": r["rcept_dt"],
                 "type": "DART 정기보고서", "status": r.get("status", ""), "note": r.get("message", "")} for r in reports]
    for k in kpi_rows:
        if k.get("source_url") and not any(x["source_url"] == k["source_url"] for x in registry):
            registry.append({"source_id": f"K{len(registry)+1:03d}", "title": k.get("source_location") or k["source_url"], "source_url": k["source_url"],
                             "source_date": "", "type": "산업 KPI 출처", "status": "", "note": k.get("kpi_key", "")})

    # ---------- 산업 KPI 확보 현황 (없으면 '미확인'으로 남김 — 임의 생성 금지)
    status_rows = []
    fin_auto = sum(1 for r in fin_rows if r["status"] == ST_AUTO)
    fin_ok = sum(1 for r in fin_rows if r["status"] == ST_VERIFIED)
    fin_bad = sum(1 for r in fin_rows if r["status"] == ST_MISMATCH)
    fin_na = sum(1 for r in fin_rows if r["status"] == ST_UNCONFIRMED)
    status_rows.append({"group": "공통 재무", "key": "annual_financials", "label": "연간 재무제표 (DART)", "status": ST_VERIFIED if fin_rows and fin_ok == len(fin_rows) else (ST_AUTO if fin_rows else ST_UNCONFIRMED),
                        "result": f"{len(years)}개 연도 · 원문 대조 {fin_ok} · 자동 {fin_auto} · 불일치 {fin_bad} · 계정 없음 {fin_na}",
                        "where": "OpenDART 단일회사 전체 재무제표 API", "caution": "자동값은 사업보고서 원문 대조 전입니다. 대조 결과는 data/manual/audit_overrides.csv에 기록"})
    status_rows.append({"group": "공통 재무", "key": "quarterly", "label": "분기 단일 실적", "status": ST_AUTO if q_rows else ST_UNCONFIRMED,
                        "result": f"{len({r['period'] for r in q_rows})}개 분기", "where": "1분기·반기·3분기·사업보고서", "caution": "Q4는 연간 − 3분기 누적이라 결산조정이 섞입니다"})
    for k in industry.get("kpis", []):
        rows = [r for r in kpi_rows if r.get("kpi_key") == k["key"]]
        best = max((r.get("status") or ST_UNCONFIRMED for r in rows), key=lambda s: STATUS_RANK.get(s, 1), default=ST_UNCONFIRMED)
        yrs = sorted({r.get("year") for r in rows if r.get("year")})
        status_rows.append({"group": industry.get("name", ""), "key": k["key"], "label": k["label"], "status": best,
                            "result": f"{len(rows)}행 · {', '.join(yrs)}" if rows else "아직 수집 안 함", "where": k.get("where", ""), "caution": k.get("caution", "")})

    # ---------- 쓰기
    write_csv(DATA / "financials.csv", ["company_id", "year", "metric", "label", "value", "unit", "scope", "source_id", "source_url", "account_nm", "audit_id", "status"], fin_rows)
    write_csv(DATA / "quarterly.csv", ["year", "quarter", "period", "metric", "label", "value", "method", "source_ids", "audit_id", "status"], q_rows)
    write_csv(DATA / "metrics.csv", ["year", "metric", "label", "value", "unit", "formula", "input_audit_ids", "note"], met_rows)
    write_csv(DATA / "source_registry.csv", ["source_id", "title", "source_url", "source_date", "type", "status", "note"], registry)
    write_csv(DATA / "audit_ledger.csv", ["audit_id", "dataset", "value", "source_id", "source_location", "method", "result", "checked_on", "checked_by", "note"], ledger)
    write_csv(DATA / "research_status.csv", ["group", "key", "label", "status", "result", "where", "caution"], status_rows)

    ly = years[-1] if years else None
    pick = lambda k: next((r["value"] for r in met_rows if r["year"] == ly and r["metric"] == k), "")  # noqa: E731
    summary = {
        "slug": cfg["slug"], "company_id": cid, "name": cname, "dashboard_path": f"dashboard.html?c={cfg['slug']}", "name_en": cfg.get("name_en", ""), "stock_code": cfg.get("stock_code", ""),
        "industry": industry.get("id", cfg["industry"]), "industry_name": industry.get("name", ""), "categories": cfg.get("categories", []),
        "competitors": cfg.get("competitors", []), "dashboard_url": cfg.get("dashboard_url", ""), "latest_year": ly,
        "kpis": None if ly is None else {"revenue": F[ly].get("revenue"), "operating_profit": F[ly].get("operating_profit"), "net_income": F[ly].get("net_income"),
                                          "operating_margin_pct": pick("operating_margin_pct"), "revenue_growth_pct": pick("revenue_growth_pct"), "debt_ratio_pct": pick("debt_ratio_pct")},
        "verification": {s: sum(1 for r in ledger if r["result"] == s) for s in (ST_VERIFIED, ST_AUTO, ST_MISMATCH, ST_UNCONFIRMED)},
        "industry_kpis_found": sum(1 for r in status_rows[2:] if r["status"] in (ST_VERIFIED, ST_AUTO)), "industry_kpis_total": len(status_rows) - 2,
        "updated_at": now_kst(),
    }
    (DATA / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"연간 {len(years)}개 연도({years[0] if years else '-'}~{ly or '-'}) · 분기 {len({r['period'] for r in q_rows})}개 · 비율 {len(met_rows)}행 · 검증장부 {len(ledger)}행 · 출처 {len(registry)}건")
    if not years:
        print("[안내] 연간 데이터가 없습니다. collect_dart.py가 먼저 실행되어야 합니다 (DART_API_KEY 확인).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
