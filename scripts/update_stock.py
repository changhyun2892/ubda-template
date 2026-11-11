#!/usr/bin/env python3
"""
주가 수집 → data/stock_daily.csv

    python scripts/update_stock.py

 - 종목: company.json의 yahoo_ticker (예: 003230.KS = 코스피, 숫자.KQ = 코스닥), 비교 지수: market_index (기본 ^KS11 코스피)
 - 출처: Yahoo Finance 일봉 (비공식 무료 경로 — 바뀌거나 막힐 수 있어 실패해도 기존 파일을 유지). DART는 주가를 제공하지 않습니다.
 - 수정주가가 아닌 일반 종가입니다. 액면분할이 있는 기업은 화면 해석에 주의.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ubda_common import DATA, KST, load_config, now_kst, write_csv, write_log

OUT = DATA / "stock_daily.csv"
HOSTS = [h for h in os.environ.get("YAHOO_HOSTS", "https://query1.finance.yahoo.com,https://query2.finance.yahoo.com").split(",") if h]


def fetch(ticker: str, start_year: int) -> dict:
    p1 = int(datetime(start_year, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(time.time()) + 86400
    last = None
    for host in HOSTS:
        url = f"{host}/v8/finance/chart/{urllib.parse.quote(ticker)}?period1={p1}&period2={p2}&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ubda dashboard data updater)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"주가 요청 실패: {last}")


def parse(js: dict) -> dict[str, dict]:
    res = js["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = {}
    for i, t in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None:  # 거래정지·휴장
            continue
        d = datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d")
        out[d] = {"date": d, "close": round(c, 2), "volume": q["volume"][i] if q["volume"][i] is not None else ""}
    return out


def main() -> int:
    cfg = load_config()
    ticker, index = cfg.get("yahoo_ticker"), cfg.get("market_index") or "^KS11"
    now = now_kst()
    if not ticker:
        write_log("stock", {"status": "건너뜀", "checked_at": now, "message": "company.json에 yahoo_ticker 없음"})
        print("[안내] yahoo_ticker가 없어 주가 수집을 건너뜁니다.")
        return 0
    try:
        rows = parse(fetch(ticker, int(cfg["start_year"])))
        if len(rows) < 20:
            raise RuntimeError(f"받은 행이 너무 적음 ({len(rows)}행) — 티커가 맞는지 확인")
        try:
            idx = parse(fetch(index, int(cfg["start_year"])))
        except Exception as e:  # noqa: BLE001 — 지수는 실패해도 주가는 저장
            print(f"[경고] 지수 수집 실패: {e}", file=sys.stderr)
            idx = {}
    except Exception as e:  # noqa: BLE001
        print(f"[경고] {e} — 기존 stock_daily.csv를 유지합니다.", file=sys.stderr)
        write_log("stock", {"status": "실패", "checked_at": now, "message": str(e)[:200]})
        return 0
    src = f"Yahoo Finance {ticker} 일봉 (비수정 종가)"
    out = []
    for d in sorted(rows):
        r = rows[d]
        k = idx.get(d)
        out.append({"date": d, "close": round(r["close"]), "volume": r["volume"], "index_close": "" if k is None else k["close"], "source": src})
    write_csv(OUT, ["date", "close", "volume", "index_close", "source"], out)
    write_log("stock", {"status": "성공", "checked_at": now, "rows": len(out), "last_date": out[-1]["date"], "last_close": out[-1]["close"], "source": src, "index": index})
    print(f"주가 {len(out)}행 저장 · 마지막 {out[-1]['date']} 종가 {out[-1]['close']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
