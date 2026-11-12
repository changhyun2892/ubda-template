#!/usr/bin/env python3
"""
1단계 · DART 정기보고서 수집 → data/raw/

    DART_API_KEY=발급키 python scripts/collect_dart.py --company <기업폴더>
    (Windows: set DART_API_KEY=발급키  →  py scripts\\collect_dart.py --company ottogi)

기존 불닭 대시보드의 update_dart.py를 기업 무관하게 바꾼 것입니다.
 1. company.json의 stock_code로 DART 고유번호(corp_code)를 찾는다 (처음 한 번, data/raw/dart_meta.json에 저장).
 2. start_year 1월 1일 이후 정기공시(사업·반기·분기보고서) 목록을 받아 아직 반영하지 않은 보고서를 찾는다.
    정정보고서가 새로 올라오면 그 기간을 다시 받아 덮어쓴다.
 3. 보고서마다 '단일회사 전체 재무제표' API에서 핵심 계정을 뽑는다.
    fs_div가 auto면 연결(CFS)을 먼저 보고, 연결재무제표가 없는 회사면 별도(OFS)를 쓴다 (어느 쪽인지 기록).

원칙
 - 값이 없으면 빈칸(=데이터 없음). 0이나 추정값으로 채우지 않는다.
 - 키가 없거나 요청이 실패하면 기존 파일을 그대로 두고 경고만 남긴다 (사이트가 깨지지 않게).
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime

from ubda_common import (KST, RAW, ST_AUTO, DartError, dart_get, load_config, now_kst, num,
                         read_csv, write_csv, write_log)

META = RAW / "dart_meta.json"
REPORTS = RAW / "dart_reports.csv"
FINS = RAW / "dart_financials.csv"

# 보고서 결산월 → (reprt_code, 이름)
REPRT = {"12": ("11011", "사업보고서"), "06": ("11012", "반기보고서"), "03": ("11013", "1분기보고서"), "09": ("11014", "3분기보고서")}
ORDER = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}

# 뽑을 계정: (metric, 화면 이름, 재무제표 구분, account_id 후보, 계정명 정규식(공백 제거 후 비교))
# 업종 공통 계정만 둡니다. 은행·보험처럼 손익 구조가 다른 업종은 industries/*.json의 extra_accounts로 추가합니다.
ACCOUNTS = [
    ("revenue", "매출액", ("IS", "CIS"), ("ifrs-full_Revenue", "ifrs_Revenue"), r"^(매출액|수익\(매출액\)|영업수익|매출)$"),
    ("cost_of_sales", "매출원가", ("IS", "CIS"), ("ifrs-full_CostOfSales", "ifrs_CostOfSales"), r"^(매출원가|영업비용)$"),
    ("sga", "판매비와관리비", ("IS", "CIS"), ("dart_TotalSellingGeneralAdministrativeExpenses",), r"^판매비와관리비$"),
    ("operating_profit", "영업이익", ("IS", "CIS"), ("dart_OperatingIncomeLoss",), r"^영업이익(\(손실\))?$"),
    ("net_income", "당기순이익", ("IS", "CIS"), ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"), r"^(당기|분기|반기)순이익(\(손실\))?$"),
    ("total_assets", "자산총계", ("BS",), ("ifrs-full_Assets", "ifrs_Assets"), r"^자산총계$"),
    ("current_assets", "유동자산", ("BS",), ("ifrs-full_CurrentAssets", "ifrs_CurrentAssets"), r"^유동자산$"),
    ("inventories", "재고자산", ("BS",), ("ifrs-full_Inventories", "ifrs_Inventories"), r"^재고자산$"),
    ("cash", "현금및현금성자산", ("BS",), ("ifrs-full_CashAndCashEquivalents", "ifrs_CashAndCashEquivalents"), r"^현금및현금성자산$"),
    ("total_liabilities", "부채총계", ("BS",), ("ifrs-full_Liabilities", "ifrs_Liabilities"), r"^부채총계$"),
    ("current_liabilities", "유동부채", ("BS",), ("ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"), r"^유동부채$"),
    ("total_equity", "자본총계", ("BS",), ("ifrs-full_Equity", "ifrs_Equity"), r"^자본총계$"),
    ("operating_cashflow", "영업활동현금흐름", ("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"), r"^영업활동(으로인한)?현금흐름$"),
    ("capex", "유형자산의 취득", ("CF",), ("ifrs-full_PurchaseOfPropertyPlantAndEquipment", "ifrs_PurchaseOfPropertyPlantAndEquipment"), r"^유형자산의?취득$"),
]
FLOW = {"revenue", "cost_of_sales", "sga", "operating_profit", "net_income"}  # 기간 손익 (분기 단일값 계산 대상)

REPORT_COLS = ["rcept_no", "rcept_dt", "report_nm", "bsns_year", "reprt_code", "report_type", "is_correction", "status", "message", "processed_at", "viewer_url"]
FIN_COLS = ["bsns_year", "reprt_code", "report_type", "metric", "label", "value", "value_cumulative", "unit", "fs_div", "sj_div",
            "account_id", "account_nm", "rcept_no", "rcept_dt", "report_nm", "viewer_url", "fetched_at", "status"]


def viewer(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def corp_code(key: str, stock_code: str) -> str:
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    if meta.get("stock_code") == stock_code and meta.get("corp_code"):
        return meta["corp_code"]
    body = dart_get("corpCode.xml", {"crtfc_key": key}, raw=True)
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:  # 키 오류 등은 압축파일 대신 JSON/XML 오류문이 온다
        txt = body[:300].decode("utf-8", "replace")
        m = re.search(r'"message"\s*:\s*"([^"]+)"|<message>([^<]+)</message>', txt)
        raise DartError(f"DART corpCode 오류: {(m.group(1) or m.group(2)) if m else txt[:100]}") from None
    root = ET.fromstring(z.read(z.namelist()[0]))
    for el in root.iter("list"):
        if (el.findtext("stock_code") or "").strip() == stock_code:
            cc = el.findtext("corp_code").strip()
            RAW.mkdir(parents=True, exist_ok=True)
            META.write_text(json.dumps({"stock_code": stock_code, "corp_name": (el.findtext("corp_name") or "").strip(), "corp_code": cc,
                                        "found_at": now_kst()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return cc
    raise DartError(f"종목코드 {stock_code}의 corp_code를 찾지 못했습니다 (상장사가 맞는지, 종목코드 6자리가 맞는지 확인)")


def list_reports(key: str, cc: str, start_year: int) -> list[dict]:
    out, page = [], 1
    end_de = datetime.now(KST).strftime("%Y%m%d")
    while True:
        js = dart_get("list.json", {"crtfc_key": key, "corp_code": cc, "bgn_de": f"{start_year}0101", "end_de": end_de,
                                    "pblntf_ty": "A", "page_no": page, "page_count": 100})
        out += js.get("list", [])
        if page >= int(js.get("total_page", 1) or 1):
            break
        page += 1
    reps = []
    for r in out:
        nm = (r.get("report_nm") or "").strip()
        m = re.search(r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)", nm)
        if not m or m.group(3) not in REPRT:
            continue
        code, rtype = REPRT[m.group(3)]
        reps.append({"rcept_no": r["rcept_no"], "rcept_dt": r.get("rcept_dt", ""), "report_nm": nm, "bsns_year": m.group(2), "reprt_code": code,
                     "report_type": rtype, "is_correction": "Y" if nm.startswith("[") else "N", "viewer_url": viewer(r["rcept_no"])})
    reps.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
    return reps


def pick(items: list[dict], sj: tuple, ids: tuple, name_re: str) -> dict | None:
    cand = [i for i in items if i.get("sj_div") in sj]
    for aid in ids:
        for i in cand:
            if i.get("account_id") == aid:
                return i
    rx = re.compile(name_re)
    for i in cand:
        nm = re.sub(r"\s+", "", i.get("account_nm") or "")
        nm = re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\dIVX]+\.", "", nm)  # 'Ⅰ.매출액' 같은 번호 제거
        if rx.match(nm):
            return i
    return None


def fetch_items(key: str, cc: str, rep: dict, fs_pref: str) -> tuple[list[dict], str]:
    order = {"CFS": ["CFS"], "OFS": ["OFS"]}.get(fs_pref, ["CFS", "OFS"])  # auto: 연결 우선, 없으면 별도
    for fs in order:
        js = dart_get("fnlttSinglAcntAll.json", {"crtfc_key": key, "corp_code": cc, "bsns_year": rep["bsns_year"], "reprt_code": rep["reprt_code"], "fs_div": fs})
        if js.get("list"):
            return js["list"], fs
    return [], ""


def norm(nm: str) -> str:
    nm = re.sub(r"\s+", "", nm or "")
    return re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\dIVX]+\.", "", nm)


def pick_sga(items: list[dict], sj: tuple, ids: tuple, name_re: str) -> dict | None:
    """판매비와관리비. 합계 계정이 없고 '판매비'·'관리비'를 따로 적는 회사(예: 오리온)는 두 계정을 더한다."""
    it = pick(items, sj, ids, name_re)
    if it and re.match(r"^판매비(와|및)관리비$", norm(it.get("account_nm"))):
        return it
    cand = [i for i in items if i.get("sj_div") in sj]
    s = next((i for i in cand if norm(i.get("account_nm")) == "판매비"), None)
    a = next((i for i in cand if norm(i.get("account_nm")) == "관리비"), None)
    if s and a:
        add = lambda k: None if num(s.get(k)) is None or num(a.get(k)) is None else num(s.get(k)) + num(a.get(k))  # noqa: E731
        return {**s, "account_id": f"{s.get('account_id', '')}+{a.get('account_id', '')}", "account_nm": "판매비 + 관리비 (합산)",
                "thstrm_amount": add("thstrm_amount"), "thstrm_add_amount": add("thstrm_add_amount")}
    return it


def to_rows(items: list[dict], rep: dict, fs: str) -> list[dict]:
    rows, ts = [], now_kst()
    used = items[0].get("rcept_no") or rep["rcept_no"]
    for metric, label, sj, ids, name_re in ACCOUNTS:
        it = pick_sga(items, sj, ids, name_re) if metric == "sga" else pick(items, sj, ids, name_re)
        val = num(it.get("thstrm_amount")) if it else None
        cum = num(it.get("thstrm_add_amount")) if it else None
        if metric in FLOW and rep["reprt_code"] == "11011":
            cum = val  # 연간 = 누적
        if metric in FLOW and cum is None and rep["reprt_code"] == "11013":
            cum = val  # 1분기는 3개월 = 누적
        rows.append({"bsns_year": rep["bsns_year"], "reprt_code": rep["reprt_code"], "report_type": rep["report_type"], "metric": metric, "label": label,
                     "value": "" if val is None else val, "value_cumulative": "" if cum is None else cum, "unit": "KRW", "fs_div": fs,
                     "sj_div": it.get("sj_div", "") if it else "", "account_id": it.get("account_id", "") if it else "",
                     "account_nm": (it.get("account_nm") or "").strip() if it else "", "rcept_no": used, "rcept_dt": rep["rcept_dt"],
                     "report_nm": rep["report_nm"], "viewer_url": viewer(used), "fetched_at": ts, "status": ST_AUTO if it else "계정 미발견"})
    return rows


def save(fins: list[dict], done: dict) -> None:
    fins.sort(key=lambda r: (r["bsns_year"], ORDER.get(r["reprt_code"], 9), r["metric"]))
    write_csv(FINS, FIN_COLS, fins)
    write_csv(REPORTS, REPORT_COLS, sorted(done.values(), key=lambda r: (r["rcept_dt"], r["rcept_no"])))


def main() -> int:
    cfg = load_config()
    key = os.environ.get("DART_API_KEY", "").strip()
    started = now_kst()
    if not cfg.get("stock_code"):
        write_log("dart", {"status": "건너뜀", "checked_at": started, "message": "company.json에 stock_code 없음 (비상장 등)"})
        print("[안내] stock_code가 없어 DART 수집을 건너뜁니다.")
        return 0
    if not key:
        print("[경고] DART_API_KEY가 없습니다 — GitHub 저장소 Settings → Secrets and variables → Actions에 등록하세요. 기존 파일 유지.", file=sys.stderr)
        write_log("dart", {"status": "키 없음", "checked_at": started, "message": "DART_API_KEY 미설정"})
        return 0
    try:
        cc = corp_code(key, cfg["stock_code"])
        found = list_reports(key, cc, int(cfg["start_year"]))
    except DartError as e:
        print(f"[경고] {e} — 기존 파일 유지", file=sys.stderr)
        write_log("dart", {"status": "실패", "checked_at": started, "message": str(e)[:200]})
        return 0

    done = {r["rcept_no"]: r for r in read_csv(REPORTS)}
    fins = read_csv(FINS)
    added, errors = [], []
    for rep in [r for r in found if r["rcept_no"] not in done]:
        try:
            items, fs = fetch_items(key, cc, rep, cfg["fs_div"])
            if items:
                rows = to_rows(items, rep, fs)
                fins = [f for f in fins if not (f["bsns_year"] == rep["bsns_year"] and f["reprt_code"] == rep["reprt_code"])] + rows
                st, msg = "반영", f"{sum(1 for r in rows if r['value'] != '')}/{len(rows)}개 계정 · {fs}"
            else:
                age = (datetime.now(KST).date() - datetime.strptime(rep["rcept_dt"], "%Y%m%d").date()).days if rep["rcept_dt"] else 99
                if age <= 14:  # 공시 직후엔 재무 API 반영이 늦을 수 있음 → 다음 실행 때 재시도
                    added.append(f"{rep['report_nm']} ({rep['rcept_dt']}) — 재무 데이터 대기")
                    continue
                st, msg = "재무 데이터 없음", "fnlttSinglAcntAll 결과 없음"
            done[rep["rcept_no"]] = {**rep, "status": st, "message": msg, "processed_at": now_kst()}
            added.append(f"{rep['report_nm']} ({rep['rcept_dt']}) — {st} ({msg})")
            save(fins, done)  # 보고서 한 건마다 저장 → 중간에 끊겨도 다음 실행이 이어서 받음
            time.sleep(0.4)
        except DartError as e:
            errors.append(f"{rep['report_nm']}: {e}")  # done에 넣지 않음 → 다음 실행 때 재시도

    save(fins, done)
    write_log("dart", {"status": "성공" if not errors else "일부 실패", "checked_at": started, "corp_code": cc, "reports_total": len(done),
                       "new_reports": added, "errors": errors[:5]})
    print(f"정기보고서 {len(found)}건 확인 · 새로 반영 {len(added)}건 · 오류 {len(errors)}건")
    for a in added:
        print("  +", a)
    for e in errors:
        print("  !", e, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
