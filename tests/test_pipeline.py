#!/usr/bin/env python3
"""
파이프라인 오프라인 테스트 — 인터넷 없이 가짜 DART·Yahoo 서버로 전체 흐름을 시험합니다.

    python tests/test_pipeline.py

저장소 파일은 건드리지 않고 임시 폴더에 복사해서 실행합니다.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import mock_server  # noqa: E402

passed, failed = [], []


def ok(name, cond, detail=""):
    (passed if cond else failed).append(name)
    print(("  ✔ " if cond else "  ✘ ") + name + (f" — {detail}" if detail else ""))


SLUG = "t"  # 테스트용 기업 폴더 이름


def workdir(company: dict | None = None) -> Path:
    d = Path(tempfile.mkdtemp(prefix="ubda_test_"))
    for n in ("scripts", "industries"):
        shutil.copytree(REPO / n, d / n)
    c = d / "companies" / SLUG
    c.mkdir(parents=True)
    # 저장소의 실제 기업 설정과 무관하게, 테스트는 항상 픽스처(삼양식품) 설정으로 실행
    cfg = {"company_id": "SY", "name": "삼양식품", "stock_code": "003230", "yahoo_ticker": "003230.KS", "market_index": "^KS11",
           "fs_div": "auto", "start_year": 2023, "industry": "food", "categories": ["라면"], "competitors": []}
    cfg.update(company or {})
    (c / "company.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    shutil.copy(HERE / "fixtures" / "expectations_sy.json", c / "verify_expectations.json")
    return d


def run(d: Path, script: str, base: str, key="TESTKEY", naver=None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DART_BASE_URL": base + "/api", "YAHOO_HOSTS": base, "DART_API_KEY": key, "NAVER_API_BASE": base,
           "NAVER_CLIENT_ID": (naver or ("", ""))[0], "NAVER_CLIENT_SECRET": (naver or ("", ""))[1],
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    env.pop("UBDA_COMPANY", None)
    return subprocess.run([sys.executable, str(d / "scripts" / script), "--company", SLUG], env=env, capture_output=True, text=True, cwd=d, timeout=120)


def rows(p: Path):
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    data = mock_server.Data()
    srv, base = mock_server.start(data)

    print("\n[1] 삼양식품 전체 실행 (수집 → 주가 → 계산 → 검증)")
    d = workdir()
    for s in ("collect_dart.py", "update_stock.py", "build_dataset.py"):
        r = run(d, s, base)
        ok(f"{s} 정상 종료", r.returncode == 0, (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "")
    v = run(d, "verify_data.py", base)
    rep = json.loads((d / "companies" / SLUG / "data" / "verify_report.json").read_text(encoding="utf-8"))
    fails = [f"{x['name']}: {x['detail']}" for x in rep["results"] if x["state"] == "실패"]
    ok("검증 실패 0건", v.returncode == 0 and not fails, "; ".join(fails[:3]) or str(rep["counts"]))
    exp = next((x for x in rep["results"] if x["name"] == "사람이 대조한 기준값과 일치"), {})
    ok("사람이 원문 대조한 기준값 48개 모두 일치", exp.get("detail") == "48/48개", exp.get("detail", ""))
    fin = rows(d / "companies" / SLUG / "data" / "financials.csv")
    ok("연간 연도 2022~2025", sorted({r["year"] for r in fin}) == ["2022", "2023", "2024", "2025"])
    q = rows(d / "companies" / SLUG / "data" / "quarterly.csv")
    ok("분기 실적 12개 이상 (2023Q1~2025Q4)", len({r["period"] for r in q}) >= 12, f"{len({r['period'] for r in q})}개")
    capex = next(r for r in fin if r["year"] == "2025" and r["metric"] == "capex")
    met = {(r["year"], r["metric"]): r for r in rows(d / "companies" / SLUG / "data" / "metrics.csv")}
    ok("2025 영업이익률 22.29%", round(float(met[("2025", "operating_margin_pct")]["value"]), 2) == 22.29, met[("2025", "operating_margin_pct")]["value"])
    ok("2022 증가율은 전기 자료 없어 빈칸", met[("2022", "revenue_growth_pct")]["value"] == "")
    fcf = int(met[("2025", "simple_fcf")]["value"])
    ok("음수로 온 유형자산 취득액을 절대값으로 FCF 계산", fcf == 309287213625 - 448988219606, f"capex 원값 {capex['value']} · FCF {fcf:,}")
    st = rows(d / "companies" / SLUG / "data" / "research_status.csv")
    n_food = len(json.loads((REPO / "industries" / "food.json").read_text(encoding="utf-8"))["kpis"])
    ok(f"식품 산업 KPI {n_food}개가 모두 '미확인'으로 표시 (임의 생성 없음)", sum(1 for r in st if r["status"] == "미확인") == n_food)
    sm = json.loads((d / "companies" / SLUG / "data" / "summary.json").read_text(encoding="utf-8"))
    ok("summary.json에 산업·카테고리·핵심 KPI", sm["industry"] == "food" and sm["categories"] == ["라면"] and sm["kpis"]["revenue"] == 2351785163786)
    stock = rows(d / "companies" / SLUG / "data" / "stock_daily.csv")
    ok("주가 940행 + 코스피 지수", len(stock) == 940 and stock[0]["index_close"] != "", f"{len(stock)}행")
    reg = rows(d / "companies" / SLUG / "data" / "source_registry.csv")
    ok("정기공시가 아닌 공시는 제외", not any("주요사항" in r["title"] for r in reg))

    r = subprocess.run([sys.executable, str(d / "scripts" / "build_index.py")], capture_output=True, text=True, cwd=d)
    idx = json.loads((d / "companies" / "index.json").read_text(encoding="utf-8"))
    types = sorted(n["type"] for n in idx["graph"]["nodes"])
    ok("기업 목록·그래프 생성 (CORE→산업→카테고리→기업)", types == ["category", "company", "core", "industry"] and idx["companies"][0]["has_data"], str(types))

    r = run(d, "collect_business_text.py", base)
    bt = d / "companies" / SLUG / "data" / "raw" / "business_2025.txt"
    txt = bt.read_text(encoding="utf-8") if bt.exists() else ""
    ok("사업보고서 'II. 사업의 내용'만 텍스트로 저장 (표 구분 유지)", "면스낵 수출 | 1,234 |" in txt and "재무에 관한 사항" not in txt and "회사의 개요" not in txt, r.stdout.strip()[-80:])
    r = run(d, "collect_business_text.py", base)
    ok("같은 보고서는 다시 받지 않음", "이미 저장됨" in r.stdout)

    sys.path.insert(0, str(d / "scripts"))
    os.environ["UBDA_COMPANY"] = SLUG
    import importlib
    os.chdir(d)
    cd = importlib.import_module("collect_dart")
    rep = {"bsns_year": "2025", "reprt_code": "11011", "report_type": "사업보고서", "rcept_no": "1", "rcept_dt": "20260301", "report_nm": "사업보고서 (2025.12)"}
    items = [{"sj_div": "CIS", "account_id": "dart_TotalSellingGeneralAdministrativeExpenses", "account_nm": "판매비", "thstrm_amount": "100"},
             {"sj_div": "CIS", "account_id": "dart_AdministrativeExpense", "account_nm": "관리비", "thstrm_amount": "40"}]
    sga = next(r for r in cd.to_rows(items, rep, "CFS") if r["metric"] == "sga")
    ok("판매비·관리비를 따로 적는 회사는 합산 (오리온 사례)", sga["value"] == 140 and "합산" in sga["account_nm"], f"{sga['value']} · {sga['account_nm']}")
    items2 = [{"sj_div": "IS", "account_id": "dart_TotalSellingGeneralAdministrativeExpenses", "account_nm": "판매비와관리비", "thstrm_amount": "90"}, items[1]]
    items3 = [{"sj_div": "CIS", "account_id": "ifrs-full_SellingExpense", "account_nm": "판매비", "thstrm_amount": "100"},
              {"sj_div": "CIS", "account_id": "ifrs-full_GeneralAndAdministrativeExpense", "account_nm": "일반관리비", "thstrm_amount": "30"}]
    sga3 = next(r for r in cd.to_rows(items3, rep, "CFS") if r["metric"] == "sga")
    ok("'판매비'+'일반관리비'도 합산 (오리온 2024~)", sga3["value"] == 130, f"{sga3['value']} · {sga3['account_nm']}")
    ok("판매비와관리비 합계 계정이 있으면 그대로", next(r for r in cd.to_rows(items2, rep, "CFS") if r["metric"] == "sga")["value"] == 90)
    os.chdir(REPO)

    print("\n[1-1] 주가 급변일 + 같은 시기 공시 자동 연결")
    fx = rows(HERE / "fixtures" / "stock_daily.csv")
    best, bd = 0, None
    for i in range(62, len(fx)):
        a0, a1, k0, k1 = (float(fx[i - 1]["close"]), float(fx[i]["close"]), fx[i - 1]["kospi"], fx[i]["kospi"])
        if not (k0 and k1):
            continue
        e = abs((a1 / a0 - 1) - (float(k1) / float(k0) - 1))
        if e > best:
            best, bd = e, fx[i]["date"]
    dk = bd.replace("-", "")
    data.extra = [{"rcept_no": dk + "900001", "rcept_dt": dk, "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)", "flr_nm": "삼양식품"},
                  {"rcept_no": dk + "900002", "rcept_dt": dk, "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서", "flr_nm": "홍길동"},
                  {"rcept_no": "20230105900003", "rcept_dt": "20230105", "report_nm": "단일판매ㆍ공급계약체결", "flr_nm": "삼양식품"}]
    from datetime import datetime as _dt
    rfc = _dt.strptime(bd, "%Y-%m-%d").strftime("%a, %d %b %Y 10:00:00 +0900")
    data.news = [{"title": "<b>삼양식품</b> 실적 발표", "link": "https://n.news.naver.com/a/1", "originallink": "https://www.example.co.kr/1", "pubDate": rfc},
                 {"title": "라면 업계 소식", "link": "https://n.news.naver.com/a/2", "originallink": "https://www.example.co.kr/2", "pubDate": rfc}]
    r = run(d, "collect_news.py", base)
    ok("네이버 키가 없으면 뉴스·검색 관심도는 건너뜀 (종료코드 0)", r.returncode == 0 and "건너뜀" in r.stdout and run(d, "collect_search.py", base).returncode == 0)
    r = run(d, "collect_news.py", base, naver=("NID", "WRONG"))
    ok("네이버 키가 틀리면 경고만", r.returncode == 0 and "인증 실패" in r.stdout + r.stderr, (r.stdout + r.stderr).strip()[-70:])
    r = run(d, "collect_news.py", base, naver=("NID", "NSECRET"))
    nw = rows(d / "companies" / SLUG / "data" / "raw" / "news.csv")
    ok("뉴스: 제목에 회사명이 있는 기사만, 태그 제거, 한국 시각으로 저장", len(nw) == 1 and nw[0]["title"] == "삼양식품 실적 발표" and nw[0]["pub_dt"] == bd + " 10:00", str(nw))
    r = run(d, "collect_news.py", base, naver=("NID", "NSECRET"))
    ok("뉴스 재실행 시 중복 저장 없음", len(rows(d / "companies" / SLUG / "data" / "raw" / "news.csv")) == 1)
    r = run(d, "collect_search.py", base, naver=("NID", "NSECRET"))
    tr = rows(d / "companies" / SLUG / "data" / "search_trend.csv")
    ok("검색 관심도: 이 기업 + 비교 기업을 한 요청으로 (주 단위)", r.returncode == 0 and data.last_trend["timeUnit"] == "week" and len(data.last_trend["keywordGroups"]) == 1 + 0
       and tr and tr[0]["is_self"] == "Y", f"{len(tr)}행 · {[g['groupName'] for g in data.last_trend['keywordGroups']]}")
    r = run(d, "collect_events.py", base)
    ev = rows(d / "companies" / SLUG / "data" / "events_auto.csv")
    lk = rows(d / "companies" / SLUG / "data" / "event_links.csv")
    hit = next((e for e in ev if e["date"] == bd), None)
    ok("급변일 찾음 (연도별 10일 이하)", r.returncode == 0 and ev and max(sum(1 for e in ev if e["date"][:4] == y) for y in {e["date"][:4] for e in ev}) <= 10,
       f"{len(ev)}일 · {r.stdout.strip()[-60:]}")
    ok("가장 큰 초과 등락일에 잠정실적 공시가 대표 공시로 연결, 지분 공시는 '기타'", hit is not None and hit["other_count"] == "1"
       and "잠정" in hit["headline"] and hit["categories"].startswith("실적"), str(hit and {k: hit[k] for k in ("date", "headline", "major_count", "other_count")}))
    ok("급변일 기사가 '보도'로 연결", hit is not None and hit["news_count"] == "1" and any(x["category"] == "보도" and x["date"] == bd for x in lk))
    ok("급변일과 멀리 떨어진 공시는 연결 안 됨", not any(x["rcept_no"] == "20230105900003" for x in lk))
    ok("공시가 없는 급변일도 남김", any(e["major_count"] == "0" for e in ev))
    disc = rows(d / "companies" / SLUG / "data" / "raw" / "dart_disclosures.csv")
    n_list = data.calls["/api/list.json"]
    r = run(d, "collect_events.py", base)
    ok("재실행 때는 최근 공시만 다시 조회 (중복 저장 없음)", data.calls["/api/list.json"] - n_list == 1 and len(rows(d / "companies" / SLUG / "data" / "raw" / "dart_disclosures.csv")) == len(disc),
       f"추가 조회 {data.calls['/api/list.json'] - n_list}회")

    print("\n[2] 다시 실행 — 새 보고서가 없으면 재무 API를 다시 부르지 않음")
    before = data.calls["/api/fnlttSinglAcntAll.json"]
    r = run(d, "collect_dart.py", base)
    ok("재실행 시 새로 반영 0건", "새로 반영 0건" in r.stdout, r.stdout.strip().splitlines()[0])
    ok("재무 API 추가 호출 없음", data.calls["/api/fnlttSinglAcntAll.json"] == before)

    print("\n[2-1] 수집이 중간에 끊겨도 받은 보고서는 남고, 다음 실행이 이어서 받음")
    dd = workdir()
    env = {**os.environ, "DART_BASE_URL": base + "/api", "YAHOO_HOSTS": base, "DART_API_KEY": "TESTKEY", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    pr = subprocess.Popen([sys.executable, str(dd / "scripts" / "collect_dart.py"), "--company", SLUG], env=env, cwd=dd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rp = dd / "companies" / SLUG / "data" / "raw" / "dart_reports.csv"
    import time as _t
    for _ in range(100):  # 보고서 몇 건이 저장될 때까지 기다렸다가 강제 종료
        if rp.exists() and len(rows(rp)) >= 3:
            break
        _t.sleep(0.1)
    pr.kill(); pr.wait()
    n_mid = len(rows(rp)) if rp.exists() else 0
    r = run(dd, "collect_dart.py", base)
    n_end = len(rows(rp))
    ok("강제 종료 전 받은 보고서가 저장됨", 0 < n_mid < n_end, f"중간 {n_mid}건 → 재실행 후 {n_end}건")

    print("\n[3] 사람 대조 기록 반영과 불일치 감지")
    man = d / "companies" / SLUG / "data" / "manual" / "audit_overrides.csv"
    with man.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["F-2025-revenue", "원문 대조 일치", "2351785163786", "사업보고서 p.48 연결 IS", "2026-11-12", "사용자", ""])
        w.writerow(["F-2024-revenue", "원문 대조 일치", "1700000000000", "사업보고서 p.48", "2026-11-12", "사용자", ""])
    run(d, "build_dataset.py", base)
    led = {r["audit_id"]: r for r in rows(d / "companies" / SLUG / "data" / "audit_ledger.csv")}
    ok("대조 일치 기록이 재빌드 후에도 유지", led["F-2025-revenue"]["result"] == "원문 대조 일치")
    ok("대조값과 다르면 '불일치'", led["F-2024-revenue"]["result"] == "불일치", led["F-2024-revenue"]["note"])
    ok("불일치가 있으면 검증 실패(종료코드 1)", run(d, "verify_data.py", base).returncode == 1)

    print("\n[4] 산업 KPI: 출처 없는 숫자·추정값 차단")
    d4 = workdir()
    for s in ("collect_dart.py", "build_dataset.py"):
        run(d4, s, base)
    kp = d4 / "companies" / SLUG / "data" / "manual" / "kpi_values.csv"
    with kp.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["export_revenue", "2025", "2025", "면스낵 수출", "100", "KRW", "제품군", "", "", "자동 수집 · 원문 대조 전", "", ""])
        w.writerow(["market_share", "2025", "2025", "라면", "15", "%", "", "", "", "미확인", "", "추정"])
    run(d4, "build_dataset.py", base)
    v4 = run(d4, "verify_data.py", base)
    ok("출처 없는 KPI 값 → 실패", "[실패] 산업 KPI 값마다 출처 URL" in v4.stdout)
    ok("'미확인'에 숫자를 넣으면 → 실패", "[실패] 미확인·미공개 항목에 숫자 없음" in v4.stdout)

    print("\n[5] 연결재무제표가 없는 회사 → 별도(OFS)로 자동 전환")
    srv.shutdown()
    data2 = mock_server.Data(stock_code="123456", corp_code="00999999", corp_name="테스트식품", no_cfs=True)
    srv, base = mock_server.start(data2)
    d5 = workdir({"company_id": "TS", "name": "테스트식품", "stock_code": "123456", "yahoo_ticker": "123456.KS"})
    run(d5, "collect_dart.py", base)
    run(d5, "build_dataset.py", base)
    f5 = rows(d5 / "companies" / SLUG / "data" / "financials.csv")
    ok("범위 '별도'로 기록", f5 and all(r["scope"] == "별도" for r in f5 if r["value"]), f"{len(f5)}행")
    v5 = run(d5, "verify_data.py", base)
    ok("다른 회사에는 삼양 기준값을 적용하지 않음", "기준 파일은 SY용" in v5.stdout)

    print("\n[6] 실패해도 사이트가 깨지지 않음")
    d6 = workdir({"stock_code": "000000"})
    r6 = run(d6, "collect_dart.py", base)
    log = json.loads((d6 / "companies" / SLUG / "data" / "update_log.json").read_text(encoding="utf-8"))
    ok("없는 종목코드 → 경고만, 종료코드 0", r6.returncode == 0 and log["dart"]["status"] == "실패", log["dart"]["message"][:60])
    d7 = workdir()
    r7 = run(d7, "collect_dart.py", base, key="")
    ok("API 키 없음 → 경고만, 종료코드 0", r7.returncode == 0 and "DART_API_KEY가 없습니다" in r7.stderr)
    r8 = run(d7, "collect_dart.py", base, key="WRONG")
    ok("잘못된 API 키 → 경고만", r8.returncode == 0 and "등록되지 않은 키" in r8.stderr)
    srv.shutdown()

    print(f"\n결과: 통과 {len(passed)} · 실패 {len(failed)}")
    for n in failed:
        print("  실패:", n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
