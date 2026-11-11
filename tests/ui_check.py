#!/usr/bin/env python3
"""
화면 점검 (선택) — 실제 브라우저로 모든 페이지를 열어 오류·빈 차트·클릭 동작을 확인합니다.

    pip install playwright && python -m playwright install chromium
    python tests/ui_check.py [사이트 폴더] [스크린샷 폴더]

사이트 폴더를 주지 않으면 이 저장소를 그대로 엽니다 (data/가 비어 있으면 '데이터 없음' 화면 점검).
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
PAGES = ["overview", "pl", "quarterly", "ratios", "bs", "stock", "industry", "audit"]
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
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    has_data = (ROOT / "data" / "financials.csv").exists()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
        for label, vp in (("PC", {"width": 1366, "height": 860}), ("모바일", {"width": 390, "height": 844})):
            print(f"\n[{label} {vp['width']}px]")
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
                pg.click(f'.nav-btn[data-page="{pid}"]')
                pg.wait_for_timeout(250)
                title = pg.inner_text("#pageTitle")
                charts = pg.locator(".chart").count()
                svgs = pg.locator(".chart svg").count()
                overflow = pg.evaluate("document.querySelector('.workspace').scrollWidth - document.querySelector('.workspace').clientWidth")
                ok(f"{pid} '{title}' 열림" + (f" · 차트 {svgs}/{charts}" if charts else ""), (svgs == charts) or not has_data, "")
                ok(f"{pid} 가로 넘침 없음", overflow <= 2, f"{overflow}px")
                if SHOTS:
                    SHOTS.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(SHOTS / f"{label}_{pid}.png"), full_page=label == "PC")
            if has_data and label == "PC":
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
                if SHOTS:
                    pg.screenshot(path=str(SHOTS / "PC_panel.png"))
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
