#!/usr/bin/env python3
"""
정기보고서별 주식 수·배당 (DART) → data/raw/dart_shares.csv, data/raw/dart_dividends.csv (누적 캐시)

    python scripts/collect_shares.py --company samyang

- 주식의 총수 현황(stockTotqySttus.json): 보통주·우선주별 발행주식총수, 자기주식수, 유통주식수 — 모든 정기보고서
- 배당에 관한 사항(alotMatter.json): 주당 현금배당금, 현금배당수익률, 배당성향 — 사업보고서만
- collect_dart.py가 만든 data/raw/dart_reports.csv의 보고서 중 아직 안 받은 것만 요청한다.
- 밸류에이션 계산은 build_valuation.py가 한다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ubda_common import DATA, DartError, dart_get, num, now_kst, read_csv, write_csv, write_log  # noqa: E402

RAW = DATA / "raw"
SH = RAW / "dart_shares.csv"
DV = RAW / "dart_dividends.csv"
SH_COLS = ["rcept_no", "rcept_dt", "bsns_year", "reprt_code", "se", "issued", "treasury", "outstanding"]
DV_COLS = ["rcept_no", "rcept_dt", "bsns_year", "se", "stock_knd", "thstrm", "frmtrm"]


def main() -> int:
    now = now_kst()
    key = os.environ.get("DART_API_KEY", "").strip()
    meta = RAW / "dart_meta.json"
    cc = json.loads(meta.read_text(encoding="utf-8")).get("corp_code") if meta.exists() else None
    reps = [r for r in read_csv(RAW / "dart_reports.csv") if r.get("status") == "반영"]
    if not key or not cc or not reps:
        msg = "DART_API_KEY 없음" if not key else "보고서 목록 없음 (collect_dart.py 먼저)"
        print(f"[건너뜀] {msg}")
        write_log("shares", {"status": "건너뜀", "checked_at": now, "message": msg})
        return 0
    sh, dv = read_csv(SH), read_csv(DV)
    done_sh, done_dv = {r["rcept_no"] for r in sh}, {r["rcept_no"] for r in dv}
    new_sh = new_dv = 0
    errors = []
    for rep in reps:
        p = {"crtfc_key": key, "corp_code": cc, "bsns_year": rep["bsns_year"], "reprt_code": rep["reprt_code"]}
        base = {"rcept_no": rep["rcept_no"], "rcept_dt": rep["rcept_dt"], "bsns_year": rep["bsns_year"]}
        if rep["rcept_no"] not in done_sh:
            try:
                lst = dart_get("stockTotqySttus.json", p).get("list", [])
                rows = [{**base, "reprt_code": rep["reprt_code"], "se": (r.get("se") or "").strip(), "issued": num(r.get("istc_totqy")),
                         "treasury": num(r.get("tesstk_co")), "outstanding": num(r.get("distb_stock_co"))} for r in lst]
                sh += rows or [{**base, "reprt_code": rep["reprt_code"], "se": "(없음)", "issued": "", "treasury": "", "outstanding": ""}]
                new_sh += 1
            except DartError as e:
                errors.append(f"{rep['report_nm']} 주식 수: {e}")
        if rep["reprt_code"] == "11011" and rep["rcept_no"] not in done_dv:
            try:
                lst = dart_get("alotMatter.json", p).get("list", [])
                rows = [{**base, "se": (r.get("se") or "").strip(), "stock_knd": (r.get("stock_knd") or "").strip(),
                         "thstrm": (r.get("thstrm") or "").strip(), "frmtrm": (r.get("frmtrm") or "").strip()} for r in lst]
                dv += rows or [{**base, "se": "(없음)", "stock_knd": "", "thstrm": "", "frmtrm": ""}]
                new_dv += 1
            except DartError as e:
                errors.append(f"{rep['report_nm']} 배당: {e}")
        if len(errors) >= 3:
            break
    RAW.mkdir(parents=True, exist_ok=True)
    write_csv(SH, SH_COLS, sorted(sh, key=lambda r: (r["rcept_dt"], r["rcept_no"], r["se"])))
    write_csv(DV, DV_COLS, sorted(dv, key=lambda r: (r["rcept_dt"], r["rcept_no"])))
    write_log("shares", {"status": "성공" if not errors else "부분 성공", "checked_at": now, "new_share_reports": new_sh, "new_dividend_reports": new_dv,
                         **({"errors": errors[:3]} if errors else {})})
    print(f"주식 수 새로 {new_sh}건 · 배당 새로 {new_dv}건" + (f" · 오류 {errors[0]}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
