"""NAVER API HUB 공통 호출 (검색어 트렌드·뉴스 검색). 키는 GitHub Secrets의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("NAVER_API_BASE", "https://naverapihub.apigw.ntruss.com")  # 테스트 때만 바꿈


class NaverError(RuntimeError):
    pass


def keys() -> tuple[str, str] | None:
    i, s = os.environ.get("NAVER_CLIENT_ID", "").strip(), os.environ.get("NAVER_CLIENT_SECRET", "").strip()
    return (i, s) if i and s else None


def call(path: str, params: dict | None = None, body: dict | None = None) -> dict:
    k = keys()
    if not k:
        raise NaverError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음")
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    last = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
            "X-NCP-APIGW-API-KEY-ID": k[0], "X-NCP-APIGW-API-KEY": k[1], "Content-Type": "application/json", "User-Agent": "ubda-dashboard"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            txt = e.read()[:300].decode("utf-8", "replace")
            if e.code in (401, 403):
                raise NaverError(f"인증 실패 {e.code} (키·구독 확인): {txt}") from None
            if e.code == 429:
                raise NaverError("하루 호출 한도 초과 (429)") from None
            if e.code == 400:
                raise NaverError(f"요청 오류 400: {txt}") from None
            last = f"{e.code} {txt}"
        except Exception as e:  # noqa: BLE001 — 네트워크 오류는 재시도
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise NaverError(f"{path} 요청 실패: {last}")
