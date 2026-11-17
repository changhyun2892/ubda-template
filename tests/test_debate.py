"""
기업 토론 검사·저장 점검 (AI 호출 없음)

  python tests/test_debate.py

확인하는 것
  1) 데이터 시트의 모든 줄에 출처 표시가 붙고, 프롬프트 자리표시가 모두 채워진다
  2) 데이터에 없는 숫자를 쓴 토론은 거절되고 저장되지 않는다
  3) 올바른 토론은 debate/<월>.json, debate/index.json, companies/debate_index.json 에 반영된다
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FAILS = 0


def ok(name, cond, detail=""):
    global FAILS
    print(("  ✔ " if cond else "  ✗ ") + name + (f" — {detail}" if detail and not cond else ""))
    FAILS += 0 if cond else 1


def sample(bad: bool) -> dict:
    n = "99,999.9억원" if bad else "23,517.9억원"
    roles = ["약세론자", "본질 분석가", "기회 탐색가", "외부자", "점검 담당"]
    adv = [{"role": r, "reply_to": None if i == 0 else roles[i - 1], "stance": "없음" if i == 0 else "반박",
            "text": f"테스트 발언. 매출액은 {n}입니다 (재무 · 2025).", "sources": ["재무 · 2025"]} for i, r in enumerate(roles)]
    return {"topic": "테스트", "advisors": adv, "dropped": [], "conclusion": "테스트 결론", "confidence": 55,
            "confidence_basis": "테스트", "to_check": ["다음 분기"], "disclaimer": "수업용 경영분석이며 투자 추천이 아닙니다."}


def main():
    import build_debate as bd
    print("[데이터 시트·프롬프트]")
    sheet, meta = bd.fact_sheet("samyang", json.loads((ROOT / "companies/index.json").read_text(encoding="utf-8")))
    lines = [l for l in sheet.splitlines() if l.startswith("- ")]
    ok("모든 데이터 줄에 출처 표시 [..]", all(l.rstrip().endswith("]") for l in lines), next((l for l in lines if not l.rstrip().endswith("]")), ""))
    ok("프롬프트 자리표시가 모두 채워짐", "{{" not in bd.build_prompt(sheet, meta, None))
    ok("검사: 데이터의 숫자는 통과 (반올림 포함)", not bd.validate(sample(False), sheet))
    ok("검사: 지어낸 숫자 거절", bool(bd.validate(sample(True), sheet)))

    ddir = ROOT / "companies/samyang/data/debate"
    allidx = ROOT / "companies/debate_index.json"
    tmp = Path(tempfile.mkdtemp())
    bak = tmp / "bak"
    if ddir.exists():
        shutil.copytree(ddir, bak)
    allidx_bak = allidx.read_text(encoding="utf-8") if allidx.exists() else None
    run = lambda *a: subprocess.run([sys.executable, "scripts/build_debate.py", *a], cwd=ROOT, capture_output=True, text=True)
    try:
        print("[저장]")
        (tmp / "bad.json").write_text(json.dumps(sample(True), ensure_ascii=False), encoding="utf-8")
        r = run("--save", "samyang", str(tmp / "bad.json"), "--month", "2099-02")
        ok("틀린 숫자 → 저장 거부(종료코드 1)", r.returncode == 1 and not (ddir / "2099-02.json").exists(), r.stdout[-200:])
        (tmp / "good.json").write_text("```json\n" + json.dumps(sample(False), ensure_ascii=False) + "\n```", encoding="utf-8")
        r = run("--save", "samyang", str(tmp / "good.json"), "--month", "2099-01")
        ok("올바른 토론 → 저장", r.returncode == 0 and (ddir / "2099-01.json").exists(), r.stdout[-200:] + r.stderr[-200:])
        idx = json.loads((ddir / "index.json").read_text(encoding="utf-8")) if (ddir / "index.json").exists() else {}
        ok("debate/index.json 월 목록", "2099-01" in idx.get("months", []), str(idx))
        al = json.loads(allidx.read_text(encoding="utf-8")) if allidx.exists() else {}
        ok("debate_index.json 에 기업 월 목록", "2099-01" in al.get("samyang", []), str(al)[:200])
        ok("--todo 목록 출력", "토론이 없는 기업" in run("--todo").stdout)
    finally:
        shutil.rmtree(ddir, ignore_errors=True)
        if bak.exists():
            shutil.copytree(bak, ddir)
        if allidx_bak is None:
            allidx.unlink(missing_ok=True)
        else:
            allidx.write_text(allidx_bak, encoding="utf-8")
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n결과: 실패 {FAILS}건")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
