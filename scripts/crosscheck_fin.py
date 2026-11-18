#!/usr/bin/env python3
"""
연간 재무 원문 자동 대조 — DART API 값이 사업보고서 원문의 재무제표 표에 실제로 있는지 프로그램이 찾는다.

    DART_API_KEY=발급키 python scripts/crosscheck_fin.py --company samyang

흐름
 1. data/raw/dart_financials.csv 의 연간(사업보고서) 값마다, 그 값을 준 보고서(접수번호)의 원본파일(document.xml)을 받는다.
    (연도별 1회만 받고 data/raw/finstmt_<연도>.txt 로 저장 · 같은 접수번호면 다시 받지 않음 · 한 번 실행에 최대 MAX_DL개)
 2. 'III. 재무에 관한 사항' 장 안의 '연결재무제표'(연결 값) 또는 '재무제표'(별도 값) 절만 표 텍스트로 뽑는다.
 3. 값 v(원)를 그 절에 적힌 단위(원·천원·백만원)로 나눈 수가 표 안에 있으면 '원문 자동 대조 일치'.
    어느 표(재무상태표·손익계산서·현금흐름표)에서 찾았는지 함께 기록한다. 같은 표 종류(BS·IS·CF)에서 찾은 것만 인정.
 4. 결과: data/fin_crosscheck.csv  → build_dataset.py가 검증 장부·화면 상태에 반영.

원칙
 - AI가 아니라 숫자 일치만 본다. '같은 행'까지는 확인하지 않는다(그래서 사람 대조와 다른 이름으로 표시).
 - 작은 값(원문 단위로 1,000 미만)은 우연히 맞을 수 있어 일치로 치지 않는다.
 - 키가 없거나 받기 실패면 기존 결과를 유지하고 경고만 남긴다.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile

from ubda_common import DATA, RAW, DartError, dart_get, load_config, now_kst, read_csv, write_csv, write_log
from collect_business_text import xml_to_text

MAX_DL = int(os.environ.get("FINCHECK_MAX_DL", "2"))      # 한 번 실행에 새로 받는 보고서 수 (시간 예산)
PARSER = 2   # 원문 추출 방식이 바뀌면 올림 → 예전 방식으로 저장한 파일은 다시 받음
III = re.compile(r"<TITLE[^>]*>\s*I{3}\.\s*재무에\s*관한\s*사항\s*</TITLE>", re.I)
IV = re.compile(r"<TITLE[^>]*>\s*IV\.\s*[^<]*</TITLE>", re.I)
TITLE = re.compile(r"<TITLE[^>]*>(.*?)</TITLE>", re.I | re.S)
NUM = re.compile(r"\(?-?\d{1,3}(?:,\d{3})+\)?|\(?-?\d{4,}\)?")
UNIT = re.compile(r"단위\s*[:：]?\s*(백만\s*원|천\s*원|원)")
SJ_WORDS = {"BS": ("재무상태표", "대차대조표"), "IS": ("손익계산서", "포괄손익"), "CIS": ("포괄손익", "손익계산서"), "CF": ("현금흐름표",)}
COLS = ["audit_id", "year", "metric", "value", "fs_div", "sj_div", "rcept_no", "result", "found_in", "unit", "note"]
ST_MATCH = "원문 자동 대조 일치"


def sections(x: str) -> dict[str, str]:
    """III장 안에서 연결재무제표·재무제표 절(주석 제외)의 원문 XML을 뽑는다."""
    s = III.search(x)
    if not s:
        return {}
    e = IV.search(x, s.end())
    body = x[s.start(): e.start() if e else len(x)]
    # 절 경계는 번호 붙은 제목(예: '3. 연결재무제표 주석')만. 재무제표 표 안에도 '연결 재무상태표' 같은 TITLE 태그가 있어 그건 경계가 아님
    ts = [t for t in TITLE.finditer(body) if re.match(r"\s*(\d+|[IVX]+)\.", re.sub(r"<[^>]+>", "", t.group(1)))]
    out = {}
    for i, t in enumerate(ts):
        name = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", t.group(1)))
        end = ts[i + 1].start() if i + 1 < len(ts) else len(body)
        if "주석" in name or "요약" in name:
            continue
        if re.fullmatch(r"\d+\.연결재무제표", name):
            out["CFS"] = body[t.start(): end]
        elif re.fullmatch(r"\d+\.재무제표", name):
            out["OFS"] = body[t.start(): end]
    return out


def to_int(tok: str) -> int | None:
    neg = tok.startswith("(") or tok.startswith("-")
    d = re.sub(r"[^\d]", "", tok)
    return (-int(d) if neg else int(d)) if d else None


def index_text(txt: str) -> list[tuple[str, str, int, set[int]]]:
    """표 텍스트를 '표 이름 → (단위, 숫자 집합)'으로. 단위·표 이름은 그 표 위쪽에서 가장 가까운 것."""
    blocks, cur_name, cur_unit, nums = [], "", 1, set()
    for line in txt.splitlines():
        u = UNIT.search(line)
        if u:
            cur_unit = {"원": 1, "천원": 1000, "백만원": 1_000_000}[re.sub(r"\s", "", u.group(1))]
        plain = line.replace(" | ", " ").strip()
        if plain and len(plain) < 40 and any(w in plain for ws in SJ_WORDS.values() for w in ws) and not NUM.search(plain.split("(")[0]):
            if nums:
                blocks.append((cur_name, "", cur_unit, nums))
            cur_name, nums = plain, set()
            continue
        for tok in NUM.findall(line):
            v = to_int(tok)
            if v is not None:
                nums.add(abs(v))
    if nums:
        blocks.append((cur_name, "", cur_unit, nums))
    return blocks


def match(v: int, sj: str, blocks) -> tuple[str, int] | None:
    words = SJ_WORDS.get(sj, ())
    for name, _, unit, nums in blocks:
        if words and not any(w in name for w in words):
            continue
        q = abs(v) / unit
        if q < 1000:                       # 작은 수는 우연 일치 가능
            continue
        if round(q) in nums or int(q) in nums or int(q) + 1 in nums:
            return name, unit
    return None


def fetch_text(key: str, rcept: str, alts: list[str]) -> tuple[str, str]:
    """보고서 원본에서 재무제표 절 텍스트. 원본이 없으면(status 014) 같은 연도의 다른 제출본."""
    tried = []
    for rn in [rcept] + [a for a in alts if a != rcept]:
        body = dart_get("document.xml", {"crtfc_key": key, "rcept_no": rn}, raw=True)
        try:
            z = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile:
            tried.append(rn)
            continue
        names = sorted(z.namelist(), key=lambda n: (n != f"{rn}.xml", len(n)))
        for n in names:
            raw = z.read(n)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    x = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            sec = sections(x)
            if sec:
                parts = []
                for div in ("CFS", "OFS"):
                    if div in sec:
                        parts.append(f"=== {div} ===\n" + xml_to_text(sec[div]))
                return "\n\n".join(parts), rn
        raise DartError(f"{rn}: 'III. 재무에 관한 사항'의 재무제표 절을 찾지 못함")
    raise DartError("원본파일 없음: " + ", ".join(tried))


def main() -> int:
    cfg = load_config()
    key = os.environ.get("DART_API_KEY", "").strip()
    now = now_kst()
    min_year = int(cfg.get("start_year", 0)) - 1
    fin = [r for r in read_csv(RAW / "dart_financials.csv") if r["reprt_code"] == "11011" and int(r["bsns_year"]) >= min_year]
    if not fin:
        print("[안내] 연간 재무가 없습니다 — collect_dart.py를 먼저 실행하세요.")
        return 0
    reports = read_csv(RAW / "dart_reports.csv")
    meta_p = RAW / "finstmt.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    years = sorted({r["bsns_year"] for r in fin}, reverse=True)
    dl, msgs = 0, []
    for y in years:
        rcept = next(r["rcept_no"] for r in fin if r["bsns_year"] == y)
        f = RAW / f"finstmt_{y}.txt"
        if f.exists() and meta.get(y, {}).get("for") == rcept and meta.get(y, {}).get("parser") == PARSER:
            continue
        if not key:
            msgs.append(f"{y}: DART_API_KEY 없음")
            continue
        if dl >= MAX_DL:
            msgs.append(f"{y}: 다음 실행으로 미룸(한 번에 {MAX_DL}개)")
            continue
        alts = [r["rcept_no"] for r in sorted(reports, key=lambda r: r["rcept_dt"], reverse=True) if r["bsns_year"] == y and r["reprt_code"] == "11011"]
        try:
            txt, used = fetch_text(key, rcept, alts)
            dl += 1
        except DartError as e:
            msgs.append(f"{y}: {e}")
            continue
        rep = next((r for r in reports if r["rcept_no"] == used), {})
        f.write_text(f"# {cfg['name']} {rep.get('report_nm', '')} — III. 재무에 관한 사항 중 재무제표 절 (원문 텍스트)\n"
                     f"# 접수번호 {used} · 원문 {rep.get('viewer_url', '')} · 저장 {now}\n\n" + txt + "\n", encoding="utf-8")
        meta[y] = {"for": rcept, "rcept_no": used, "saved_at": now, "chars": len(txt), "parser": PARSER}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows, n_ok = [], 0
    cache: dict[str, dict] = {}
    for r in fin:
        y = r["bsns_year"]
        if y not in cache:
            p = RAW / f"finstmt_{y}.txt"
            txt = p.read_text(encoding="utf-8") if p.exists() and meta.get(y, {}).get("parser") == PARSER else ""
            cache[y] = {div: index_text(part) for div, part in re.findall(r"=== (CFS|OFS) ===\n(.*?)(?=\n=== |\Z)", txt, re.S)}
        try:
            v = int(float(r["value"]))
        except ValueError:
            continue
        aid = f"F-{y}-{r['metric']}"
        blocks = cache[y].get(r["fs_div"])
        res, found, unit, note = "", "", "", ""
        if not cache[y]:
            note = "원문 재무제표를 아직 받지 못함"
        elif blocks is None:
            note = f"원문에 {'연결' if r['fs_div'] == 'CFS' else '별도'}재무제표 절이 없음"
        else:
            m = match(v, r["sj_div"], blocks)
            if m:
                res, found, unit = ST_MATCH, m[0], {1: "원", 1000: "천원", 1_000_000: "백만원"}[m[1]]
                n_ok += 1
            else:
                note = "원문 표에서 같은 숫자를 찾지 못함 (재분류·합산 계정이거나 표기 차이)"
        rows.append({"audit_id": aid, "year": y, "metric": r["metric"], "value": v, "fs_div": r["fs_div"], "sj_div": r["sj_div"],
                     "rcept_no": meta.get(y, {}).get("rcept_no", r["rcept_no"]), "result": res, "found_in": found, "unit": unit, "note": note})
    write_csv(DATA / "fin_crosscheck.csv", COLS, rows)
    write_log("fincheck", {"status": "성공" if not msgs else "일부", "checked_at": now, "matched": n_ok, "total": len(rows), "message": "; ".join(msgs)[:300]})
    print(f"원문 자동 대조: {n_ok}/{len(rows)} 일치" + (f" · {'; '.join(msgs)}" if msgs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
