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
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
SHOTS = Path(sys.argv[2]) if len(sys.argv) > 2 else None
PAGES = ["overview", "compare", "pl", "quarterly", "ratios", "bs", "stock", "industry", "dart", "audit", "screen"]
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
        # 3D 포털 (index.html)
        for label, vp in (("PC", {"width": 1366, "height": 860}), ("모바일", {"width": 390, "height": 844})):
            print(f"\n[3D 포털 index.html · {label}]")
            pg = b.new_page(viewport=vp)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.goto(root)
            pg.wait_for_function("window.__portal", timeout=20000)
            ok("WebGL 화면 표시 (대체 화면 아님)", pg.locator("canvas").count() == 1 and not pg.is_visible("#fallback"))
            n_ind = len(list((ROOT / "industries").glob("*.json")))
            ok("산업 노드 이름표 = industries/*.json 수", pg.locator(".lbl.industry").count() == n_ind, f"{pg.locator('.lbl.industry').count()}/{n_ind}")
            first = sorted(slugs)[0]
            ind = __import__("json").loads((ROOT / "companies" / first / "company.json").read_text(encoding="utf-8"))
            cat = (ind.get("categories") or ["기타"])[0]
            for nid in (f"ind:{ind['industry']}", f"cat:{ind['industry']}:{cat}", f"co:{first}"):
                pg.wait_for_function("!__portal.flying")
                pg.wait_for_timeout(300)
                pt = pg.evaluate(f"__portal.screenOf({__import__('json').dumps(nid)})")
                pg.mouse.click(pt["x"], pt["y"])
                pg.wait_for_timeout(300)
                ok(f"구체 클릭 → {nid} 선택", pg.evaluate("__portal.selected") == nid)
            pg.wait_for_function("!__portal.flying")
            ok("기업 정보 패널 + 대시보드 열기", "대시보드 열기" in pg.inner_text("#info"))
            if SHOTS:
                SHOTS.mkdir(parents=True, exist_ok=True)
                pg.screenshot(path=str(SHOTS / f"3d_{label}.png"))
            pg.click("#resetBtn")
            pg.fill("#q", ind["name"][:2])
            pg.wait_for_timeout(150)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            ok("검색 → 기업으로 이동", (pg.evaluate("__portal.selected") or "").startswith("co:"), pg.evaluate("__portal.selected"))
            pg.click("text=대시보드 열기")
            pg.wait_for_selector(".page", timeout=10000)
            ok("대시보드로 이동", "dashboard.html?c=" in pg.url, pg.url.split("/")[-1])
            ok(f"3D {label} 자바스크립트 오류 없음", not errs, "; ".join(errs[:3]))
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
        for slug in slugs:
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
                    pg.wait_for_timeout(300)
                    ok("메인 스크린 KPI 5개·차트 4개", pg.locator(".sc-kpi").count() == 5 and pg.locator(".sc-card .chart svg").count() == 4)
                    if SHOTS:
                        pg.screenshot(path=str(SHOTS / f"{slug}_screen.png"))
                    pg.keyboard.press("Escape")
                    pg.wait_for_timeout(200)
                    pg.click('[data-per="quarter"]')
                    pg.wait_for_timeout(200)
                    ok("개요 연간→분기 전환", pg.locator("#c1 text").filter(has_text="Q").count() > 0)
                    pg.click('[data-per="annual"]')
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
        b.close()
    srv.shutdown()
    print(f"\n결과: 실패 {len(fails)}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
