#!/usr/bin/env python3
"""
기업 목록 만들기 → companies/index.json

    python scripts/build_index.py

첫 화면(기업 목록)과 앞으로 만들 3D 뉴런 포털이 읽는 파일입니다.
기업 폴더를 추가하고 이 스크립트를 실행하면 목록·그래프에 자동으로 나타납니다.

graph 구조:  CORE → 산업 → 카테고리 → 기업
 - 기업이 카테고리 여러 개에 속하면 기업 노드는 1개, 연결선만 여러 개 (기업 정보 중복 저장 안 함)
 - 카테고리 id는 '산업:카테고리' (같은 이름이 다른 산업에 있어도 섞이지 않게)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))


def main() -> int:
    industries = {}
    for p in sorted((ROOT / "industries").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        industries[d["id"]] = {"name": d.get("name", d["id"]), "color": d.get("color", "#888")}

    companies = []
    for p in sorted((ROOT / "companies").glob("*/company.json")):
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if cfg.get("enabled", True) is False:
            continue
        slug = p.parent.name
        sp = p.parent / "data" / "summary.json"
        sm = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        companies.append({
            "slug": slug, "company_id": cfg["company_id"], "name": cfg["name"], "name_en": cfg.get("name_en", ""),
            "stock_code": cfg.get("stock_code", ""), "industry": cfg["industry"], "categories": cfg.get("categories", []),
            "competitors": cfg.get("competitors", []), "theme_color": cfg.get("theme_color", ""),
            "dashboard_path": f"dashboard.html?c={slug}", "has_data": bool(sm.get("latest_year")),
            "latest_year": sm.get("latest_year"), "kpis": sm.get("kpis"), "verification": sm.get("verification"),
            "industry_kpis_found": sm.get("industry_kpis_found"), "industry_kpis_total": sm.get("industry_kpis_total"),
            "updated_at": sm.get("updated_at", ""),
        })

    nodes = [{"id": "core", "type": "core", "label": "경영분석 CORE"}]
    links, seen = [], set()
    for c in companies:
        ind = c["industry"]
        if ("ind", ind) not in seen:
            seen.add(("ind", ind))
            nodes.append({"id": f"ind:{ind}", "type": "industry", "label": industries.get(ind, {}).get("name", ind), "color": industries.get(ind, {}).get("color")})
            links.append({"source": "core", "target": f"ind:{ind}"})
        nodes.append({"id": f"co:{c['slug']}", "type": "company", "label": c["name"], "slug": c["slug"], "url": c["dashboard_path"]})
        for cat in c["categories"] or ["기타"]:
            cid = f"cat:{ind}:{cat}"
            if ("cat", cid) not in seen:
                seen.add(("cat", cid))
                nodes.append({"id": cid, "type": "category", "label": cat, "industry": ind})
                links.append({"source": f"ind:{ind}", "target": cid})
            links.append({"source": cid, "target": f"co:{c['slug']}"})

    out = {"updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "industries": industries, "companies": companies,
           "graph": {"nodes": nodes, "links": links}}
    (ROOT / "companies" / "index.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"기업 목록: {len(companies)}개 · 그래프 노드 {len(nodes)} · 연결 {len(links)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
