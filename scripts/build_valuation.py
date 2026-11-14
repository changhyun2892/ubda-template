#!/usr/bin/env python3
"""
밸류에이션 계산 → data/valuation_daily.csv (일별), data/valuation.json (최신 값 + 산식·입력값)

    python scripts/build_valuation.py --company samyang

입력 (모두 이미 수집된 파일, 인터넷 불필요)
- 주가: data/stock_daily.csv (보통주 종가, 비수정)
- 주식 수: data/raw/dart_shares.csv (collect_shares.py · 정기보고서 '주식의 총수 현황')
- 순이익: data/quarterly.csv 분기 순이익 (지배주주 순이익이 있으면 그것, 없으면 당기순이익) → 최근 4분기 합(TTM)
- 자본: data/raw/dart_financials.csv 자본총계 (분기·반기·사업보고서 기말)
- 배당: data/raw/dart_dividends.csv 사업보고서 보통주 주당 현금배당금

산식
- 시가총액 = 보통주 종가 × 보통주 발행주식총수 (거래소 방식, 우선주 시가총액은 주가가 없어 제외)
- EPS = TTM 순이익 ÷ (보통주+우선주 유통주식수, 자기주식 제외) → PER = 종가 ÷ EPS (순이익이 0 이하면 계산 안 함)
- BPS = 자본총계 ÷ 같은 주식 수 → PBR = 종가 ÷ BPS
- 배당수익률 = 최근 사업보고서 보통주 주당 현금배당금 ÷ 종가

시점: 각 숫자는 그 보고서가 DART에 처음 접수된 날부터 쓴다 (미래 정보가 과거 날짜에 섞이지 않게).
"""
from __future__ import annotations

import bisect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ubda_common import DATA, now_kst, read_csv, write_csv, write_log  # noqa: E402

RAW = DATA / "raw"
Q_RC = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}


def f(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def dash(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def asof(series: list[tuple[str, object]], d: str):
    """series: (사용 시작일, 값) 정렬 목록 → d 시점의 최신 값"""
    i = bisect.bisect_right([s[0] for s in series], d) - 1
    return series[i][1] if i >= 0 else None


def main() -> int:
    now = now_kst()
    stock = read_csv(DATA / "stock_daily.csv")
    reps = read_csv(RAW / "dart_reports.csv")
    shares = [r for r in read_csv(RAW / "dart_shares.csv") if r["se"] != "(없음)"]
    if not stock or not reps or not shares:
        why = "주가 없음" if not stock else "주식 수 자료 없음 (collect_shares.py 먼저)"
        print(f"[건너뜀] {why}")
        write_log("valuation", {"status": "건너뜀", "checked_at": now, "message": why})
        return 0
    first = {}  # (연도, 보고서코드) → 처음 접수일
    for r in reps:
        k = (r["bsns_year"], r["reprt_code"])
        first[k] = min(first.get(k, r["rcept_dt"]), r["rcept_dt"])

    # 주식 수: 보고서별 보통주 발행 수, 보통+우선 유통 수
    by_rc: dict[str, dict] = {}
    for r in shares:
        se = r["se"].replace(" ", "")
        if se in ("합계", "비고") or not se:
            continue
        g = by_rc.setdefault(r["rcept_no"], {"dt": r["rcept_dt"], "common_issued": None, "out": 0.0, "pref": 0.0, "rc": (r["bsns_year"], r["reprt_code"])})
        iss, tr, out = f(r["issued"]), f(r["treasury"]), f(r["outstanding"])
        if out is None and iss is not None:
            out = iss - (tr or 0)
        if "보통" in se:
            g["common_issued"] = iss
            g["common_out"] = out
        else:
            g["pref"] += out or 0
        g["out"] += out or 0
    sh_series = sorted((g["dt"], g) for g in by_rc.values() if g["common_issued"])

    # 순이익 TTM: 분기 순이익(지배주주 우선)
    q = read_csv(DATA / "quarterly.csv")
    qni: dict[tuple[int, int], tuple[float, str]] = {}
    for key in ("net_income", "net_income_owners"):  # 뒤의 지배주주 값이 있으면 덮어씀
        for r in q:
            if r["metric"] == key and f(r["value"]) is not None:
                qni[(int(r["year"]), int(r["quarter"]))] = (f(r["value"]), key)
    ttm_series = []
    for (y, n) in sorted(qni):
        last4 = [(y, n)]
        yy, nn = y, n
        for _ in range(3):
            nn -= 1
            if nn == 0:
                yy, nn = yy - 1, 4
            last4.append((yy, nn))
        if not all(k in qni for k in last4):
            continue
        avail = first.get((str(y), Q_RC[n]))
        if not avail:
            continue
        ttm_series.append((avail, {"value": sum(qni[k][0] for k in last4), "period": f"{last4[-1][0]}Q{last4[-1][1]}~{y}Q{n}",
                                   "basis": "지배주주 순이익" if qni[(y, n)][1] == "net_income_owners" else "당기순이익(비지배 포함)"}))
    # 분기가 모자란 해(분석 시작 전 해 등)는 사업보고서 연간 순이익으로 채움
    have = {s[0] for s in ttm_series}
    fins = read_csv(DATA / "financials.csv")
    for y in sorted({r["year"] for r in fins}):
        avail = first.get((y, "11011"))
        v = next((f(r["value"]) for r in fins if r["year"] == y and r["metric"] == "net_income_owners"), None)
        basis = "지배주주 순이익"
        if v is None:
            v, basis = next((f(r["value"]) for r in fins if r["year"] == y and r["metric"] == "net_income"), None), "당기순이익(비지배 포함)"
        if avail and v is not None and avail not in have:
            ttm_series.append((avail, {"value": v, "period": f"{y} 연간", "basis": basis}))
    ttm_series.sort(key=lambda s: s[0])

    # 자본총계 (보고서 기말)
    eq_series = []
    for r in read_csv(RAW / "dart_financials.csv"):
        if r["metric"] == "total_equity" and f(r["value"]) is not None:
            avail = first.get((r["bsns_year"], r["reprt_code"]))
            if avail:
                eq_series.append((avail, {"value": f(r["value"]), "period": f"{r['bsns_year']} {r['report_type']}"}))
    eq_series = sorted({s[0]: s for s in eq_series}.values(), key=lambda s: s[0])

    # 배당 (사업보고서 보통주 주당 현금배당금)
    dv_series = []
    for r in read_csv(RAW / "dart_dividends.csv"):
        se = r["se"].replace(" ", "")
        if "주당현금배당금" in se and ("보통" in r["stock_knd"] or not r["stock_knd"]):
            avail = first.get((r["bsns_year"], "11011"), r["rcept_dt"])
            v = f(r["thstrm"])
            dv_series.append((avail, {"value": v or 0.0, "year": r["bsns_year"]}))
    payout = {}
    for r in read_csv(RAW / "dart_dividends.csv"):
        if "배당성향" in r["se"].replace(" ", "") and f(r["thstrm"]) is not None:
            payout[r["bsns_year"]] = f(r["thstrm"])
    dv_series = sorted({s[0]: s for s in dv_series}.values(), key=lambda s: s[0])

    rows = []
    for s in stock:
        px = f(s["close"])
        if not px:
            continue
        d = s["date"].replace("-", "")
        sh, ni, eq, dv = asof(sh_series, d), asof(ttm_series, d), asof(eq_series, d), asof(dv_series, d)
        if not sh:
            continue
        mcap = px * sh["common_issued"]
        out = sh["out"] or None
        eps = ni["value"] / out if ni and out else None
        bps = eq["value"] / out if eq and out else None
        rows.append({"date": s["date"], "close": round(px), "market_cap": round(mcap),
                     "per": round(px / eps, 2) if eps and eps > 0 else "", "pbr": round(px / bps, 3) if bps and bps > 0 else "",
                     "div_yield_pct": round(dv["value"] / px * 100, 3) if dv else "",
                     "eps": round(eps, 1) if eps is not None else "", "bps": round(bps, 1) if bps is not None else "", "dps": dv["value"] if dv else ""})
    write_csv(DATA / "valuation_daily.csv", ["date", "close", "market_cap", "per", "pbr", "div_yield_pct", "eps", "bps", "dps"], rows)

    if not rows:
        write_log("valuation", {"status": "건너뜀", "checked_at": now, "message": "주가 기간에 맞는 주식 수 자료 없음"})
        print("[건너뜀] 계산할 날짜 없음")
        return 0
    last = rows[-1]
    d = last["date"].replace("-", "")
    sh, ni, eq, dv = asof(sh_series, d), asof(ttm_series, d), asof(eq_series, d), asof(dv_series, d)
    rmap = {r["rcept_no"]: r for r in reps}
    shrep = next((r for k, r in rmap.items() if by_rc.get(k) is sh), None)
    out = {
        "as_of": last["date"], "close": last["close"], "market_cap": last["market_cap"],
        "per": last["per"] or None, "pbr": last["pbr"] or None, "div_yield_pct": last["div_yield_pct"] or None,
        "eps": last["eps"] or None, "bps": last["bps"] or None, "dps": last["dps"] if last["dps"] != "" else None,
        "inputs": {
            "common_issued": sh["common_issued"], "shares_outstanding": sh["out"], "preferred_outstanding": sh["pref"],
            "shares_report": shrep["report_nm"] if shrep else "", "shares_url": shrep["viewer_url"] if shrep else "",
            "ttm_net_income": ni["value"] if ni else None, "ttm_period": ni["period"] if ni else "", "ni_basis": ni["basis"] if ni else "",
            "equity": eq["value"] if eq else None, "equity_period": eq["period"] if eq else "",
            "dps_year": dv["year"] if dv else "", "payout_pct": payout.get(dv["year"]) if dv else None,
        },
        "notes": ["시가총액은 보통주만 (거래소 방식). 우선주는 주가를 받지 않아 시가총액에서 빠짐",
                  "PER·PBR의 주식 수는 보통주+우선주 유통주식수(자기주식 제외)",
                  "자본총계는 비지배지분을 포함", "비수정 종가 기준 · 자동 계산 · 원문 대조 전"],
        "built_at": now,
    }
    (DATA / "valuation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_log("valuation", {"status": "성공", "checked_at": now, "rows": len(rows), "as_of": last["date"], "per": out["per"], "pbr": out["pbr"]})
    print(f"밸류에이션 {len(rows)}일 · {last['date']} 시총 {last['market_cap'] / 1e12:.2f}조 · PER {out['per']} · PBR {out['pbr']} · 배당수익률 {out['div_yield_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
