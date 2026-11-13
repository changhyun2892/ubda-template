#!/usr/bin/env python3
"""
산업 KPI 원문 대조(자동) — kpi_values.csv의 숫자가 저장된 사업보고서 본문에 실제로 있는지 찾는다.

    python scripts/crosscheck_kpi.py [기업 ...]        (없으면 전체)
    결과: companies/_runs/kpi_crosscheck.csv  ·  화면에 기업별 요약

· 본문: data/raw/business_*.txt, overview_*.txt (collect_business_text.py가 저장)
· 값 v를 원문 단위 후보(1, 천, 만, 백만, 억, 십억, 조)로 나눠 본문 숫자와 같으면 '원문 일치'.
· 작은 정수(1,000 미만, 소수점 없음)는 우연히 맞을 수 있어 '일치(약함)'으로 따로 센다.
· 못 찾으면: 메모에 합산·계산 표시가 있으면 '계산값', 범위가 다른 보고서(재작성·전년 보고서)면 '다른 보고서', 나머지는 '원문에서 못 찾음'(사람 확인 대상).
· 이 점검은 '숫자가 본문 어딘가에 있다'만 확인한다. 같은 표·같은 행인지는 확인하지 않는다(상태를 바꾸지 않음).
"""
from __future__ import annotations

import csv
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MULTS = [Decimal(1), Decimal(10) ** 3, Decimal(10) ** 4, Decimal(10) ** 6, Decimal(10) ** 8, Decimal(10) ** 9, Decimal(10) ** 11, Decimal(10) ** 12]
NUM = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])|(?<![\d.,])\d+(?:\.\d+)?(?![\d,])")
CALC = re.compile(r"합산|합계로|계산|산출|단순 합|더한|차감 후|÷|비중\(계산|파생|추정")
OTHER = re.compile(r"재작성|비교 표시|\d{4} 보고서|전년 보고서|이전 보고서")


def numbers(text: str) -> set[Decimal]:
    out = set()
    for m in NUM.finditer(text):
        try:
            d = Decimal(m.group(0).replace(",", ""))
        except InvalidOperation:
            continue
        out.add(d.normalize())
    return out


def found(v: Decimal, nums: set[Decimal]) -> tuple[bool, Decimal | None]:
    a = abs(v)
    for m in MULTS:
        x = a / m
        if x == 0:
            continue
        cands = {x.normalize()}
        # 원문이 소수 1~2자리로 반올림해 적은 경우(예: 13.4%)
        for q in ("1", "0.1", "0.01"):
            cands.add(x.quantize(Decimal(q)).normalize())
        for c in cands:
            if c in nums and abs(c - x) <= abs(x) * Decimal("0.0005") + Decimal("0.005"):
                return True, x
    return False, None


def tokens(text: str) -> list[Decimal]:
    """본문 숫자를 나온 순서대로 (표 형식이 회사마다 달라 행 경계 대신 '가까이 붙어 있음'으로 판단)."""
    out = []
    for m in NUM.finditer(text):
        try:
            out.append(Decimal(m.group(0).replace(",", "")).normalize())
        except InvalidOperation:
            pass
    return out


def same_row(vals: list[tuple[int, Decimal]], toks: list[Decimal], window: int = 12) -> str:
    """같은 항목의 여러 연도 값이 원문에서 가까이(숫자 12개 안) 함께 나오는지, 연도 순서(오름·내림)대로인지."""
    suspect = False
    idx: dict[Decimal, list[int]] = {}
    for i, n in enumerate(toks):
        idx.setdefault(n, []).append(i)
    for m in MULTS:
        xs = []
        for y, v in vals:
            x = (abs(v) / m)
            if x == 0:
                break
            ks = {x.normalize(), x.quantize(Decimal("0.1")).normalize(), x.quantize(Decimal("0.01")).normalize()}
            hits = sorted({i for k in ks for i in idx.get(k, [])})
            if not hits:
                break
            xs.append((y, x.normalize(), hits))
        else:
            if len({x for _, x, _ in xs}) < len(xs):
                # 값이 같은 연도가 있으면 가까이 있는지만 본다
                base = xs[0][2]
                if any(all(any(abs(h - b) <= window for h in hs) for _, _, hs in xs) for b in base):
                    return "같은 행"
                continue
            ys = sorted(xs)  # 연도순
            for b in ys[0][2]:
                for direction in (1, -1):
                    cur, ok = b, True
                    for _, _, hs in ys[1:]:
                        nxt = [h for h in hs if 0 < (h - cur) * direction <= window]
                        if not nxt:
                            ok = False
                            break
                        cur = min(nxt, key=lambda h: abs(h - cur))
                    if ok:
                        return "같은 행"
            # 가까이 있지만 순서가 섞인 경우
            for b in ys[0][2]:
                if all(any(abs(h - b) <= window for h in hs) for _, _, hs in ys[1:]):
                    suspect = True
    return "같은 행 · 연도 순서 의심" if suspect else "같은 행 없음"


def check(slug: str) -> list[dict]:
    d = ROOT / "companies" / slug / "data"
    kp = d / "manual" / "kpi_values.csv"
    if not kp.exists():
        return []
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted((d / "raw").glob("business_*.txt")) + sorted((d / "raw").glob("overview_*.txt")))
    nums = numbers(text)
    res = []
    for r in csv.DictReader(kp.open(encoding="utf-8-sig")):
        val = (r.get("value") or "").strip()
        if not val:
            continue
        try:
            v = Decimal(val)
        except InvalidOperation:
            continue
        ok, x = found(v, nums) if text else (False, None)
        if ok:
            weak = x == x.to_integral_value() and abs(x) < 1000
            kind = "일치(약함)" if weak else "원문 일치"
        elif "주석" in r.get("source_location", ""):
            kind = "본문 밖 출처"  # 연결재무제표 주석 등 저장하지 않은 장
        elif not text:
            kind = "본문 없음"
        elif "서술" in r.get("note", "") + r.get("scope", ""):
            kind = "서술형"  # '2조 2,752억'처럼 숫자가 나뉘어 적힌 문장
        elif CALC.search(r.get("note", "") + r.get("item", "")):
            kind = "계산값"
        elif OTHER.search(r.get("scope", "") + r.get("source_location", "") + r.get("note", "")):
            kind = "다른 보고서"
        else:
            kind = "원문에서 못 찾음"
        res.append({"company": slug, "kpi_key": r["kpi_key"], "year": r["year"], "item": r["item"], "value": val, "unit": r.get("unit", ""),
                    "scope": r.get("scope", ""), "result": kind, "row_check": "", "source_location": r.get("source_location", "")})
    # 여러 연도 값이 있는 항목: 원문 표 한 행에 함께 있는지
    toks = tokens(text) if text else []
    groups: dict[tuple, list[dict]] = {}
    for x in res:
        groups.setdefault((x["kpi_key"], x["item"], x["scope"], x["unit"]), []).append(x)
    for g in groups.values():
        ys = {x["year"] for x in g}
        if len(ys) < 2 or len(ys) != len(g) or any(x["result"] not in ("원문 일치", "일치(약함)") for x in g):
            continue
        rc = same_row([(int(x["year"]), Decimal(x["value"])) for x in g], toks)
        for x in g:
            x["row_check"] = rc
    return res


def main() -> int:
    slugs = sys.argv[1:] or sorted(p.parent.name for p in (ROOT / "companies").glob("*/company.json"))
    allr = []
    print(f"{'기업':<14}{'행':>5}{'일치':>6}{'약함':>6}{'계산':>6}{'기타':>6}{'못찾음':>7}{'행순서의심':>8}{'행없음':>7}")
    for s in slugs:
        rs = check(s)
        allr += rs
        c = lambda k: sum(1 for x in rs if x["result"] == k)
        o = sum(1 for x in rs if x["result"] in ("다른 보고서", "본문 밖 출처", "서술형"))
        rq = sum(1 for x in rs if "의심" in x["row_check"]); rn = sum(1 for x in rs if x["row_check"] == "같은 행 없음")
        print(f"{s:<14}{len(rs):>5}{c('원문 일치'):>6}{c('일치(약함)'):>6}{c('계산값'):>6}{o:>6}{c('원문에서 못 찾음'):>7}{rq:>8}{rn:>7}" + ("  [본문 없음]" if c("본문 없음") else ""))
    out = ROOT / "companies" / "_runs" / "kpi_crosscheck.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allr[0].keys()) if allr else ["company"])
        w.writeheader()
        w.writerows(allr)
    tot = len(allr)
    c = lambda k: sum(1 for x in allr if x["result"] == k)
    rq = sum(1 for x in allr if "의심" in x["row_check"]); rs_ = sum(1 for x in allr if x["row_check"] == "같은 행"); rn = sum(1 for x in allr if x["row_check"] == "같은 행 없음")
    print(f"\n전체 {tot}행 · 원문 일치 {c('원문 일치')} · 약함 {c('일치(약함)')} · 계산값 {c('계산값')} · 본문 밖·서술·타보고서 {c('본문 밖 출처') + c('서술형') + c('다른 보고서')} · 못 찾음 {c('원문에서 못 찾음')}")
    print(f"여러 연도 행 대조: 같은 행 {rs_} · 연도 순서 의심 {rq} · 같은 행 없음 {rn} → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
