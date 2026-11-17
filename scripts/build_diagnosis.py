#!/usr/bin/env python3
"""
종합 진단 (규칙 기반) → companies/diagnosis.json

    python scripts/build_diagnosis.py

모든 기업을 한 번에 계산한다 (같은 산업 안 순위가 필요해서). 자동 업데이트의 마지막 단계(index 작업)에서 실행. 결과는 companies/<slug>/data/diagnosis.json

1) 5개 축 = 같은 산업 기업 사이의 백분위(0~100, 50 = 산업 가운데). 축 = 그 축 지표들의 백분위 평균.
   성장성: 매출(은행은 순이자이익)·영업이익 증가율 / 수익성: 영업이익률·ROE (은행 ROE·ROA)
   안정성: 부채비율(낮을수록)·유동비율 (은행 자기자본비율·대손비용률 낮을수록)
   효율성: 총자산회전율 (은행 CIR 낮을수록) / 가격 매력: PER·PBR 낮을수록 (적자로 PER이 없으면 PBR만)
2) 투자 성향 3가지 — 아래 WEIGHTS는 UBDA가 임의로 정한 기준이다(학술·업계 표준 아님). 성향 부합도 = 요인 백분위의 가중평균.
3) 한 줄 코멘트 = 그 성향의 요인 중 가장 좋은 것과 가장 약한 것을 숫자와 함께. 원인·전망은 쓰지 않는다.

투자 권유가 아니라 공시 숫자를 성향별 관점으로 정리한 것이다.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 요인: (라벨, 높을수록 좋음?, 표시 형식)
FACTORS = {
    "rev_growth": ("매출 증가율", True, "pct"), "op_growth": ("영업이익 증가율", True, "pct"), "op_margin": ("영업이익률", True, "pct"),
    "roe": ("ROE", True, "pct"), "roa": ("ROA", True, "pct"), "debt_ratio": ("부채비율", False, "pct0"), "current_ratio": ("유동비율", True, "pct0"),
    "equity_ratio": ("자기자본비율", True, "pct"), "credit_cost": ("대손비용률", False, "pct2"), "asset_turnover": ("총자산회전율", True, "turn"),
    "cir": ("CIR(영업이익경비율)", False, "pct"), "per": ("PER", False, "x1"), "pbr": ("PBR", False, "x2"), "div_yield": ("배당수익률", True, "pct2"),
    "vol_1y": ("주가 변동성(연환산)", False, "pct"), "mdd_1y": ("1년 최대 낙폭", True, "pct"), "ret_1y": ("1년 시장 대비 수익률", True, "pctp"),
}
AXES = {  # 일반 기업 / 은행
    "growth": ("성장성", ["rev_growth", "op_growth"], ["rev_growth", "op_growth"]),
    "profit": ("수익성", ["op_margin", "roe"], ["roe", "roa"]),
    "stable": ("안정성", ["debt_ratio", "current_ratio"], ["equity_ratio", "credit_cost"]),
    "efficiency": ("효율성", ["asset_turnover"], ["cir"]),
    "value": ("가격 매력", ["per", "pbr"], ["per", "pbr"]),
}
# 성향별 가중치 (합 1). 은행은 같은 이름의 축 값이 은행 지표로 계산됨.
WEIGHTS = {
    "stable": ("안정형", {"axis:stable": 0.35, "div_yield": 0.25, "vol_1y": 0.25, "axis:profit": 0.15}),
    "neutral": ("위험중립형", {"axis:profit": 0.30, "axis:value": 0.30, "axis:growth": 0.20, "axis:stable": 0.20}),
    "active": ("적극투자형", {"axis:growth": 0.40, "ret_1y": 0.30, "axis:profit": 0.20, "axis:efficiency": 0.10}),
}
FOCUS = {"stable": "재무 안정·배당·주가 변동", "neutral": "수익성과 가격의 균형", "active": "성장과 주가 흐름"}


def f(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def rows(p: Path) -> list[dict]:
    return list(csv.DictReader(p.open(encoding="utf-8-sig"))) if p.exists() else []


def fmt(v, kind):
    if v is None:
        return "–"
    if kind == "pct0":
        return f"{v:,.0f}%"
    if kind == "pct2":
        return f"{v:.2f}%"
    if kind == "pctp":
        return f"{v:+.1f}%p"
    if kind == "x1":
        return f"{v:.1f}배"
    if kind == "x2":
        return f"{v:.2f}배"
    if kind == "turn":
        return f"{v:.2f}회"
    return f"{v:.1f}%"


def stock_stats(sd: list[dict]):
    pts = [(r["date"], f(r.get("adj_close")) or f(r["close"]), f(r.get("index_close"))) for r in sd]
    pts = [p for p in pts if p[1]]
    if len(pts) < 120:
        return {}
    last = pts[-1][0]
    cut = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    yr = [p for p in pts if p[0] >= cut]
    rets = [(b[1] / a[1] - 1) for a, b in zip(yr, yr[1:])]
    vol = statistics.pstdev(rets) * math.sqrt(250) * 100 if len(rets) > 20 else None
    peak, mdd = yr[0][1], 0.0
    for _, c, _ in yr:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    r1 = yr[-1][1] / yr[0][1] - 1
    i0, i1 = yr[0][2], yr[-1][2]
    ex = (r1 - (i1 / i0 - 1)) * 100 if i0 and i1 else None
    return {"vol_1y": vol, "mdd_1y": mdd * 100, "ret_1y": ex, "stock_asof": last}


def pctile(v, peers, higher):
    """같은 산업 안 백분위 (0 = 가장 나쁨, 100 = 가장 좋음). 비교 대상이 자기 포함 2곳 미만이면 None"""
    vals = [p for p in peers if p is not None]
    if v is None or len(vals) < 2:
        return None, None, len(vals)
    better = sum(1 for p in vals if (p > v if higher else p < v))
    same = sum(1 for p in vals if p == v) - 1
    worse = len(vals) - 1 - better - same
    return round((worse + same / 2) / (len(vals) - 1) * 100), better + 1, len(vals)


def main() -> int:
    idx = json.loads((ROOT / "companies" / "index.json").read_text(encoding="utf-8"))
    ind_name = {k: v["name"] for k, v in idx["industries"].items()}
    raw = {}
    for c in idx["companies"]:
        if not c.get("has_data"):
            continue
        d = ROOT / "companies" / c["slug"] / "data"
        y = str(c["latest_year"])
        met = {r["metric"]: f(r["value"]) for r in rows(d / "metrics.csv") if r["year"] == y}
        bank = c["industry"] == "bank"
        v = json.loads((d / "valuation.json").read_text(encoding="utf-8")) if (d / "valuation.json").exists() else {}
        x = {
            "rev_growth": met.get("nii_growth_pct" if bank else "revenue_growth_pct"), "op_growth": met.get("op_growth_pct"),
            "op_margin": met.get("operating_margin_pct"), "roe": met.get("roe_pct"), "roa": met.get("roa_pct"),
            "debt_ratio": met.get("debt_ratio_pct"), "current_ratio": met.get("current_ratio_pct"), "equity_ratio": met.get("equity_ratio_pct"),
            "credit_cost": met.get("credit_cost_pct"), "asset_turnover": met.get("asset_turnover"), "cir": met.get("cir_pct"),
            "per": f(v.get("per")), "pbr": f(v.get("pbr")), "div_yield": f(v.get("div_yield_pct")) if v else None,
        }
        if v and x["div_yield"] is None and v.get("dps") in (0, 0.0, None) and v.get("inputs", {}).get("dps_year"):
            x["div_yield"] = 0.0  # 사업보고서상 무배당
        x.update(stock_stats(rows(d / "stock_daily.csv")))
        ni = v.get("inputs", {}).get("ttm_net_income") if v else None
        raw[c["slug"]] = {"c": c, "x": x, "year": y, "bank": bank, "loss": ni is not None and ni <= 0, "ev": len(rows(d / "events_auto.csv"))}

    out = {}
    for slug, r in raw.items():
        peers = [p for p in raw.values() if p["c"]["industry"] == r["c"]["industry"]]
        fac = {}
        for k, (label, higher, kind) in FACTORS.items():
            p, rank, n = pctile(r["x"].get(k), [q["x"].get(k) for q in peers], higher)
            fac[k] = {"label": label, "value": r["x"].get(k), "text": fmt(r["x"].get(k), kind),
                      "pctile": p, "rank": rank, "n": n, "higher_better": higher}
        axes = {}
        for a, (label, gen, bank) in AXES.items():
            keys = bank if r["bank"] else gen
            ps = [fac[k]["pctile"] for k in keys if fac[k]["pctile"] is not None]
            axes[a] = {"label": label, "score": round(sum(ps) / len(ps)) if ps else None, "factors": keys}
        prof = {}
        for pk, (plabel, w) in WEIGHTS.items():
            parts, tot, used = [], 0.0, 0.0
            for key, wt in w.items():
                ks = axes[key[5:]]["factors"] if key.startswith("axis:") else [key]
                ks = [k for k in ks if fac[k]["pctile"] is not None]
                s = axes[key[5:]]["score"] if key.startswith("axis:") else (fac[key]["pctile"] if ks else None)
                lbl = AXES[key[5:]][0] if key.startswith("axis:") else fac[key]["label"]
                parts.append({"key": key, "label": lbl, "weight": wt, "score": s,
                              "best": max(ks, key=lambda k: fac[k]["pctile"]) if ks else None, "worst": min(ks, key=lambda k: fac[k]["pctile"]) if ks else None})
                if s is not None:
                    tot += s * wt
                    used += wt
            score = round(tot / used) if used >= 0.5 else None

            def say(k):
                fx = fac[k]
                return f"{fx['label']} {fx['text']}(업종 {fx['n']}곳 중 {fx['rank']}위)"
            wt = {}
            for p in parts:
                for k in (p["best"], p["worst"]):
                    if k:
                        wt[k] = max(wt.get(k, 0), p["weight"])
            goods = sorted({p["best"] for p in parts if p["best"] and fac[p["best"]]["pctile"] >= 60}, key=lambda k: -fac[k]["pctile"] * (0.5 + wt[k]))  # 가중치 큰 요인 우선
            bads = sorted({p["worst"] for p in parts if p["worst"] and fac[p["worst"]]["pctile"] <= 40}, key=lambda k: fac[k]["pctile"])
            if score is None:
                comment = "비교할 같은 산업 기업이나 지표가 부족해 판단 근거가 없음"
            elif goods and bads:
                comment = f"{say(goods[0])}는 강점, {say(bads[0])}는 확인할 지점"
                if "부채비율" in comment and (r["x"].get("debt_ratio") or 0) > 200 and not r["bank"]:
                    comment = comment.replace("는 확인할 지점", "로 200%를 넘어 확인할 지점")
            elif goods:
                comment = f"{say(goods[0])} 등 이 성향이 보는 지표가 업종 중간 이상"
            elif bads:
                comment = f"강점으로 꼽을 지표가 없고 {say(bads[0])}가 가장 약함"
            else:
                comment = "이 성향이 보는 지표가 모두 업종 중간권"
            if pk == "stable" and r["loss"]:
                comment += " · 최근 4분기 적자"
            if pk == "stable" and (r["x"].get("debt_ratio") or 0) > 200 and not r["bank"] and "부채비율" not in comment:
                comment += f" · 부채비율 {fac['debt_ratio']['text']}로 200% 초과"
            if pk == "active" and r["ev"] >= 30:
                comment += f" · 2023년 이후 주가 급변일 {r['ev']}일"
            prof[pk] = {"label": plabel, "focus": FOCUS[pk], "score": score, "level": None if score is None else ("높음" if score >= 65 else "보통" if score >= 35 else "낮음"),
                        "comment": comment, "parts": parts}
        out[slug] = {"year": r["year"], "industry": ind_name.get(r["c"]["industry"], r["c"]["industry"]), "peers": len(peers), "bank": r["bank"],
                     "axes": axes, "profiles": prof, "factors": fac, "stock_asof": r["x"].get("stock_asof")}
    meta = {"built_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "method": "같은 산업 기업 사이 백분위(0~100, 50 = 가운데) · 성향별 가중치는 UBDA가 임의로 정한 기준 · 투자 권유 아님",
            "weights": {k: {"label": v[0], "weights": v[1]} for k, v in WEIGHTS.items()}}
    for slug, v in out.items():  # 대시보드는 자기 기업 파일만 읽음
        (ROOT / "companies" / slug / "data" / "diagnosis.json").write_text(json.dumps({**meta, **v}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"종합 진단 {len(out)}개 기업")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
