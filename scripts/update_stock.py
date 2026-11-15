#!/usr/bin/env python3
"""
주가 수집 → data/stock_daily.csv

    python scripts/update_stock.py

 - 종목: company.json의 yahoo_ticker (예: 003230.KS = 코스피, 숫자.KQ = 코스닥), 비교 지수: market_index (기본 ^KS11 코스피)
 - 출처: Yahoo Finance 일봉 (비공식 무료 경로 — 바뀌거나 막힐 수 있어 실패해도 기존 파일을 유지). DART는 주가를 제공하지 않습니다.
 - close = Yahoo 일봉 종가 (액면분할은 과거까지 반영, 배당은 미반영), adj_close = 배당·분할을 모두 반영한 수정주가 (수익률·급변일 계산용),
   raw_close = 그날 실제 거래된 가격 (분할 이전 날짜는 분할 비율을 되돌림 — 시가총액·PER 계산용)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
        url = f"{host}/v8/finance/chart/{urllib.parse.quote(ticker)}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ubda dashboard data updater)"})
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    return json.load(r)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2)
    raise RuntimeError(f"주가 요청 실패: {last}")


def parse(js: dict) -> dict[str, dict]:
    res = js["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = ((res["indicators"].get("adjclose") or [{}])[0] or {}).get("adjclose") or []
    splits = []  # (날짜, 비율) — 5:1 분할이면 비율 5
    for sp in ((res.get("events") or {}).get("splits") or {}).values():
        try:
            ratio = float(sp["numerator"]) / float(sp["denominator"])
            if ratio > 0 and ratio != 1:
                splits.append((datetime.fromtimestamp(int(sp["date"]), KST).strftime("%Y-%m-%d"), ratio))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    out = {}
    for i, t in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None:  # 거래정지·휴장
            continue
        d = datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d")
        a = adj[i] if i < len(adj) and adj[i] is not None else c
        back = 1.0
        for sd, ratio in splits:  # 이 날짜보다 뒤에 있었던 분할을 되돌려 실제 거래 가격으로
            if sd > d:
                back *= ratio
        out[d] = {"date": d, "close": round(c, 2), "adj_close": round(a, 2), "raw_close": round(c * back, 2), "splits": len(splits),
                  "volume": q["volume"][i] if q["volume"][i] is not None else ""}
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
            # 같은 실행 안에서는 시장지수를 한 번만 받음 (기업마다 반복 요청하지 않게)
            cache = os.path.join(tempfile.gettempdir(), f"ubda_index_{index.strip('^')}_{cfg['start_year']}_{time.strftime('%Y%m%d%H')}.json")
            if os.path.exists(cache):
                idx = json.load(open(cache, encoding="utf-8"))
            else:
                idx = parse(fetch(index, int(cfg["start_year"])))
                json.dump(idx, open(cache, "w", encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — 지수는 실패해도 주가는 저장
            print(f"[경고] 지수 수집 실패: {e}", file=sys.stderr)
            idx = {}
    except Exception as e:  # noqa: BLE001
        print(f"[경고] {e} — 기존 stock_daily.csv를 유지합니다.", file=sys.stderr)
        write_log("stock", {"status": "실패", "checked_at": now, "message": str(e)[:200]})
        return 0
    src = f"Yahoo Finance {ticker} 일봉 (분할 반영 종가)"
    out = []
    for d in sorted(rows):
        r = rows[d]
        k = idx.get(d)
        out.append({"date": d, "close": round(r["close"]), "volume": r["volume"], "index_close": "" if k is None else k["close"], "source": src,
                    "adj_close": r["adj_close"], "raw_close": round(r["raw_close"])})
    write_csv(OUT, ["date", "close", "volume", "index_close", "source", "adj_close", "raw_close"], out)
    write_log("stock", {"status": "성공", "checked_at": now, "rows": len(out), "last_date": out[-1]["date"], "last_close": out[-1]["close"], "source": src, "index": index})
    print(f"주가 {len(out)}행 저장 · 마지막 {out[-1]['date']} 종가 {out[-1]['close']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
