"""
기업 토론(평의회) — API 없이, 사용자가 요청할 때 Claude(구독 세션)가 직접 토론을 작성하고 이 스크립트로 검사·저장합니다.

  python scripts/build_debate.py --todo                      # 이번 달 토론이 아직 없는 기업 목록
  python scripts/build_debate.py --prompt samyang            # 데이터가 채워진 프롬프트 출력 → 이걸 읽고 토론 JSON 작성
  python scripts/build_debate.py --save samyang /tmp/a.json  # 작성한 JSON 검사 → 통과하면 debate/<YYYY-MM>.json 저장

검사: JSON 형식, 고문 5명(순서·이름), 확신도 0~100, 그리고
      "발언·결론 속 숫자가 데이터 시트에 있는 숫자인가" (반올림 허용, 연도·12 이하 정수 제외). 하나라도 틀리면 저장하지 않음.
절차 문서: docs/토론_생성절차.md · 프롬프트: prompts/debate_council.md
비용: API를 쓰지 않으므로 별도 요금 없음 (구독 사용량만 씀). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES = ROOT / "companies"
PROMPT_FILE = ROOT / "prompts" / "debate_council.md"
KST = timezone(timedelta(hours=9))
ROLES = ["약세론자", "본질 분석가", "기회 탐색가", "외부자", "점검 담당"]


# ---------------------------------------------------------------- 읽기 도우미
def rcsv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def rjson(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def fnum(v):
    try:
        x = float(str(v).replace(",", ""))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def won(v) -> str:
    """원 → '2,351.8억원' (1조 이상은 '(2.35조원)' 병기)."""
    v = fnum(v)
    eok = v / 1e8
    s = f"{eok:,.1f}억원"
    if abs(v) >= 1e12:
        s += f" ({v / 1e12:,.2f}조원)"
    return s


def pct(v, d=1) -> str:
    v = fnum(v)
    return f"{v:.{d}f}%"


# ---------------------------------------------------------------- 데이터 시트
def fact_sheet(slug: str, index: dict | None) -> tuple[str, dict]:
    """AI에게 줄 데이터 시트(텍스트)와 메타. 모든 줄 = '- 항목 (기간): 값 [출처 항목 · 기준]'."""
    cdir = COMPANIES / slug
    d = cdir / "data"
    co = rjson(cdir / "company.json") or {}
    L: list[str] = []
    add = L.append
    meta = {"name": co.get("name", slug), "code": co.get("stock_code", ""), "industry": co.get("industry", "")}

    ind = rjson(ROOT / "industries" / f"{co.get('industry', '')}.json") or {}
    add(f"## 기업\n- {co.get('name', slug)} ({co.get('stock_code', '')}) · 산업 {ind.get('name', co.get('industry', ''))} · 카테고리 {', '.join(co.get('categories', [])) or '미확인'} [기업 정보]")

    # 연간 재무
    fin = rcsv(d / "financials.csv")
    years = sorted({r["year"] for r in fin})[-3:]
    meta["years"] = years
    if years:
        add("\n## 연간 재무 (DART 연결/별도 재무제표)")
        want = ["revenue", "operating_profit", "net_income", "total_assets", "total_liabilities", "total_equity", "operating_cashflow", "capex", "cash"]
        for y in years:
            for k in want:
                r = next((r for r in fin if r["year"] == y and r["metric"] == k), None)
                v = fnum(r["value"]) if r else None
                if r and v is not None:
                    add(f"- {r['label'] if 'label' in r else k} ({y}): {won(v)} [재무 · {y}]")
    met = rcsv(d / "metrics.csv")
    if met:
        add("\n## 재무비율 (DART 값으로 계산)")
        keep = ["revenue_growth_pct", "op_growth_pct", "operating_margin_pct", "net_margin_pct", "roe_pct", "roa_pct", "debt_ratio_pct", "current_ratio_pct", "asset_turnover", "cost_ratio_pct", "sga_ratio_pct"]
        for y in years:
            for k in keep:
                r = next((r for r in met if r["year"] == y and r["metric"] == k), None)
                v = fnum(r["value"]) if r else None
                if r and v is not None:
                    val = f"{v:.2f}회" if k == "asset_turnover" else pct(v)
                    add(f"- {r['label']} ({y}): {val} [재무비율 · {y}]")

    # 성과체계: ROE = 순이익률 × 총자산회전율 × 레버리지
    def mv(y, k):
        r = next((r for r in met if r["year"] == y and r["metric"] == k), None)
        return fnum(r["value"]) if r else None
    pt = []
    for y in years[-2:]:
        roe, nm, at = mv(y, "roe_pct"), mv(y, "net_margin_pct"), mv(y, "asset_turnover")
        if None not in (roe, nm, at) and nm and at:
            lev = roe / (nm * at)
            pt.append(f"- ROE 분해 ({y}): ROE {pct(roe)} = 순이익률 {pct(nm)} × 총자산회전율 {at:.2f}회 × 재무레버리지 {lev:.2f}배 [성과체계 · {y}]")
    if pt:
        add("\n## 성과체계 (ROE 분해)")
        L.extend(pt)

    # 분기
    q = rcsv(d / "quarterly.csv")
    periods = sorted({r["period"] for r in q})[-5:]
    if periods:
        add("\n## 분기 단일 실적 (Q4 = 연간 − 3분기 누적)")
        for p in periods:
            for k, lab in (("revenue", "매출액"), ("operating_profit", "영업이익")):
                r = next((r for r in q if r["period"] == p and r["metric"] == k), None)
                v = fnum(r["value"]) if r else None
                if v is not None:
                    add(f"- {lab} ({p}): {won(v)} [분기 실적 · {p}]")
        meta["latest_quarter"] = periods[-1]

    # 밸류에이션
    val = rjson(d / "valuation.json")
    if val:
        a = val.get("as_of", "")
        add(f"\n## 밸류에이션 (기준일 {a})")
        if val.get("close") is not None: add(f"- 종가: {val['close']:,.0f}원 [밸류에이션 · {a}]")
        if val.get("market_cap") is not None: add(f"- 시가총액: {won(val['market_cap'])} [밸류에이션 · {a}]")
        for k, lab in (("per", "PER(최근 4분기 지배주주 순이익)"), ("pbr", "PBR")):
            if val.get(k) is not None: add(f"- {lab}: {val[k]:.2f}배 [밸류에이션 · {a}]")
            else: add(f"- {lab}: 미확인 (적자 또는 자료 없음) [밸류에이션 · {a}]")
        if val.get("div_yield_pct") is not None: add(f"- 배당수익률: {val['div_yield_pct']:.2f}% (주당배당금 {val.get('dps') or 0:,.0f}원) [밸류에이션 · {a}]")
        po = (val.get("inputs") or {}).get("payout_pct")
        if po is not None: add(f"- 배당성향: {po:.1f}% [밸류에이션 · {(val.get('inputs') or {}).get('dps_year', a)}]")
        meta["val_asof"] = a

    # 종합 진단
    dg = rjson(d / "diagnosis.json")
    if dg:
        y = dg.get("year", "")
        add(f"\n## 종합 진단 (같은 산업 {dg.get('peers', '?')}곳 사이 백분위, 50 = 가운데 · {y})")
        for ax in (dg.get("axes") or {}).values():
            if ax.get("score") is not None: add(f"- {ax['label']} 백분위: {ax['score']} [종합 진단 · {y}]")
        for f in (dg.get("factors") or {}).values():
            if f.get("rank"): add(f"- {f['label']}: {f.get('text', '')} (업종 {f['n']}곳 중 {f['rank']}위) [종합 진단 · {y}]")
        for p in (dg.get("profiles") or {}).values():
            if p.get("score") is not None: add(f"- {p['label']} 투자자 적합 점수: {p['score']} ({p.get('level', '')}) [종합 진단 · {y}]")

    # 같은 산업 비교
    if index:
        peers = [c for c in index.get("companies", []) if c.get("industry") == co.get("industry") and c.get("slug") != slug and c.get("kpis")]
        if peers:
            add(f"\n## 같은 산업 비교 기업 (각 사 최신 사업연도)")
            for c in peers:
                k = {a: fnum(b) for a, b in (c.get("kpis") or {}).items()}
                v = {a: fnum(b) for a, b in (c.get("valuation") or {}).items() if a != "as_of"}
                parts = []
                if k.get("revenue") is not None: parts.append(f"매출액 {won(k['revenue'])}")
                if k.get("operating_margin_pct") is not None: parts.append(f"영업이익률 {pct(k['operating_margin_pct'])}")
                if k.get("revenue_growth_pct") is not None: parts.append(f"매출 증가율 {pct(k['revenue_growth_pct'])}")
                if k.get("debt_ratio_pct") is not None: parts.append(f"부채비율 {pct(k['debt_ratio_pct'])}")
                if v.get("per") is not None: parts.append(f"PER {v['per']:.2f}배")
                if v.get("pbr") is not None: parts.append(f"PBR {v['pbr']:.2f}배")
                add(f"- {c['name']} ({c.get('latest_year', '')}): {', '.join(parts)} [같은 산업 비교 · {c.get('latest_year', '')}]")

    # 주가
    st = rcsv(d / "stock_daily.csv")
    if st:
        last = st[-1]
        lc = fnum(last.get("raw_close") or last["close"])
        add(f"\n## 주가 (야후 파이낸스, 기준일 {last['date']})")
        adj = [(r["date"], fnum(r.get("adj_close") or r["close"]), fnum(r.get("index_close"))) for r in st]
        adj = [x for x in adj if x[1]]
        if lc: add(f"- 종가: {lc:,.0f}원 [주가 · {last['date']}]")
        end = date.fromisoformat(last["date"])
        for days, lab in ((91, "3개월"), (365, "1년")):
            cut = (end - timedelta(days=days)).isoformat()
            base = next((x for x in adj if x[0] >= cut), None)
            if base and adj and base[0] < adj[-1][0]:
                r = (adj[-1][1] / base[1] - 1) * 100
                s = f"- {lab} 수익률(수정종가): {r:.1f}%"
                if base[2] and adj[-1][2]:
                    s += f", 같은 기간 시장지수 {(adj[-1][2] / base[2] - 1) * 100:.1f}%"
                add(s + f" [주가 · {base[0]}~{adj[-1][0]}]")
        meta["stock_asof"] = last["date"]
        ev = rcsv(d / "events_auto.csv")
        cut = (end - timedelta(days=365)).isoformat()
        ev = sorted([e for e in ev if e["date"] >= cut], key=lambda e: -abs(fnum(e.get("excess_pct")) or 0))[:6]
        if ev:
            add("\n## 최근 1년 주가 급변일 (시장 대비 초과 수익률 큰 순 · 같은 시기 공시는 원인이 아님)")
            for e in sorted(ev, key=lambda e: e["date"]):
                add(f"- {e['date']} {e['direction']}: 등락률 {fnum(e['ret_pct']):.1f}%, 시장 대비 {fnum(e['excess_pct']):.1f}%, 같은 시기 공시: {e.get('headline') or '없음'} [급변일 · {e['date']}]")

    # 사건 연표 (주요 공시)
    dis = rcsv(d / "raw" / "dart_disclosures.csv")
    major = {"실적", "공급계약", "시설투자", "합병·분할", "지분·출자", "최대주주", "증자·사채", "소송·제재", "배당", "자기주식"}
    if dis:
        cut = (datetime.now(KST).date() - timedelta(days=365)).strftime("%Y%m%d")
        rows = sorted([r for r in dis if r.get("category") in major and r["rcept_dt"] >= cut], key=lambda r: r["rcept_dt"])[-12:]
        if rows:
            add("\n## 최근 1년 주요 공시 (DART)")
            for r in rows:
                dt = f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}-{r['rcept_dt'][6:]}"
                add(f"- {dt} [{r['category']}] {r['report_nm'].strip()} [사건 연표 · {dt}]")

    # 관련 보도
    news = sorted(rcsv(d / "raw" / "news.csv"), key=lambda r: r.get("pub_dt", ""), reverse=True)[:8]
    if news:
        add("\n## 최근 관련 보도 제목 (네이버 뉴스 · 기사 내용은 확인 전)")
        for n in news:
            add(f"- {n['pub_dt'][:10]} {re.sub(r'<[^>]+>', '', n['title'])} ({n.get('press', '')}) [관련 보도 · {n['pub_dt'][:10]}]")

    # 산업 KPI
    kv = rcsv(d / "manual" / "kpi_values.csv")
    rs = rcsv(d / "research_status.csv")
    if kv or rs:
        add("\n## 산업 KPI (사업보고서 · 원문 대조 상태 표시)")
        for r in sorted(kv, key=lambda r: (r["kpi_key"], r["year"]))[-24:]:
            v = fnum(r["value"])
            if v is None:
                continue
            unit = r.get("unit", "")
            vs = won(v) if unit == "KRW" else f"{v:,.2f}{unit}".replace(".00", "")
            add(f"- {r['item']} ({r['period']}): {vs} · {r['status']} [산업 KPI · {r['period']}]")
        for r in rs:
            if r.get("status") in ("미확인", "미공개"):
                add(f"- {r['label']}: {r['status']} [산업 KPI]")

    # 검색 관심도
    sr = rcsv(d / "search_trend.csv")
    if sr:
        mine = [(r["period"], fnum(r["ratio"])) for r in sr if r.get("is_self") == "Y" and fnum(r["ratio"]) is not None]
        if len(mine) >= 8:
            last4 = sum(v for _, v in mine[-4:]) / 4
            yr = mine[-52:]
            avg = sum(v for _, v in yr) / len(yr)
            add(f"\n## 검색 관심도 (네이버 데이터랩 상대값, 최근 주 {mine[-1][0]})")
            add(f"- 최근 4주 평균 {last4:.1f} / 최근 52주 평균 {avg:.1f} [검색 관심도 · {mine[-1][0]}]")

    return "\n".join(L), meta


# ---------------------------------------------------------------- 프롬프트
def build_prompt(sheet: str, meta: dict, question: str | None) -> str:
    t = PROMPT_FILE.read_text(encoding="utf-8")
    t = t.replace("{{기업명}}", meta["name"]).replace("{{종목코드}}", meta["code"])
    t = t.replace("{{사용자 질문}}", question or "(질문 없음)")
    return t.replace("{{DATA}}", sheet)


# ---------------------------------------------------------------- 검사
NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> list[str]:
    return [m.group(0) for m in NUM.finditer(text)]


def number_pool(sheet: str) -> list[float]:
    out = set()
    for s in numbers_in(sheet):
        v = fnum(s)
        if v is not None:
            out.add(v); out.add(abs(v))
    return sorted(out)


def number_ok(s: str, pool: list[float]) -> bool:
    v = fnum(s)
    if v is None:
        return True
    v = abs(v)
    if v == int(v) and (v <= 12 or 1990 <= v <= 2100):   # 분기·개수·연도
        return True
    dec = len(s.split(".")[1]) if "." in s else 0
    return any(round(p, dec) == round(v, dec) for p in pool)


def validate(out: dict, sheet: str) -> list[str]:
    err = []
    adv = out.get("advisors")
    if not isinstance(adv, list) or len(adv) != 5:
        return ["advisors 가 5명이 아님"]
    roles = [a.get("role") for a in adv]
    if roles != ROLES:
        err.append(f"고문 순서·이름이 다름: {roles}")
    for k in ("topic", "conclusion", "confidence_basis"):
        if not isinstance(out.get(k), str) or not out[k].strip():
            err.append(f"{k} 비어 있음")
    c = out.get("confidence")
    if not isinstance(c, (int, float)) or not 0 <= c <= 100:
        err.append("confidence 가 0~100 숫자가 아님")
    pool = number_pool(sheet)
    texts = [(a.get("role", "?"), a.get("text", "")) for a in adv] + [("결론", out.get("conclusion", "")), ("확신도 근거", out.get("confidence_basis", ""))]
    for who, t in texts:
        bad = [s for s in numbers_in(t) if not number_ok(s, pool)]
        if bad:
            err.append(f"{who}: 데이터 시트에 없는 숫자 {', '.join(bad[:5])}")
    return err


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    return json.loads(t[a:b + 1])


# ---------------------------------------------------------------- 저장
def save_debate(slug: str, month: str, out: dict, sheet: str, meta: dict, author: str) -> Path:
    out["confidence"] = int(round(out["confidence"]))
    out.setdefault("disclaimer", "수업용 경영분석이며 투자 추천이 아닙니다.")
    out["meta"] = {
        "month": month, "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "model": author,
        "data_years": meta.get("years"), "latest_quarter": meta.get("latest_quarter"), "stock_asof": meta.get("stock_asof"),
        "valuation_asof": meta.get("val_asof"), "prompt": "prompts/debate_council.md",
        "check": "형식·고문 5명·확신도 범위·발언 속 숫자가 데이터 시트에 있는지 자동 검사 통과",
        "note": "AI가 작성한 토론입니다. 숫자는 대시보드 데이터에서만 인용하도록 검사했지만 해석은 AI의 의견입니다.",
    }
    ddir = COMPANIES / slug / "data" / "debate"
    ddir.mkdir(parents=True, exist_ok=True)
    f = ddir / f"{month}.json"
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    write_index(ddir)
    return f


def write_index(ddir: Path):
    months = sorted((p.stem for p in ddir.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}", p.stem)), reverse=True)
    (ddir / "index.json").write_text(json.dumps({"months": months}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_all_index()


def write_all_index():
    """companies/debate_index.json — 기업별 토론 월 목록 (화면은 이 파일 하나만 읽어 404 없이 '토론 없음'을 안다)."""
    allm = {}
    for d in sorted(COMPANIES.glob("*/data/debate")):
        ms = sorted((p.stem for p in d.glob("*.json") if re.fullmatch(r"\d{4}-\d{2}", p.stem)), reverse=True)
        if ms:
            allm[d.parent.parent.name] = ms
    (COMPANIES / "debate_index.json").write_text(json.dumps(allm, ensure_ascii=False, indent=1), encoding="utf-8")


def all_slugs() -> list[str]:
    return sorted(p.parent.name for p in COMPANIES.glob("*/company.json"))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--todo", action="store_true", help="이번 달 토론이 없는 기업 목록")
    g.add_argument("--prompt", metavar="SLUG", help="데이터가 채워진 프롬프트 출력")
    g.add_argument("--save", nargs=2, metavar=("SLUG", "JSON"), help="작성한 토론 JSON 검사 후 저장")
    ap.add_argument("--month", default=datetime.now(KST).strftime("%Y-%m"))
    ap.add_argument("--question", default=None)
    ap.add_argument("--author", default="Claude (구독 세션)")
    a = ap.parse_args()
    index = rjson(COMPANIES / "index.json")

    if a.todo:
        todo = [s for s in all_slugs() if not (COMPANIES / s / "data" / "debate" / f"{a.month}.json").exists()
                and (COMPANIES / s / "data" / "financials.csv").exists()]
        print(f"{a.month} 토론이 없는 기업 {len(todo)}곳")
        print(" ".join(todo))
        return

    slug = a.prompt or a.save[0]
    if slug not in all_slugs():
        sys.exit(f"없는 기업: {slug}")
    sheet, meta = fact_sheet(slug, index)
    if not meta.get("years"):
        sys.exit(f"{slug}: 재무 데이터가 없어 토론을 만들 수 없음")

    if a.prompt:
        print(build_prompt(sheet, meta, a.question))
        return

    raw = Path(a.save[1]).read_text(encoding="utf-8")
    try:
        out = parse_json(raw)
    except Exception as e:
        sys.exit(f"검증 실패 — JSON 해석 실패: {e}")
    errs = validate(out, sheet)
    if errs:
        print("검증 실패 — 저장하지 않음")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    f = save_debate(slug, a.month, out, sheet, meta, a.author)
    print(f"저장: {f.relative_to(ROOT)} (확신도 {out['confidence']}%)")


if __name__ == "__main__":
    main()
