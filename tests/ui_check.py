#!/usr/bin/env python3
"""
화면 점검 (선택) — 실제 브라우저로 모든 페이지를 열어 오류·빈 차트·클릭 동작을 확인합니다.

    pip install playwright && python -m playwright install chromium
    python tests/ui_check.py [사이트 폴더] [스크린샷 폴더]

사이트 폴더를 주지 않으면 이 저장소를 그대로 엽니다.
기업 목록(index.html)과 companies/ 아래 모든 기업의 대시보드(dashboard.html?c=기업)를 점검합니다.
데이터가 아직 없는 기업은 '데이터 없음' 안내가 나오는지 확인합니다.
"""
from __future__ import annotations

import functools
import json
import time
import http.server
import os
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
PAGES = ["overview", "compare", "pl", "quarterly", "ratios", "bs", "stock", "timeline", "news", "debate", "production", "industry", "dart", "audit", "screen"]
fails: list[str] = []


def ok(name, cond, detail=""):
    print(("  ✔ " if cond else "  ✘ ") + name + (f" — {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=str(ROOT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{srv.server_address[1]}/"
    slugs = sorted(p.parent.name for p in (ROOT / "companies").glob("*/company.json"))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None,
                              args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])  # 화면 없는 환경에서도 WebGL
        # 랜딩페이지 (landing.html) — 사이트 주소를 처음 열면 랜딩, 입장하면 기업 네트워크 그래프
        if (ROOT / "landing.html").exists():
            for label, vp in (("PC", {"width": 1366, "height": 860}), ("모바일", {"width": 390, "height": 844})):
                print(f"\n[랜딩 landing.html · {label}]")
                pg = b.new_page(viewport=vp)
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                pg.goto(root)
                pg.wait_for_url("**/landing.html", timeout=10000)
                ok("사이트 주소 → 랜딩으로 이동", pg.url.endswith("landing.html"), pg.url.split("/")[-1])
                pg.wait_for_timeout(1500)  # companies/index.json을 읽어 숫자를 채울 시간
                n_co = len(slugs)
                ok("랜딩 기업 수 = companies/ 기업 수", pg.inner_text("[data-n='co']") == str(n_co), f"{pg.inner_text('[data-n=co]')}/{n_co}")
                ok("랜딩 가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth") <= vp["width"])
                if label == "PC":
                    pg.keyboard.press("Enter")
                    pg.wait_for_url("**/index.html", timeout=15000)
                    pg.wait_for_function("document.querySelector('#stats') && /COMPANIES/.test(document.querySelector('#stats').textContent)", timeout=20000)
                    ok("Enter → 기업 네트워크 입장", True)
                    pg.goto(root + "list.html")
                    pg.click("text=3D 보기")
                    pg.wait_for_function("document.querySelector('#stats') && /COMPANIES/.test(document.querySelector('#stats').textContent)", timeout=20000)
                    ok("같은 탭: 목록 → 3D 보기에서 랜딩으로 돌아가지 않음", pg.url.endswith("index.html"), pg.url.split("/")[-1])
                ok(f"랜딩 {label} 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
                pg.close()
            pg = b.new_page()
            pg.goto(root + "index.html?direct")
            pg.wait_for_function("document.querySelector('#stats') && /COMPANIES/.test(document.querySelector('#stats').textContent)", timeout=20000)
            ok("주소에 ?…가 붙은 링크는 랜딩을 건너뜀", "index.html?direct" in pg.url)
            pg.close()
        # 기업 네트워크 그래프 (index.html) — 입장 표시를 미리 넣어 랜딩을 건너뜀
        J = __import__("json")
        idx = J.loads((ROOT / "companies" / "index.json").read_text(encoding="utf-8"))
        n_ind_idx = len({c["industry"] for c in idx["companies"]})
        for label, vp in (("PC", {"width": 1366, "height": 860}), ("모바일", {"width": 390, "height": 844})):
            print(f"\n[기업 네트워크 index.html · {label}]")
            pg = b.new_page(viewport=vp)
            pg.add_init_script("try{sessionStorage.setItem('ubda_entered','1')}catch(e){}")
            errs, ext = [], []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.on("request", lambda r: ext.append(r.url) if not (r.url.startswith(root) or r.url.startswith("data:") or r.url.startswith("blob:")) else None)
            pg.goto(root)
            pg.wait_for_function("document.querySelector('#stats') && /COMPANIES/.test(document.querySelector('#stats').textContent)", timeout=20000)
            st = pg.inner_text("#stats")
            ok("WebGL 그래프 표시 (안내 문구 아님)", not pg.is_visible("#nogl"))
            ok("산업·기업 수 = companies/index.json", f"{n_ind_idx} INDUSTRIES" in st and f"{len(idx['companies'])} COMPANIES" in st, st.replace("\n", " / "))
            ok("DATA 날짜 = index.json updated_at", idx.get("updated_at", "?") in st)
            ok("기업 이름 라벨 = 대시보드 링크", pg.locator("#labels a[href*='dashboard.html?c=']").count() == len(idx["companies"]), str(pg.locator("#labels a").count()))
            first = idx["companies"][0]
            pg.fill("#q", first["name"])
            pg.wait_for_timeout(400)
            pg.keyboard.press("Enter")
            pg.wait_for_selector("a.cta", timeout=8000)
            ok("검색 → 기업 패널 + 대시보드 열기 버튼", first["name"] in pg.inner_text("#pbody") and "대시보드 열기" in pg.inner_text("a.cta"))
            if SHOTS:
                SHOTS.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(SHOTS / f"graph_{label}.png"))
            pg.locator("a.cta").press("Enter")
            pg.wait_for_url("**/dashboard.html?c=*", timeout=10000)
            ok("Enter → 같은 탭에서 대시보드", f"dashboard.html?c={first['slug']}" in pg.url, pg.url.split("/")[-1])
            pg.go_back()
            pg.wait_for_function("document.querySelector('#stats') && /COMPANIES/.test(document.querySelector('#stats').textContent)", timeout=20000)
            ok("뒤로 가기 → 그래프로 돌아옴 (랜딩 아님)", pg.url.split("?")[0].endswith("/") or "index.html" in pg.url, pg.url.split("/")[-1])
            ok("가로 넘침 없음", pg.evaluate("document.documentElement.scrollWidth") <= vp["width"])
            ok(f"그래프 {label} 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
            ok(f"그래프 {label} 외부 요청 없음", not ext, "; ".join(ext[:3]))
            pg.close()
        # 기업 목록 (목록형)
        print("\n[기업 목록 list.html]")
        pg = b.new_page(viewport={"width": 1366, "height": 860})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(root + "list.html")
        pg.wait_for_selector(".p-card, .empty", timeout=10000)
        ok("기업 카드 표시", pg.locator(".p-card").count() >= len(slugs), f"{pg.locator('.p-card').count()}개 / 기업 {len(slugs)}개")
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(SHOTS / "목록.png"), full_page=True)
        pg.fill("#q", "zzz없는기업")
        ok("검색: 결과 없음 안내", "검색 결과가 없습니다" in pg.inner_text("#list"))
        pg.fill("#q", "")
        pg.locator(".p-card").first.click()
        pg.wait_for_selector(".page", timeout=10000)
        ok("카드 클릭 → 대시보드 이동", "dashboard.html?c=" in pg.url, pg.url)
        pg.goto(root + "dashboard.html?c=nocompany")
        pg.wait_for_timeout(500)
        ok("없는 기업 주소 → 안내 표시", "찾지 못했습니다" in pg.inner_text("#workspace"))
        ok("목록 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
        pg.close()
        only = [x for x in os.environ.get("UI_ONLY", "").split(",") if x]  # 예: UI_ONLY=naver,kakao — 일부 기업 대시보드만 점검
        for slug in [x for x in slugs if not only or x in only]:
            url = root + f"dashboard.html?c={slug}"
            has_data = (ROOT / "companies" / slug / "data" / "financials.csv").exists()
            for label, vp in (("PC", {"width": 1366, "height": 860}), ("모바일", {"width": 390, "height": 844})):
                print(f"\n[{slug} · {label} {vp['width']}px · {'데이터 있음' if has_data else '데이터 없음'}]")
                pg = b.new_page(viewport=vp)
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                pg.goto(url)
                pg.wait_for_selector(".page", timeout=10000)
                if label == "PC" and has_data:
                    # PC 사이드바 자동 숨김: 기본은 숨김, 왼쪽 끝에 마우스 → 나옴, 벗어나면 숨김
                    pg.goto("about:blank"); pg.goto(url + "#overview")   # 메인 스크린에서는 사이드바가 없으므로 개요에서 확인
                    pg.wait_for_timeout(1500)
                    nx = lambda: pg.evaluate("document.querySelector('.nav').getBoundingClientRect().right")
                    ok("사이드바: 기본 숨김(PC)", nx() <= 1)
                    pg.mouse.move(600, 400); pg.mouse.move(4, 430); pg.wait_for_timeout(700)
                    ok("사이드바: 왼쪽 끝 마우스 → 나옴", nx() > 150)
                    pg.mouse.move(120, 430); pg.mouse.move(800, 430); pg.wait_for_timeout(900)
                    ok("사이드바: 벗어나면 숨김", nx() <= 1)
                    pg.evaluate("localStorage.setItem('ubda_nav_pin','1')")   # 이하 탭별 점검은 사이드바 고정 상태에서
                    pg.goto("about:blank"); pg.goto(url)
                    pg.wait_for_selector(".page", timeout=10000)
                if has_data:
                    # 기본 진입 = 메인 스크린 → 지구본 더블클릭 확인창(No: 유지, Yes: 개요)
                    ok("기본 진입 화면이 메인 스크린", "screen-mode" in (pg.get_attribute("body", "class") or ""))
                    sf = None
                    for _ in range(60):
                        sf = next((f for f in pg.frames if "screen.html" in f.url), None)
                        if sf and sf.evaluate("!!window.__screenReady"):
                            break
                        pg.wait_for_timeout(250)
                    if sf:
                        sf.dblclick("#globePanel")
                        pg.wait_for_timeout(500)
                        ok("지구본 더블클릭 → 입장 확인창", sf.evaluate("!document.getElementById('enterDlg').hidden") and "입장하시겠습니까" in sf.inner_text("#enterQ"))
                        if SHOTS:
                            pg.screenshot(path=str(SHOTS / f"{slug}_{label}_enter.png"))
                        sf.click("#enterNo")
                        pg.wait_for_timeout(400)
                        ok("No → 메인 스크린 유지", sf.evaluate("document.getElementById('enterDlg').hidden") and "screen-mode" in (pg.get_attribute("body", "class") or ""))
                        sf.dblclick("#globePanel")
                        pg.wait_for_timeout(500)
                        sf.click("#enterYes")
                        pg.wait_for_timeout(500)
                        ok("Yes → 개요로 입장", pg.inner_text("#pageTitle") == "개요" and "screen-mode" not in (pg.get_attribute("body", "class") or ""))
                    else:
                        ok("메인 스크린 프레임 로드", False)
                for pid in PAGES:
                    if label == "모바일":
                        pg.click("#menuBtn")
                        pg.wait_for_timeout(300)
                    if pid != "screen" and "screen-mode" in (pg.get_attribute("body", "class") or ""):
                        pg.keyboard.press("Escape")
                        pg.wait_for_timeout(200)
                        if label == "모바일":
                            pg.click("#menuBtn")
                            pg.wait_for_timeout(300)
                    pg.click(f'.nav-btn[data-page="{pid}"]')
                    pg.wait_for_timeout(700 if pid == "compare" else 250)
                    title = pg.inner_text("#pageTitle")
                    charts = pg.locator(".chart").count()
                    svgs = pg.locator(".chart svg").count()
                    overflow = pg.evaluate("document.querySelector('.workspace').scrollWidth - document.querySelector('.workspace').clientWidth")
                    ok(f"{pid} '{title}' 열림" + (f" · 차트 {svgs}/{charts}" if charts else ""), (svgs == charts) or not has_data)
                    ok(f"{pid} 가로 넘침 없음", overflow <= 2, f"{overflow}px")
                    if SHOTS:
                        pg.screenshot(path=str(SHOTS / f"{slug}_{label}_{pid}.png"), full_page=label == "PC")
                if has_data and label == "PC":
                    pg.keyboard.press("Escape")  # 메인 스크린에서 나가기
                    pg.wait_for_timeout(300)
                    ok("메인 스크린 → Esc로 개요 복귀", pg.inner_text("#pageTitle") == "개요")
                    pg.click('.nav-btn[data-page="screen"]')
                    fr = pg.frame_locator("#screenFrame")
                    sf = None
                    for _ in range(60):
                        sf = next((f for f in pg.frames if "screen.html" in f.url), None)
                        if sf and sf.evaluate("!!window.__screenReady"):
                            break
                        pg.wait_for_timeout(250)
                    ready = bool(sf and sf.evaluate("!!window.__screenReady"))
                    kpis = fr.locator(".kpi").count() if ready else 0
                    canv = sf.evaluate("[...document.querySelectorAll('#qopChart,#plantChart,#dialA,#qrevChart,#searchChart')].filter(e=>e.querySelector('canvas')).length") if ready else 0
                    hard = sf.evaluate("document.querySelectorAll('.err:not([style])').length") if ready else -1
                    ok("메인 스크린(screen.html) KPI 4개·차트 칸 5개·오류 없음", kpis == 4 and canv == 5 and hard == 0, f"KPI {kpis} · 차트 {canv} · 오류 {hard}")
                    if SHOTS:
                        pg.screenshot(path=str(SHOTS / f"{slug}_screen.png"))
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(200)
                    pg.click('[data-per="quarter"]')
                    pg.wait_for_timeout(200)
                    ok("개요 연간→분기 전환", pg.locator("#c1 text").filter(has_text="Q").count() > 0)
                    pg.click('[data-per="annual"]')
                    if pg.locator(".bd-grid").count():
                        # 보드형 개요(임시 미리보기 기업): 카드 5개, 키보드로 순서 이동 → 저장 → 기본 배치로
                        order = lambda: pg.evaluate("[...document.querySelectorAll('.bd-grid>.bd-card')].map(c=>c.dataset.bk).join()")
                        before = order()
                        ok("보드: 카드 5개", pg.locator(".bd-grid > .bd-card").count() == 5, before)
                        pg.focus('.bd-grid [data-grip="diag"]'); pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(300)
                        moved = order()
                        ok("보드: 손잡이 ← 키로 카드 이동", moved != before and moved.startswith("diag"), moved)
                        pg.click('[data-bd="reset"]'); pg.wait_for_timeout(300)
                        ok("보드: 기본 배치로 복원", order() == before)
                    else:
                        pg.click("#editBtn")
                        pg.wait_for_timeout(200)
                        ok("배치 편집 모드 표시", pg.locator(".edit-banner").count() == 1 and pg.locator(".grid > .card[draggable=true]").count() > 0)
                        pg.click('[data-edit="done"]')
                    pg.click("#askBtn")
                    pg.wait_for_timeout(200)
                    chips = pg.locator("[data-ask]")
                    for i in range(chips.count()):
                        chips.nth(i).click()
                        pg.wait_for_timeout(250)
                    n_calc = pg.locator(".ans:not(.unk)").count()
                    n_unk = pg.locator(".ans.unk").count()
                    ok("데이터 질의 예시 답변", n_calc >= 4 and pg.locator(".ans").count() == chips.count(), f"계산 {n_calc} · 미확인 {n_unk}")
                    if SHOTS:
                        pg.screenshot(path=str(SHOTS / f"{slug}_query.png"))
                    pg.click('.nav-btn[data-page="compare"]')
                    pg.wait_for_timeout(800)
                    ok("기업 비교 차트 2개", pg.locator("#cp1 svg, #cp2 svg").count() == 2)
                    _idx = json.loads((ROOT / "companies" / "index.json").read_text(encoding="utf-8"))
                    _ind = {c["name"]: c["industry"] for c in _idx["companies"]}
                    _me = json.loads((ROOT / "companies" / slug / "company.json").read_text(encoding="utf-8"))["industry"]
                    _names = pg.locator("[data-cmp]").all_inner_texts()
                    ok("기업 비교 후보는 같은 산업만", _names and all(_ind.get(n) == _me for n in _names), ", ".join(_names))
                    if (ROOT / "companies" / slug / "data" / "diagnosis.json").exists():
                        pg.click('[data-page="overview"]'); time.sleep(1.2)
                        if pg.locator(".bd-grid").count():
                            ok("보드 성과체계: ROE + 3요인 + 손익·부채 4칸", pg.locator(".bp .bp-n.root").count() == 1 and pg.locator(".bp-r3 .bp-n").count() == 3 and pg.locator(".bp-r4 .bp-n").count() == 4)
                            ok("보드 종합 진단: 레이더 + 성향 3개", pg.locator(".bd-radar svg").count() == 1 and pg.locator(".bd-prof").count() == 3)
                        else:
                            ok("개요 성과체계: ROE 분해 합계 = ROE 변화", pg.locator(".pt .pt-n.root").count() == 1 and "ROE" in pg.locator(".pt-sum").inner_text())
                            ok("종합 진단 카드: 레이더 + 성향 3개", pg.locator(".card.diag .radar").count() == 1 and pg.locator(".dg-row").count() == 3)
                        pg.locator('[data-act="dg:neutral"]').click(); time.sleep(0.4)
                        ok("진단 근거 패널", "위험중립형" in pg.locator("#panelIn h2").inner_text())
                        pg.locator("#panelIn .x").click()
                    pg.click('.nav-btn[data-page="overview"]')
                    pg.wait_for_timeout(200)
                    pg.locator(".chart .bar").first.click()
                    pg.wait_for_timeout(400)
                    ok("막대 클릭 → 근거 패널 열림", "panel-open" in (pg.get_attribute("#app", "class") or "") and "검증번호" in pg.inner_text("#panelIn"))
                    pg.click('.nav-btn[data-page="ratios"]')
                    pg.wait_for_timeout(200)
                    pg.locator("tr.click").first.click()
                    pg.wait_for_timeout(300)
                    ok("재무비율 클릭 → 산식 표시", "산식" in pg.inner_text("#panelIn"))
                    pg.click('.nav-btn[data-page="quarterly"]')
                    pg.locator('[data-q="operating_profit"]').click()
                    ok("분기 항목 전환", pg.locator('[data-q="operating_profit"][aria-pressed="true"]').count() == 1)
                    pg.click('.nav-btn[data-page="stock"]')
                    pg.locator('[data-sm="raw"]').click()
                    ok("주가 보기 전환", pg.locator(".chart svg path").count() >= 1)
                if not has_data:  # 데이터 파일이 아직 없으면 404는 정상 ('데이터 없음' 안내로 처리됨)
                    errs = [e for e in errs if "404" not in e]
                    if label == "모바일":
                        pg.click("#menuBtn")
                        pg.wait_for_timeout(300)
                    pg.click('.nav-btn[data-page="overview"]')
                    pg.wait_for_timeout(200)
                    ok(f"{label} 빈 상태 안내 표시", "아직 재무 데이터가 없습니다" in pg.inner_text("#workspace"))
                ok(f"{label} 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
                pg.close()
        # 기업 토론 탭: 테스트 픽스처(가짜 토론)를 가로채 넣어 말풍선 재생·결론 표시를 확인 (사이트 데이터는 건드리지 않음)
        fx = (ROOT / "tests/fixtures/debate_sample.json").read_text(encoding="utf-8")
        tslug = next((x for x in slugs if (not only or x in only) and (ROOT / "companies" / x / "data" / "financials.csv").exists()), None)
        if tslug:
            print(f"\n[기업 토론 탭 · {tslug} · 테스트 픽스처]")
            pg = b.new_page(viewport={"width": 1366, "height": 860})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/companies/debate_index.json", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({tslug: ["2026-11"]})))
            pg.route(f"**/companies/{tslug}/data/debate/2026-11.json", lambda r: r.fulfill(status=200, content_type="application/json", body=fx))
            pg.goto(root + f"dashboard.html?c={tslug}#debate")
            pg.wait_for_timeout(1500)
            first = pg.evaluate("document.querySelectorAll('.deb-row:not(.deb-hide)').length")
            ok("토론: 말풍선이 하나씩 나타남", 0 < first < 6, f"처음 {first}개")
            pg.click('[data-act="deb:skip"]')
            pg.wait_for_timeout(300)
            ok("토론: 전체 보기 → 고문 5명 + 결론", pg.locator(".deb-row").count() == 6 and pg.locator(".deb-row.deb-hide").count() == 0)
            ok("토론: 확신도·답글 표시", "62%" in pg.inner_text(".deb-conf") and pg.locator(".deb-rep").count() == 4)
            if SHOTS:
                pg.screenshot(path=str(SHOTS / f"{tslug}_debate.png"), full_page=True)
            ok("토론: 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
            pg.close()
        b.close()
    srv.shutdown()
    print(f"\n결과: 실패 {len(fails)}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
