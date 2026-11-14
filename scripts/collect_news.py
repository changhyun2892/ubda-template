#!/usr/bin/env python3
"""
네이버 뉴스 검색 (NAVER API HUB) → data/raw/news.csv (누적)

    python scripts/collect_news.py --company samyang

- 회사 이름으로 최신순 검색. 검색 API는 날짜 지정이 안 되고 최근 1,000건까지만 볼 수 있어,
  매일 실행하며 새 기사를 쌓아 간다 (처음 실행은 최대 1,000건, 이후에는 이미 받은 기사가 나오면 멈춤).
- 제목에 회사 이름이 들어간 기사만 남긴다 (이름만 스친 기사 제외).
- 저장: 날짜·제목·링크만. 기사 본문·요약은 저장하지 않는다.
- collect_events.py가 이 파일을 읽어 급변일 전날~당일 기사를 '보도 후보 · 확인 전'으로 붙인다.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from naver_api import NaverError, call, keys  # noqa: E402
from ubda_common import DATA, KST, load_config, now_kst, read_csv, write_csv, write_log  # noqa: E402

OUT = DATA / "raw" / "news.csv"
COLS = ["pub_dt", "title", "press", "link", "originallink"]


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def main() -> int:
    cfg = load_config()
    now = now_kst()
    if not keys():
        print("[건너뜀] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음 — 뉴스 수집 안 함")
        write_log("news", {"status": "건너뜀", "checked_at": now, "message": "네이버 API 키 없음"})
        return 0
    name = cfg["name"]
    old = read_csv(OUT) if OUT.exists() else []
    seen = {r["link"] for r in old}
    new, err, pages = [], "", 0
    for start in range(1, 1001, 100):
        try:
            js = call("/search/v1/news", params={"query": name, "display": 100, "start": start, "sort": "date"})
        except NaverError as e:
            err = str(e)
            break
        pages += 1
        items = js.get("items", [])
        dup = 0
        for it in items:
            link = it.get("link") or it.get("originallink") or ""
            if not link or link in seen:
                dup += 1
                continue
            title = clean(it.get("title", ""))
            if name.replace(" ", "") not in title.replace(" ", ""):
                continue
            try:
                dt = parsedate_to_datetime(it.get("pubDate", "")).astimezone(KST).strftime("%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                continue
            seen.add(link)
            host = urlparse(it.get("originallink") or link).netloc.replace("www.", "")
            new.append({"pub_dt": dt, "title": title, "press": host, "link": link, "originallink": it.get("originallink", "")})
        if len(items) < 100 or (old and dup >= 50):  # 끝까지 봤거나, 이미 받은 기사 구간에 들어옴
            break
        if start + 100 > int(js.get("total", 0) or 0):
            break
    rows = sorted(old + new, key=lambda r: r["pub_dt"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_csv(OUT, COLS, rows)
    info = {"status": "성공" if not err else ("부분 성공" if new or old else "실패"), "checked_at": now, "new": len(new), "total": len(rows),
            "first": rows[0]["pub_dt"] if rows else "", "pages": pages, "source": "NAVER API HUB 뉴스 검색 (제목에 회사명 포함 기사만)"}
    if err:
        info["message"] = err
    write_log("news", info)
    print(f"뉴스 새로 {len(new)}건 · 누적 {len(rows)}건 ({info['first'][:10]}~)" + (f" · {err}" if err else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
