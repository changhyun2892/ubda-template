#!/usr/bin/env python3
"""
사업보고서 본문 텍스트 저장 → data/raw/business_<연도>.txt

    DART_API_KEY=발급키 python scripts/collect_business_text.py --company ottogi

산업 KPI(제품군 매출·수출·원재료 가격·생산능력·가동률 등)는 재무제표 API에 없고 사업보고서 본문 표에만 있습니다.
OpenDART '공시서류 원본파일(document.xml)' API로 최신 사업보고서를 받아,
'II. 사업의 내용' 장만 표 구조(| 와 줄바꿈)를 살린 텍스트로 저장합니다.
AI나 사람이 이 파일을 읽고 data/manual/kpi_values.csv에 출처와 함께 옮깁니다 (값을 자동으로 추출하지는 않음).

 - 이미 저장한 보고서(같은 접수번호)는 다시 받지 않습니다.
 - 키가 없거나 실패하면 기존 파일을 그대로 두고 경고만 남깁니다.
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import sys
import zipfile

from ubda_common import RAW, DartError, dart_get, load_config, now_kst, read_csv, write_log

START = re.compile(r"<TITLE[^>]*>\s*I{2}\.\s*사업의\s*내용\s*</TITLE>", re.I)
END = re.compile(r"<TITLE[^>]*>\s*I{3}\.\s*재무에\s*관한\s*사항\s*</TITLE>", re.I)


def xml_to_text(x: str) -> str:
    """DART XML(dart4.xsd) → 읽기 쉬운 텍스트. 표는 셀을 ' | ', 행을 줄바꿈으로."""
    x = re.sub(r"<(TD|TH|TE|TU)\b[^>]*>", "", x, flags=re.I)
    x = re.sub(r"</(TD|TH|TE|TU)>", " | ", x, flags=re.I)
    x = re.sub(r"</TR>", "\n", x, flags=re.I)
    x = re.sub(r"<TABLE\b[^>]*>", "\n[표]\n", x, flags=re.I)
    x = re.sub(r"</TABLE>", "[표 끝]\n", x, flags=re.I)
    x = re.sub(r"<TITLE\b[^>]*>", "\n\n## ", x, flags=re.I)
    x = re.sub(r"</(TITLE|P|SPAN|TABLE-GROUP)>|<BR\s*/?>", "\n", x, flags=re.I)
    x = re.sub(r"<[^>]+>", "", x)
    x = html.unescape(x)
    x = re.sub(r"[ \t ]+", " ", x)
    x = re.sub(r" ?\| ?\n", " |\n", x)
    x = re.sub(r"\n\s*\n\s*\n+", "\n\n", x)
    return x.strip()


def main() -> int:
    cfg = load_config()
    key = os.environ.get("DART_API_KEY", "").strip()
    now = now_kst()
    reps = [r for r in read_csv(RAW / "dart_reports.csv") if r.get("reprt_code") == "11011"]
    if not reps:
        print("[안내] 사업보고서 기록이 없습니다 — collect_dart.py를 먼저 실행하세요.")
        return 0
    rep = sorted(reps, key=lambda r: (r["bsns_year"], r["rcept_dt"]))[-1]
    out = RAW / f"business_{rep['bsns_year']}.txt"
    meta = RAW / "business_text.json"
    m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    if out.exists() and m.get(rep["bsns_year"], {}).get("rcept_no") == rep["rcept_no"]:
        print(f"이미 저장됨: {out.name} ({rep['report_nm']})")
        return 0
    if not key:
        print("[경고] DART_API_KEY 없음 — 사업보고서 본문 저장을 건너뜁니다.", file=sys.stderr)
        return 0
    try:
        body = dart_get("document.xml", {"crtfc_key": key, "rcept_no": rep["rcept_no"]}, raw=True)
        try:
            z = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile:
            raise DartError("원본파일 대신 오류 응답: " + body[:200].decode("utf-8", "replace")) from None
        # 본문은 보통 '<접수번호>.xml' (첨부·감사보고서는 '_00760' 같은 꼬리가 붙음)
        names = sorted(z.namelist(), key=lambda n: (n != f"{rep['rcept_no']}.xml", len(n)))
        txt = ""
        for n in names:
            raw = z.read(n)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    x = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            s, e = START.search(x), END.search(x)
            if s:
                txt = xml_to_text(x[s.start(): e.start() if e and e.start() > s.start() else len(x)])
                break
        if not txt:
            raise DartError("'II. 사업의 내용' 장을 찾지 못했습니다")
    except DartError as e:
        print(f"[경고] {e}", file=sys.stderr)
        write_log("business_text", {"status": "실패", "checked_at": now, "message": str(e)[:200]})
        return 0
    head = (f"# {cfg['name']} {rep['report_nm']} — II. 사업의 내용 (본문 텍스트)\n"
            f"# 접수번호 {rep['rcept_no']} · 접수일 {rep['rcept_dt']} · 원문 {rep['viewer_url']}\n"
            f"# OpenDART document.xml에서 자동 추출 ({now}). 표는 ' | '로 구분. 숫자 단위는 각 표의 원문 단위를 따름.\n\n")
    out.write_text(head + txt + "\n", encoding="utf-8")
    m[rep["bsns_year"]] = {"rcept_no": rep["rcept_no"], "report_nm": rep["report_nm"], "viewer_url": rep["viewer_url"], "saved_at": now, "chars": len(txt)}
    meta.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_log("business_text", {"status": "성공", "checked_at": now, "report": rep["report_nm"], "chars": len(txt)})
    print(f"저장: {out.name} ({len(txt):,}자)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
