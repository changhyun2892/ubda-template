#!/usr/bin/env python3
"""
모든 기업을 한 번에 처리 → companies/<기업>/data/ + companies/index.json

    python scripts/run_all.py                    모든 기업: 수집 → 주가 → 계산 → 점검 → 기업 목록
    python scripts/run_all.py --only ottogi      한 기업만
    python scripts/run_all.py --steps build,verify   수집 없이 계산·점검만 (인터넷 없이 가능)

companies/ 아래에 company.json이 있는 폴더를 모두 기업으로 봅니다.
company.json에 "enabled": false 를 넣으면 건너뜁니다.
한 기업이 실패해도 다른 기업은 계속 진행합니다. 점검 '실패'가 있으면 마지막에 종료코드 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = {"collect": "collect_dart.py", "stock": "update_stock.py", "build": "build_dataset.py", "verify": "verify_data.py"}


def arg(name: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def main() -> int:
    steps = (arg("--steps") or "collect,stock,build,verify").split(",")
    only = arg("--only")
    slugs = []
    for p in sorted((ROOT / "companies").glob("*/company.json")):
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if cfg.get("enabled", True) is False:
            print(f"[건너뜀] {p.parent.name} (enabled=false)")
            continue
        if only and p.parent.name != only:
            continue
        slugs.append(p.parent.name)
    if not slugs:
        print("처리할 기업이 없습니다.")
        return 1
    failed = []
    for slug in slugs:
        print(f"\n===== {slug} =====", flush=True)
        for st in steps:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / STEPS[st]), "--company", slug], cwd=ROOT)
            if r.returncode != 0:
                failed.append(f"{slug}:{st}")
                if st != "verify":
                    print(f"[오류] {slug} {st} 단계 실패 — 이 기업의 다음 단계는 건너뜀", file=sys.stderr)
                    break
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_index.py")], cwd=ROOT, check=False)
    print("\n결과:", "모두 정상" if not failed else "실패 → " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
