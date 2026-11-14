#!/usr/bin/env python3
"""
네이버 검색어 트렌드 (NAVER API HUB) → data/search_trend.csv

    python scripts/collect_search.py --company samyang

- 이 기업과 비교 기업(company.json competitors, 최대 4곳)을 한 번에 요청해 같은 기준(가장 큰 값 = 100)의 상대 비율로 받는다.
- 검색어: 회사 이름 + company.json의 search_keywords(있으면, 예: 대표 브랜드). 비교 기업은 회사 이름만.
- 주 단위, start_year 1월부터 오늘까지. 비율은 매번 다시 계산되므로 매 실행 전체를 다시 받는다 (기업당 하루 1회 호출).
- 값은 검색 '횟수'가 아니라 상대 비율이다. 회사 이름 검색에는 주가·제품·채용 등 여러 관심이 섞인다.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naver_api import NaverError, call, keys  # noqa: E402
from ubda_common import DATA, KST, load_config, now_kst, write_csv, write_log  # noqa: E402

OUT = DATA / "search_trend.csv"


def main() -> int:
    cfg = load_config()
    now = now_kst()
    if not keys():
        print("[건너뜀] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음 — 검색 관심도 수집 안 함")
        write_log("search", {"status": "건너뜀", "checked_at": now, "message": "네이버 API 키 없음"})
        return 0
    own = [cfg["name"]] + [k for k in cfg.get("search_keywords", []) if k != cfg["name"]]
    groups = [{"groupName": cfg["name"], "keywords": own[:20]}]
    for c in cfg.get("competitors", [])[:4]:
        name = c.get("name") if isinstance(c, dict) else c
        if name and name != cfg["name"]:
            groups.append({"groupName": name, "keywords": [name]})
    body = {"startDate": f"{int(cfg['start_year'])}-01-01", "endDate": datetime.now(KST).strftime("%Y-%m-%d"), "timeUnit": "week", "keywordGroups": groups}
    try:
        js = call("/search-trend/v1/search", body=body)
    except NaverError as e:
        print(f"[경고] 검색어 트렌드 수집 실패: {e} — 기존 파일 유지", file=sys.stderr)
        write_log("search", {"status": "실패", "checked_at": now, "message": str(e)})
        return 0
    rows = []
    for res in js.get("results", []):
        for d in res.get("data", []):
            rows.append({"period": d["period"], "group": res["title"], "is_self": "Y" if res["title"] == cfg["name"] else "",
                         "ratio": d["ratio"], "keywords": " · ".join(res.get("keywords", []))})
    rows.sort(key=lambda r: (r["period"], r["is_self"] != "Y", r["group"]))
    write_csv(OUT, ["period", "group", "is_self", "ratio", "keywords"], rows)
    last = max((r["period"] for r in rows), default="")
    write_log("search", {"status": "성공", "checked_at": now, "rows": len(rows), "groups": [g["groupName"] for g in groups], "last_period": last,
                         "source": "NAVER API HUB 검색어 트렌드 (주 단위, 상대 비율)"})
    print(f"검색 관심도 {len(rows)}행 · {len(groups)}개 검색어 묶음 · 마지막 주 {last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
