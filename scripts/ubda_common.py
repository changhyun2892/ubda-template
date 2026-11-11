"""
UBDA 공통 도구 — 모든 스크립트가 함께 쓰는 설정 읽기·CSV 읽기/쓰기·로그·DART 요청.

기업마다 바뀌는 값은 저장소 맨 위의 company.json 한 곳에만 있습니다.
이 파일과 다른 스크립트에는 특정 기업 이름이나 종목코드를 적지 않습니다.
표준 라이브러리만 사용합니다 (pip 설치 불필요).
"""
from __future__ import annotations

import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"            # API에서 받은 그대로에 가까운 중간 결과
CONFIG = ROOT / "company.json"
LOG = DATA / "update_log.json"
KST = timezone(timedelta(hours=9))

# 검증 상태 — 화면·검증 스크립트·스킬이 모두 이 이름을 그대로 씁니다.
ST_VERIFIED = "원문 대조 일치"          # 사람이 공시 원문(PDF/뷰어)과 직접 대조
ST_AUTO = "자동 수집 · 원문 대조 전"    # 공식 API 값 그대로, 사람 대조는 아직
ST_UNCONFIRMED = "미확인"               # 찾지 못했거나 출처가 불충분
ST_UNDISCLOSED = "미공개"               # 회사가 공개하지 않는 항목
ST_MISMATCH = "불일치"                  # 대조 결과 값이 다름 — 화면에 경고


def now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


def load_config() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for k in ("company_id", "name", "industry"):
        if not cfg.get(k):
            raise SystemExit(f"company.json에 '{k}' 값이 없습니다.")
    cfg.setdefault("fs_div", "auto")
    cfg.setdefault("start_year", datetime.now(KST).year - 3)
    return cfg


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p: Path, cols: list[str], rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_log(key: str, info: dict) -> None:
    log = {}
    if LOG.exists():
        try:
            log = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log = {}
    log[key] = info
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def num(s) -> int | None:
    """DART 금액 문자열 → 정수. 빈칸·'-'는 None(=데이터 없음). 0으로 채우지 않는다."""
    if s is None:
        return None
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


class DartError(RuntimeError):
    pass


DART_BASE = os.environ.get("DART_BASE_URL", "https://opendart.fss.or.kr/api")  # 테스트 때만 바꿈


def dart_get(path: str, params: dict, raw: bool = False):
    url = f"{DART_BASE}/{path}?{urllib.parse.urlencode(params)}"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ubda-dashboard"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if raw:
                return body
            js = json.loads(body.decode("utf-8"))
            st = js.get("status")
            if st == "000":
                return js
            if st == "013":  # 조회된 데이터 없음
                return {"status": "013", "list": []}
            raise DartError(f"DART {path} 오류 {st}: {js.get('message')}")
        except DartError:
            raise
        except Exception as e:  # noqa: BLE001 — 네트워크 오류는 재시도
            last = e
            time.sleep(2 * (attempt + 1))
    raise DartError(f"DART {path} 요청 실패: {last}")
