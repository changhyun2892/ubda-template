"""
오프라인 테스트용 가짜 DART·Yahoo 서버.

tests/fixtures/의 실제 수집 기록(불닭 대시보드가 2026-11-10 OpenDART에서 받은 값)으로
OpenDART·Yahoo와 같은 모양의 응답을 돌려줍니다. 인터넷 없이 파이프라인 전체를 시험하기 위한 것이며,
실제 데이터의 정확성은 GitHub Actions에서 진짜 API로 다시 확인합니다.
"""
from __future__ import annotations

import csv
import io
import json
import threading
import urllib.parse
import zipfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FX = Path(__file__).resolve().parent / "fixtures"
KST = timezone(timedelta(hours=9))


def _rows(name):
    with (FX / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class Data:
    def __init__(self, stock_code="003230", corp_code="00126283", corp_name="삼양식품", no_cfs=False):
        self.stock_code, self.corp_code, self.corp_name, self.no_cfs = stock_code, corp_code, corp_name, no_cfs
        self.reports = _rows("dart_reports.csv")
        self.items = defaultdict(list)  # (year, reprt) -> DART list 항목
        for r in _rows("dart_auto_financials.csv"):
            if not r["account_id"]:
                continue
            self.items[(r["bsns_year"], r["reprt_code"])].append({
                "rcept_no": r["rcept_no"], "sj_div": r["sj_div"], "account_id": r["account_id"], "account_nm": r["account_nm"],
                "thstrm_amount": r["value"], "thstrm_add_amount": r["value_cumulative"] if r["reprt_code"] in ("11012", "11014") else ""})
        for r in _rows("extra_annual_accounts.csv"):
            k = (r["bsns_year"], "11011")
            rc = self.items[k][0]["rcept_no"] if self.items[k] else ""
            self.items[k].append({"rcept_no": rc, "sj_div": r["sj_div"], "account_id": r["account_id"], "account_nm": r["account_nm"],
                                  "thstrm_amount": r["value"], "thstrm_add_amount": ""})
        self.stock = _rows("stock_daily.csv")
        self.extra = []  # 정기보고서 외 공시 (사건 수집 테스트용, pblntf_ty 없이 요청할 때만)
        self.news = []  # 네이버 뉴스 검색 결과 (테스트에서 채움)
        self.extra = []  # 정기보고서 외 공시 (사건 수집 테스트용, pblntf_ty 없이 요청할 때만)
        self.calls = defaultdict(int)


def make_handler(d: Data):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 조용히
            pass

        def _json(self, obj, code=200):
            b = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            d.calls[u.path] += 1
            if u.path.startswith("/api/") and p.get("crtfc_key") != "TESTKEY":
                return self._json({"status": "010", "message": "등록되지 않은 키입니다."})
            if u.path == "/api/corpCode.xml":
                xml = (f"<result><list><corp_code>00000001</corp_code><corp_name>다른회사</corp_name><stock_code>999999</stock_code></list>"
                       f"<list><corp_code>{d.corp_code}</corp_code><corp_name>{d.corp_name}</corp_name><stock_code>{d.stock_code}</stock_code></list></result>")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr("CORPCODE.xml", xml)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(buf.getvalue())
                return
            if u.path == "/api/list.json":
                lst = [{"rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"], "report_nm": r["report_nm"], "corp_name": d.corp_name}
                       for r in d.reports if p["bgn_de"] <= r["rcept_dt"] <= p["end_de"]]
                lst.append({"rcept_no": "20240101000001", "rcept_dt": "20240101", "report_nm": "주요사항보고서(자기주식취득결정)"})  # 정기보고서 아님 → 무시되어야 함
                if "pblntf_ty" not in p:
                    lst += [r for r in d.extra if p["bgn_de"] <= r["rcept_dt"] <= p["end_de"]]
                if "pblntf_ty" not in p:
                    lst += [r for r in d.extra if p["bgn_de"] <= r["rcept_dt"] <= p["end_de"]]
                return self._json({"status": "000", "total_page": 1, "list": lst})
            if u.path == "/api/fnlttSinglAcntAll.json":
                if d.no_cfs and p["fs_div"] == "CFS":
                    return self._json({"status": "013", "message": "조회된 데이타가 없습니다."})
                if not d.no_cfs and p["fs_div"] == "OFS":
                    return self._json({"status": "013", "message": "조회된 데이타가 없습니다."})
                its = d.items.get((p["bsns_year"], p["reprt_code"]), [])
                return self._json({"status": "000", "list": its} if its else {"status": "013", "message": "조회된 데이타가 없습니다."})
            if u.path == "/api/document.xml":
                xml = ("<DOCUMENT><BODY><SECTION-1><TITLE ATOC=\"Y\">I. 회사의 개요</TITLE><P>개요</P></SECTION-1>"
                       "<SECTION-1><TITLE ATOC=\"Y\">II. 사업의 내용</TITLE><SECTION-2><TITLE ATOC=\"Y\">4. 매출 및 수주상황</TITLE>"
                       "<P>(단위 : 백만원)</P><TABLE><TR><TH>구분</TH><TH>제71기</TH></TR><TR><TD>면스낵 수출</TD><TD>1,234</TD></TR></TABLE></SECTION-2></SECTION-1>"
                       "<SECTION-1><TITLE ATOC=\"Y\">III. 재무에 관한 사항</TITLE><P>재무</P></SECTION-1></BODY></DOCUMENT>")
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr(f"{p['rcept_no']}.xml", xml.encode("utf-8"))
                    z.writestr(f"{p['rcept_no']}_00760.xml", "<DOCUMENT>감사보고서</DOCUMENT>".encode("utf-8"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(buf.getvalue())
                return
            if u.path == "/search/v1/news":
                if self.headers.get("X-NCP-APIGW-API-KEY-ID") != "NID" or self.headers.get("X-NCP-APIGW-API-KEY") != "NSECRET":
                    return self._json({"error": {"errorCode": "200", "message": "Authentication Failed"}}, 401)
                st, n = int(p.get("start", 1)), int(p.get("display", 10))
                return self._json({"total": len(d.news), "start": st, "display": n, "items": d.news[st - 1:st - 1 + n]})
            if u.path.startswith("/v8/finance/chart/"):
                sym = urllib.parse.unquote(u.path.rsplit("/", 1)[1])
                ts, cl, vol = [], [], []
                for r in d.stock:
                    t = datetime.strptime(r["date"], "%Y-%m-%d").replace(hour=9, tzinfo=KST)
                    ts.append(int(t.timestamp()))
                    cl.append(float(r["kospi"]) if sym == "^KS11" and r["kospi"] else (None if sym == "^KS11" else float(r["close"])))
                    vol.append(int(r["volume"]) if r["volume"] else None)
                return self._json({"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": cl, "volume": vol}]}}]}})
            self._json({"error": "not found"}, 404)
        def do_POST(self):  # noqa: N802
            u = urllib.parse.urlparse(self.path)
            d.calls[u.path] += 1
            if self.headers.get("X-NCP-APIGW-API-KEY-ID") != "NID":
                return self._json({"error": {"errorCode": "200", "message": "Authentication Failed"}}, 401)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            if u.path == "/search-trend/v1/search":
                d.last_trend = body
                res = [{"title": g["groupName"], "keywords": g["keywords"], "data": [{"period": "2025-01-06", "ratio": 100 - 10 * i}, {"period": "2025-01-13", "ratio": 50.5 - i}]}
                       for i, g in enumerate(body["keywordGroups"])]
                return self._json({"startDate": body["startDate"], "endDate": body["endDate"], "timeUnit": body["timeUnit"], "results": res})
            self._json({"error": "not found"}, 404)
    return H


def start(d: Data) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
