#!/usr/bin/env python3
"""
주가 급변일 + 같은 시기 DART 공시 자동 수집 → data/events_auto.csv, data/event_links.csv

    python scripts/collect_events.py --company samyang

1) 급변일: data/stock_daily.csv(update_stock.py 결과)에서
   초과 등락률 = 종목 등락률 − 시장지수 등락률 (그날 시장 전체가 움직인 만큼은 뺀다)
   기준: |초과 등락률| ≥ 직전 250거래일 초과 등락률 표준편차 × 2.5  또는  |초과 등락률| ≥ 5%
   연도별로 크기(표준편차 배수) 상위 10일만 남긴다. 거래량이 직전 20일 평균의 3배 이상이면 함께 표시.
2) 공시: DART 공시 목록(list.json, 모든 유형)을 data/raw/dart_disclosures.csv에 모아 두고
   처음에는 start_year−1년 1월부터, 그다음부터는 마지막 접수일 7일 전부터만 다시 받는다.
3) 연결: 급변일 2거래일 전 다음 날 ~ 급변일 당일에 접수된 공시를 붙인다
   (장 마감 뒤·주말 공시는 다음 거래일 주가에 반영되기 때문). 주요 유형만 따로 보이고 나머지는 '기타'로 센다.
4) data/raw/news.csv(collect_news.py)가 있으면 같은 기간 기사를 '보도'로 붙인다 (보도 후보 · 확인 전).
   뉴스 검색은 최근 1,000건까지만 돼서, 뉴스 수집을 시작한 뒤의 급변일 위주로 채워진다.

같은 시기에 있었던 공시일 뿐, 주가 변동의 원인이라는 뜻이 아니다. 공시가 없는 급변일도 지우지 않는다.
주가는 비수정 종가라 액면분할·무상증자일은 가격 착시가 생길 수 있어, 그 공시가 붙으면 note에 적는다.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ubda_common import DATA, KST, DartError, dart_get, load_config, now_kst, read_csv, write_csv, write_log  # noqa: E402

RAW = DATA / "raw"
DISC = RAW / "dart_disclosures.csv"
OUT_EV = DATA / "events_auto.csv"
OUT_LK = DATA / "event_links.csv"

SIGMA_K, ABS_MIN, TOP_PER_YEAR, WIN_SIGMA, MIN_HIST, VOL_K = 2.5, 5.0, 10, 250, 60, 3.0

# 주가에 영향을 줄 만한 공시 유형 (위에서부터 먼저 맞는 것). report_nm 기준
CATS = [
    ("실적", r"잠정\)?실적|영업\(잠정\)|매출액또는손익구조|손익구조30%|손익구조\s*30"),
    ("정기보고서", r"^(?!\[)(사업|반기|분기)보고서"),  # 실적이 처음 공개되는 회사가 많음. 지난 보고서 정정([기재정정])은 기타
    ("공급계약", r"단일판매|공급계약"),
    ("시설투자", r"신규시설투자|유형자산\s*양수|유형자산양수"),
    ("합병·분할", r"합병|분할|영업양수|영업양도|주식교환|주식이전"),
    ("지분·출자", r"타법인주식및출자증권|출자증권\s*(취득|처분)|공개매수"),
    ("최대주주", r"최대주주\s*변경|최대주주변경"),
    ("증자·사채", r"유상증자|무상증자|전환사채|신주인수권부사채|교환사채|감자"),
    ("자기주식", r"자기주식|주식소각"),
    ("배당", r"배당"),
    ("소송·제재", r"소송|횡령|배임|영업정지|불성실공시|거래정지|매매거래정지|조회공시|풍문"),
]
MAJOR = {c for c, _ in CATS}
PRIO = {c: k for k, (c, _) in enumerate(CATS)}
PRICE_TRAP = re.compile(r"주식분할|액면분할|무상증자|주식병합|감자")


def viewer(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def category(nm: str) -> str:
    for c, pat in CATS:
        if re.search(pat, nm.replace(" ", "")) or re.search(pat, nm):
            return c
    return "기타"


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def spikes(rows: list[dict]) -> list[dict]:
    pts = [(r["date"], f(r["close"]), f(r["volume"]), f(r.get("index_close"))) for r in rows]
    pts = [p for p in pts if p[1]]
    out, ex_hist = [], []
    for i in range(1, len(pts)):
        d, c, v, ix = pts[i]
        _, c0, _, ix0 = pts[i - 1]
        r = (c / c0 - 1) * 100
        m = (ix / ix0 - 1) * 100 if ix and ix0 else None
        e = r - m if m is not None else r
        hist = ex_hist[-WIN_SIGMA:]
        sd = None
        if len(hist) >= MIN_HIST:
            mu = sum(hist) / len(hist)
            sd = math.sqrt(sum((h - mu) ** 2 for h in hist) / (len(hist) - 1))
        vols = [p[2] for p in pts[max(0, i - 20):i] if p[2]]
        vr = v / (sum(vols) / len(vols)) if v and vols else None
        ex_hist.append(e)
        if sd is None:  # 비교할 과거가 짧으면 판단하지 않음
            continue
        z = abs(e) / sd if sd else 0
        if z >= SIGMA_K or abs(e) >= ABS_MIN:
            out.append({"i": i, "date": d, "close": round(c), "ret_pct": round(r, 2), "index_ret_pct": "" if m is None else round(m, 2),
                        "excess_pct": round(e, 2), "sigma_pct": round(sd, 2), "z": round(z, 2), "volume_ratio": "" if vr is None else round(vr, 1),
                        "direction": "상승" if e > 0 else "하락", "volume_spike": "Y" if vr and vr >= VOL_K else ""})
    keep = []
    by_year: dict[str, list] = {}
    for s in out:
        by_year.setdefault(s["date"][:4], []).append(s)
    for y, lst in by_year.items():
        lst.sort(key=lambda s: -s["z"])
        for k, s in enumerate(lst[:TOP_PER_YEAR], 1):
            s["rank_in_year"] = k
            s["candidates_in_year"] = len(lst)
            keep.append(s)
    keep.sort(key=lambda s: s["date"])
    return keep, pts


def fetch_disclosures(key: str, cc: str, start_year: int) -> tuple[list[dict], int]:
    old = read_csv(DISC) if DISC.exists() else []
    seen = {r["rcept_no"] for r in old}
    if old:
        last = max(r["rcept_dt"] for r in old)
        bgn = (datetime.strptime(last, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
    else:
        bgn = f"{start_year - 1}0101"
    end = datetime.now(KST).strftime("%Y%m%d")
    new = []
    # DART list.json은 corp_code 지정 시에도 한 번에 조회 기간 제한이 있어 1년 단위로 나눈다
    a = datetime.strptime(bgn, "%Y%m%d")
    z = datetime.strptime(end, "%Y%m%d")
    while a <= z:
        b = min(z, a + timedelta(days=364))
        page = 1
        while True:
            js = dart_get("list.json", {"crtfc_key": key, "corp_code": cc, "bgn_de": a.strftime("%Y%m%d"), "end_de": b.strftime("%Y%m%d"),
                                        "page_no": page, "page_count": 100})
            for r in js.get("list", []):
                if r["rcept_no"] in seen:
                    continue
                seen.add(r["rcept_no"])
                nm = re.sub(r"\s+", " ", (r.get("report_nm") or "").strip())
                new.append({"rcept_no": r["rcept_no"], "rcept_dt": r.get("rcept_dt", ""), "report_nm": nm, "flr_nm": r.get("flr_nm", ""),
                            "rm": r.get("rm", ""), "category": category(nm), "viewer_url": viewer(r["rcept_no"])})
            if page >= int(js.get("total_page", 1) or 1):
                break
            page += 1
        a = b + timedelta(days=1)
    allr = sorted(old + new, key=lambda r: (r["rcept_dt"], r["rcept_no"]))
    for r in allr:  # 분류 규칙을 고치면 예전 행도 다시 분류
        r["category"] = category(r["report_nm"])
    RAW.mkdir(parents=True, exist_ok=True)
    write_csv(DISC, ["rcept_no", "rcept_dt", "report_nm", "flr_nm", "rm", "category", "viewer_url"], allr)
    return allr, len(new)


def main() -> int:
    cfg = load_config()
    now = now_kst()
    stock = read_csv(DATA / "stock_daily.csv") if (DATA / "stock_daily.csv").exists() else []
    if len(stock) < MIN_HIST + 2:
        print("[건너뜀] 주가 자료가 부족합니다 (update_stock.py 먼저)")
        write_log("events", {"status": "건너뜀", "checked_at": now, "message": "주가 자료 부족"})
        return 0
    days, pts = spikes(stock)
    key = os.environ.get("DART_API_KEY", "").strip()
    disc, n_new, err = [], 0, ""
    meta = DATA / "raw" / "dart_meta.json"
    cc = json.loads(meta.read_text(encoding="utf-8")).get("corp_code") if meta.exists() else None
    if key and cc:
        try:
            disc, n_new = fetch_disclosures(key, cc, int(cfg["start_year"]))
        except DartError as e:
            err = str(e)
            print(f"[경고] 공시 목록 수집 실패: {e} — 저장된 목록으로 연결", file=sys.stderr)
    else:
        err = "DART_API_KEY 없음" if not key else "corp_code 없음 (collect_dart.py 먼저)"
        print(f"[경고] {err} — 저장된 공시 목록으로 연결", file=sys.stderr)
    if not disc and DISC.exists():
        disc = read_csv(DISC)
    for r in disc:  # 분류 규칙을 고치면 저장된 목록도 다시 분류
        r["category"] = category(r["report_nm"])

    news_p = DATA / "raw" / "news.csv"  # collect_news.py (네이버 키가 있을 때만)
    news = read_csv(news_p) if news_p.exists() else []
    dates = [p[0] for p in pts]
    ev, links = [], []
    for s in days:
        i = s["i"]
        lo = dates[i - 2] if i >= 2 else dates[0]  # 2거래일 전 날짜 (그 다음 날부터 포함)
        lo_k, hi_k = lo.replace("-", ""), s["date"].replace("-", "")
        hit = [r for r in disc if lo_k < r["rcept_dt"] <= hi_k]
        major = sorted((r for r in hit if r["category"] in MAJOR), key=lambda r: PRIO[r["category"]])  # 실적·계약 같은 유형이 먼저
        notes = []
        if any(PRICE_TRAP.search(r["report_nm"]) for r in hit):
            notes.append("주식 수가 바뀌는 공시가 있어 비수정 주가의 착시일 수 있음")
        for r in hit:
            links.append({"date": s["date"], "rcept_dt": r["rcept_dt"], "category": r["category"], "major": "Y" if r["category"] in MAJOR else "",
                          "report_nm": r["report_nm"], "flr_nm": r.get("flr_nm", ""), "rcept_no": r["rcept_no"], "viewer_url": r["viewer_url"]})
        nw = [r for r in news if lo_k < r["pub_dt"][:10].replace("-", "") <= hi_k]
        for r in nw:
            links.append({"date": s["date"], "rcept_dt": r["pub_dt"][:10].replace("-", ""), "category": "보도", "major": "", "report_nm": r["title"],
                          "flr_nm": r.get("press", ""), "rcept_no": "", "viewer_url": r["link"]})
        ev.append({**{k: v for k, v in s.items() if k != "i"}, "news_count": len(nw) if news else "",
                   "window": f"{lo_k[:4]}-{lo_k[4:6]}-{lo_k[6:]} 다음 날 ~ {s['date']}",
                   "major_count": len(major), "other_count": len(hit) - len(major),
                   "headline": (major[0]["report_nm"] if major else ("연결된 주요 공시 없음" if disc else "공시 목록 미수집")),
                   "categories": "·".join(dict.fromkeys(r["category"] for r in major)),
                   "note": " / ".join(notes), "status": "자동 수집 · 같은 시기 공시이며 원인 아님"})
    cols = ["date", "direction", "close", "ret_pct", "index_ret_pct", "excess_pct", "sigma_pct", "z", "volume_ratio", "volume_spike",
            "rank_in_year", "candidates_in_year", "window", "major_count", "other_count", "news_count", "headline", "categories", "note", "status"]
    write_csv(OUT_EV, cols, ev)
    write_csv(OUT_LK, ["date", "rcept_dt", "category", "major", "report_nm", "flr_nm", "rcept_no", "viewer_url"], links)
    linked = sum(1 for e in ev if e["major_count"])
    info = {"status": "성공" if not err else ("부분 성공" if disc else "공시 미수집"), "checked_at": now, "spike_days": len(ev),
            "with_major_disclosure": linked, "news_total": len(news), "disclosures_total": len(disc), "disclosures_new": n_new,
            "rule": f"|초과 등락률| ≥ {SIGMA_K}σ(직전 {WIN_SIGMA}거래일) 또는 ≥ {ABS_MIN}%, 연도별 상위 {TOP_PER_YEAR}일, 공시 창 D-2(다음 날)~D",
            **({"message": err} if err else {})}
    write_log("events", info)
    print(f"급변일 {len(ev)}일 (주요 공시 연결 {linked}일) · 공시 목록 {len(disc)}건 (새로 {n_new}건)" + (f" · {err}" if err else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
