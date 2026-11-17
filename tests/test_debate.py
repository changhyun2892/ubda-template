"""
기업 토론 생성 점검 — 실제 AI를 부르지 않고 가짜 API 서버로 확인합니다.

  python tests/test_debate.py

확인하는 것
  1) 데이터 시트에 출처 표시가 붙고, 프롬프트의 자리표시가 모두 채워진다
  2) 데이터에 없는 숫자를 쓴 응답은 거절되고, 한 번 다시 요청한다
  3) 다시 받은 올바른 응답은 debate/<월>.json 과 index.json 으로 저장된다
  4) 끝까지 틀린 응답은 저장하지 않는다
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FAILS = 0


def ok(name, cond, detail=""):
    global FAILS
    print(("  ✔ " if cond else "  ✗ ") + name + (f" — {detail}" if detail and not cond else ""))
    FAILS += 0 if cond else 1


def answer(bad_number: bool) -> str:
    n = "99,999.9억원" if bad_number else "23,517.9억원"
    roles = ["약세론자", "본질 분석가", "기회 탐색가", "외부자", "점검 담당"]
    adv = [{"role": r, "reply_to": None if i == 0 else roles[i - 1], "stance": "없음" if i == 0 else "반박",
            "text": f"테스트 발언 {i}. 매출액은 {n}입니다 (재무 · 2025).", "sources": ["재무 · 2025"]} for i, r in enumerate(roles)]
    return "```json\n" + json.dumps({"topic": "테스트", "advisors": adv, "dropped": [], "conclusion": "테스트 결론",
                                      "confidence": 55, "confidence_basis": "테스트", "to_check": ["다음 분기"],
                                      "disclaimer": "수업용 경영분석이며 투자 추천이 아닙니다."}, ensure_ascii=False) + "\n```"


class Fake(http.server.BaseHTTPRequestHandler):
    mode = "bad-then-good"
    calls = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        Fake.calls += 1
        bad = Fake.mode == "always-bad" or (Fake.mode == "bad-then-good" and len(body["messages"]) == 1)
        out = {"content": [{"type": "text", "text": answer(bad)}]}
        b = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)


def main():
    import build_debate as bd
    print("[데이터 시트]")
    sheet, meta = bd.fact_sheet("samyang", json.loads((ROOT / "companies/index.json").read_text(encoding="utf-8")))
    lines = [l for l in sheet.splitlines() if l.startswith("- ")]
    ok("모든 데이터 줄에 출처 표시 [..]", all(l.rstrip().endswith("]") for l in lines), next((l for l in lines if not l.rstrip().endswith("]")), ""))
    p = bd.build_prompt(sheet, meta, None)
    ok("프롬프트 자리표시가 모두 채워짐", "{{" not in p)
    ok("검사: 지어낸 숫자 거절", bool(bd.validate(json.loads(answer(True).strip("`json\n")), sheet)))
    ok("검사: 데이터의 숫자는 통과 (반올림 포함)", bd.number_ok("23,517.9", bd.number_pool(sheet)) and bd.number_ok("2.4", bd.number_pool(sheet)))

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ddir = ROOT / "companies/samyang/data/debate"
    backup = None
    if ddir.exists():
        backup = ROOT / ".debate_backup"; shutil.rmtree(backup, ignore_errors=True); shutil.copytree(ddir, backup); shutil.rmtree(ddir)
    log = ROOT / "companies/debate_log.json"
    log_bak = log.read_text(encoding="utf-8") if log.exists() else None
    allidx = ROOT / "companies/debate_index.json"
    allidx_bak = allidx.read_text(encoding="utf-8") if allidx.exists() else None
    env = dict(os.environ, ANTHROPIC_API_KEY="test", DEBATE_API_URL=f"http://127.0.0.1:{srv.server_address[1]}/v1/messages")
    try:
        print("[틀린 숫자 → 다시 요청 → 저장]")
        Fake.mode, Fake.calls = "bad-then-good", 0
        r = subprocess.run([sys.executable, "scripts/build_debate.py", "--only", "samyang", "--month", "2099-01"], cwd=ROOT, env=env, capture_output=True, text=True)
        f = ddir / "2099-01.json"
        ok("두 번 호출(재요청)", Fake.calls == 2, f"{Fake.calls}회 · {r.stdout[-300:]}")
        ok("월별 파일 저장", f.exists(), r.stdout[-300:] + r.stderr[-300:])
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            ok("고문 5명·메타 포함", len(d["advisors"]) == 5 and d["meta"]["month"] == "2099-01")
        idx = json.loads((ddir / "index.json").read_text(encoding="utf-8")) if (ddir / "index.json").exists() else {}
        ok("index.json 월 목록", idx.get("months") == ["2099-01"], str(idx))
        al = json.loads(allidx.read_text(encoding="utf-8")) if allidx.exists() else {}
        ok("debate_index.json 에 기업 월 목록", al.get("samyang") == ["2099-01"], str(al)[:200])

        print("[끝까지 틀리면 저장 안 함]")
        Fake.mode, Fake.calls = "always-bad", 0
        r = subprocess.run([sys.executable, "scripts/build_debate.py", "--only", "samyang", "--month", "2099-02"], cwd=ROOT, env=env, capture_output=True, text=True)
        ok("저장하지 않음", not (ddir / "2099-02.json").exists())
        ok("로그에 검증 실패", "검증 실패" in r.stdout, r.stdout[-300:])

        print("[키 없으면 조용히 건너뜀]")
        r = subprocess.run([sys.executable, "scripts/build_debate.py", "--only", "samyang"], cwd=ROOT, env={k: v for k, v in env.items() if k != "ANTHROPIC_API_KEY"}, capture_output=True, text=True)
        ok("키 없음 → 종료코드 0·안내", r.returncode == 0 and "ANTHROPIC_API_KEY" in r.stdout)
    finally:
        shutil.rmtree(ddir, ignore_errors=True)
        if backup:
            shutil.copytree(backup, ddir); shutil.rmtree(backup)
        if allidx_bak is None:
            allidx.unlink(missing_ok=True)
        else:
            allidx.write_text(allidx_bak, encoding="utf-8")
        if log_bak is None:
            log.unlink(missing_ok=True)
        else:
            log.write_text(log_bak, encoding="utf-8")
        srv.shutdown()
    print(f"\n결과: 실패 {FAILS}건")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
