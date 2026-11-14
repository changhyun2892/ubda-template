/* UBDA 공통 대시보드
 * company.json + data/*.csv만 읽어 화면을 그립니다. 특정 기업 이름·수치는 이 파일에 없습니다.
 * 구성: 1) 데이터 읽기  2) 계산·형식 도우미  3) 차트(SVG)  4) 근거 패널  5) 페이지  6) 시작
 * 외부 라이브러리 없음 (인터넷 없이도 동작).
 */
'use strict';

/* ---------------- 1) 데이터 읽기 ---------------- */
// 주소 dashboard.html?c=<기업폴더> → companies/<기업폴더>/ 의 파일을 읽음
const SLUG = (new URLSearchParams(location.search).get('c') || '').replace(/[^a-z0-9_-]/gi, '');
const FILE_MAP = {
  company: 'company.json', summary: 'data/summary.json', verify: 'data/verify_report.json', log: 'data/update_log.json',
  fin: 'data/financials.csv', qtr: 'data/quarterly.csv', met: 'data/metrics.csv', ledger: 'data/audit_ledger.csv',
  reg: 'data/source_registry.csv', status: 'data/research_status.csv', kpi: 'data/manual/kpi_values.csv', stock: 'data/stock_daily.csv',
  reports: 'data/raw/dart_reports.csv', events: 'data/events_auto.csv', evlinks: 'data/event_links.csv',
};
const COMPARE_KEYS = ['company', 'summary', 'fin', 'met', 'qtr', 'ledger', 'reg'];

function parseCSV(text) {
  const rows = []; let row = [], cell = '', q = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  const head = rows.shift() || [];
  return rows.filter((r) => r.length > 1 || r[0] !== '').map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ''])));
}

async function loadAll(slug = SLUG, keys = Object.keys(FILE_MAP)) {
  const out = {};
  await Promise.all(keys.map((k) => [k, `companies/${slug}/${FILE_MAP[k]}`]).map(async ([k, url]) => {
    try {
      const r = await fetch(url, { cache: 'no-cache' });
      if (!r.ok) throw new Error(r.status);
      const t = await r.text();
      out[k] = url.endsWith('.json') ? JSON.parse(t) : parseCSV(t);
    } catch (e) { out[k] = url.endsWith('.json') ? null : []; }
  }));
  if (keys.includes('status') && out.company?.industry) {
    try { out.industry = await (await fetch(`industries/${out.company.industry}.json`, { cache: 'no-cache' })).json(); } catch (e) { out.industry = null; }
  }
  return out;
}

/* ---------------- 2) 계산·형식 도우미 ---------------- */
let D = {}; // 읽은 데이터
const S = { page: 'overview', year: null, qmetric: 'revenue', stockMode: 'index', ledgerFilter: 'all', period: 'annual', cmp: null, edit: false };
let INDEX = null; // companies/index.json (기업 비교·질의용)
const OTHER = {}; // 다른 기업 데이터 캐시
const N = (s) => (s === undefined || s === null || s === '' ? null : Number(s));
const nf = (d) => new Intl.NumberFormat('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '데이터 없음' : nf(d).format(v));
const eok = (v, d = 1) => (v === null || v === undefined ? '데이터 없음' : fmt(v / 1e8, d) + '억원');
const pct = (v, d = 1) => (v === null || v === undefined ? '데이터 없음' : fmt(v, d) + '%');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const growth = (c, p) => (c === null || p === null || p <= 0 ? null : (c / p - 1) * 100);
const $ = (s) => document.querySelector(s);

const fin = (y, m) => N(D.fin.find((r) => +r.year === y && r.metric === m)?.value);
const finRow = (y, m) => D.fin.find((r) => +r.year === y && r.metric === m);
const metRow = (y, k) => D.met.find((r) => +r.year === y && r.metric === k);
const met = (y, k) => N(metRow(y, k)?.value);
const YEARS = () => [...new Set(D.fin.map((r) => +r.year))].sort();
const LEDGER = () => new Map(D.ledger.map((r) => [r.audit_id, r]));
const REG = () => new Map(D.reg.map((r) => [r.source_id, r]));

const ST_CLASS = { '원문 대조 일치': 'st-ok', '자동 수집 · 원문 대조 전': 'st-auto', '미확인': 'st-na', '미공개': 'st-na', '불일치': 'st-bad', '통과': 'st-ok', '실패': 'st-bad', '경고': 'st-warn', '미실행': 'st-na' };
const ST_SHORT = { '자동 수집 · 원문 대조 전': '자동 · 대조 전' };
const badge = (s) => `<span class="st ${ST_CLASS[s] || 'st-na'}" title="${esc(s)}">${esc(ST_SHORT[s] || s || '미확인')}</span>`;
const pill = (v, unit = '%', d = 1) => `<span class="pill ${v === null ? 'na' : v > 0 ? 'up' : v < 0 ? 'down' : 'na'}">${v === null ? '전년 비교 없음' : (v > 0 ? '▲ ' : v < 0 ? '▼ ' : '') + fmt(Math.abs(v), d) + unit}</span>`;

/* ---------------- 3) 차트 (SVG) ---------------- */
const tip = { el: null, show(e, html) { this.el.innerHTML = html; this.el.classList.add('on'); const x = Math.min(e.clientX + 12, innerWidth - 270); this.el.style.left = x + 'px'; this.el.style.top = e.clientY + 12 + 'px'; }, hide() { this.el.classList.remove('on'); } };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const COLORS = () => [css('--accent'), css('--s2'), css('--s3'), css('--s4'), css('--s5')];

function niceTicks(min, max, n = 4) {
  if (min === max) { max = min + 1; }
  const step0 = (max - min) / n, mag = 10 ** Math.floor(Math.log10(Math.abs(step0)));
  const step = [1, 2, 2.5, 5, 10].map((s) => s * mag).find((s) => s >= step0) || step0;
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step, t = [];
  for (let v = lo; v <= hi + step / 2; v += step) t.push(+v.toPrecision(12));
  return t;
}

/** 막대(+선) 차트. bars: [{name,color,values}], line: {name,color,values,fmt}|null, opt: {fmt, stacked, onClick(i,seriesIndex)} */
function barLine(el, cats, bars, line, opt = {}) {
  if (!el) return; // 데이터가 없어 차트 자리가 없는 페이지
  const W = Math.max(280, el.clientWidth || 500), H = opt.h || 230, m = { t: 12, r: line ? 46 : 12, b: 26, l: 56 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const vals = opt.stacked ? cats.map((_, i) => bars.reduce((s, b) => s + (b.values[i] || 0), 0)) : bars.flatMap((b) => b.values).filter((v) => v !== null);
  if (!vals.length) { el.innerHTML = '<div class="empty"><b>데이터 없음</b>아직 수집된 값이 없습니다.</div>'; return; }
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1], Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;
  const bw = iw / cats.length, gw = bw * 0.7, sw = opt.stacked ? gw : gw / bars.length;
  const f = opt.fmt || ((v) => fmt(v / 1e8, 0));
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(opt.label || '')}">`;
  ticks.forEach((t) => { s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="${t === 0 ? '#c9c3b8' : '#eeeae4'}"/><text x="${m.l - 6}" y="${Y(t) + 3}" text-anchor="end">${f(t)}</text>`; });
  cats.forEach((c, i) => {
    let acc = 0;
    bars.forEach((b, j) => {
      const v = b.values[i]; if (v === null || v === undefined) return;
      const x = m.l + i * bw + (bw - gw) / 2 + (opt.stacked ? 0 : j * sw);
      const top = opt.stacked ? Y(acc + v) : Y(Math.max(0, v)), bot = opt.stacked ? Y(acc) : Y(Math.min(0, v));
      if (opt.stacked) acc += v;
      s += `<rect class="bar" data-i="${i}" data-j="${j}" x="${x + 1}" y="${top}" width="${Math.max(1, sw - 2)}" height="${Math.max(1, bot - top)}" rx="2" fill="${b.color}"/>`;
    });
    s += `<text x="${m.l + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(c)}</text>`;
  });
  if (line) {
    const lv = line.values.filter((v) => v !== null);
    if (lv.length) {
      const lt = niceTicks(Math.min(0, ...lv), Math.max(...lv)), l0 = lt[0], l1 = lt[lt.length - 1], LY = (v) => m.t + ih - ((v - l0) / (l1 - l0)) * ih;
      lt.forEach((t) => { s += `<text x="${W - m.r + 6}" y="${LY(t) + 3}">${fmt(t, 0)}${line.unit || ''}</text>`; });
      const pts = line.values.map((v, i) => (v === null ? null : [m.l + i * bw + bw / 2, LY(v)]));
      let d = ''; pts.forEach((p, i) => { if (p) d += (d && pts[i - 1] ? 'L' : 'M') + p[0] + ',' + p[1]; });
      s += `<path d="${d}" fill="none" stroke="${line.color}" stroke-width="2"/>`;
      pts.forEach((p, i) => { if (p) s += `<circle class="bar" data-i="${i}" data-j="L" cx="${p[0]}" cy="${p[1]}" r="3.5" fill="#fff" stroke="${line.color}" stroke-width="2"/>`; });
    }
  }
  el.innerHTML = s + '</svg>';
  el.querySelectorAll('.bar').forEach((r) => {
    const i = +r.dataset.i, j = r.dataset.j;
    const html = () => `<b>${esc(cats[i])}</b><br>` + bars.map((b) => `${esc(b.name)}: ${b.values[i] === null ? '데이터 없음' : (opt.tipFmt || eok)(b.values[i])}`).join('<br>') + (line ? `<br>${esc(line.name)}: ${line.values[i] === null ? '데이터 없음' : (line.fmt || pct)(line.values[i])}` : '') + (opt.onClick ? '<br><i>클릭: 근거 보기</i>' : '');
    r.addEventListener('mousemove', (e) => tip.show(e, html()));
    r.addEventListener('mouseleave', () => tip.hide());
    if (opt.onClick) r.addEventListener('click', () => opt.onClick(i, j));
  });
}

/** 날짜 선 차트. series: [{name,color,values}] (xs와 같은 길이), markers: [{date,label,url}] */
function lineChart(el, xs, series, markers = [], opt = {}) {
  if (!el) return;
  const W = Math.max(280, el.clientWidth || 500), H = opt.h || 260, m = { t: 12, r: 12, b: 26, l: 56 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const all = series.flatMap((s) => s.values).filter((v) => v !== null && !Number.isNaN(v));
  if (!all.length) { el.innerHTML = '<div class="empty"><b>데이터 없음</b>주가가 아직 수집되지 않았습니다.</div>'; return; }
  const ticks = niceTicks(Math.min(...all), Math.max(...all)), y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = (i) => m.l + (i / Math.max(1, xs.length - 1)) * iw, Y = (v) => m.t + ih - ((v - y0) / (y1 - y0)) * ih;
  const f = opt.fmt || ((v) => fmt(v, 0));
  let s = `<svg viewBox="0 0 ${W} ${H}">`;
  ticks.forEach((t) => { s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#eeeae4"/><text x="${m.l - 6}" y="${Y(t) + 3}" text-anchor="end">${f(t)}</text>`; });
  const years = [...new Set(xs.map((x) => x.slice(0, 4)))];
  years.forEach((y) => { const i = xs.findIndex((x) => x.startsWith(y)); s += `<text x="${X(i)}" y="${H - 8}">${y}</text>`; });
  const idx = new Map(xs.map((x, i) => [x, i]));
  markers.forEach((mk) => {
    let i = idx.get(mk.date); if (i === undefined) i = xs.findIndex((x) => x >= mk.date); if (i < 0) return;
    s += `<line class="mk" data-l="${esc(mk.label)}" x1="${X(i)}" x2="${X(i)}" y1="${m.t}" y2="${m.t + ih}" stroke="${css('--s5')}" stroke-dasharray="2 3" opacity=".55" stroke-width="2"/>`;
  });
  series.forEach((se) => {
    let d = '', pen = false;
    se.values.forEach((v, i) => { if (v === null || Number.isNaN(v)) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(v).toFixed(1); pen = true; });
    s += `<path d="${d}" fill="none" stroke="${se.color}" stroke-width="1.6"/>`;
  });
  s += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/><line class="cur" y1="${m.t}" y2="${m.t + ih}" stroke="#999" opacity="0"/>`;
  (opt.dots || []).forEach((dt) => { // 급변일 점 (첫 번째 선 위). 클릭하면 opt.onDot(key)
    const i = idx.get(dt.date), v = i === undefined ? null : series[0].values[i]; if (v === null || v === undefined) return;
    s += `<circle class="dot" data-key="${esc(dt.key)}" data-l="${esc(dt.label)}" cx="${X(i)}" cy="${Y(v)}" r="${dt.big ? 5.5 : 4}" fill="${dt.color}" stroke="#fff" stroke-width="1.5" style="cursor:pointer"/>`;
  });
  el.innerHTML = s + '</svg>';
  const svg = el.querySelector('svg'), cur = el.querySelector('.cur');
  el.querySelector('.hit').addEventListener('mousemove', (e) => {
    const b = svg.getBoundingClientRect(), x = ((e.clientX - b.left) / b.width) * W, i = Math.max(0, Math.min(xs.length - 1, Math.round(((x - m.l) / iw) * (xs.length - 1))));
    cur.setAttribute('x1', X(i)); cur.setAttribute('x2', X(i)); cur.setAttribute('opacity', 1);
    tip.show(e, `<b>${xs[i]}</b><br>` + series.map((se) => `${esc(se.name)}: ${se.values[i] === null ? '-' : f(se.values[i])}`).join('<br>'));
  });
  el.querySelector('.hit').addEventListener('mouseleave', () => { tip.hide(); cur.setAttribute('opacity', 0); });
  el.querySelectorAll('.mk').forEach((l) => { l.addEventListener('mousemove', (e) => tip.show(e, esc(l.dataset.l))); l.addEventListener('mouseleave', () => tip.hide()); });
  el.querySelectorAll('.dot').forEach((c) => {
    c.addEventListener('mousemove', (e) => tip.show(e, esc(c.dataset.l).replace(/\n/g, '<br>'))); c.addEventListener('mouseleave', () => tip.hide());
    c.addEventListener('click', () => { tip.hide(); opt.onDot && opt.onDot(c.dataset.key); });
  });
}

const legend = (items) => `<div class="legend">${items.map(([n, c]) => `<span><i style="background:${c}"></i>${esc(n)}</span>`).join('')}</div>`;

/* ---------------- 4) 근거 패널 ---------------- */
function openPanel(html) { $('#panelIn').innerHTML = html; $('#app').classList.add('panel-open'); $('#panelIn').querySelector('.x')?.addEventListener('click', closePanel); }
function closePanel() { $('#app').classList.remove('panel-open'); }

function evidenceHTML(aid) {
  const a = LEDGER().get(aid); if (!a) return `<div class="ev-box">검증번호 ${esc(aid)} 기록 없음</div>`;
  const src = REG().get(a.source_id);
  return `<dl class="ev-box"><dt>검증번호</dt><dd>${esc(aid)} ${badge(a.result)}</dd>
    <dt>출처</dt><dd>${src ? `<a href="${esc(src.source_url)}" target="_blank" rel="noopener">${esc(src.title)}</a>` : esc(a.source_id || '없음')}</dd>
    <dt>원문 위치</dt><dd>${esc(a.source_location)}</dd><dt>방법</dt><dd>${esc(a.method)}</dd>
    <dt>확인</dt><dd>${esc(a.checked_by)} · ${esc(a.checked_on)}</dd>${a.note ? `<dt>메모</dt><dd>${esc(a.note)}</dd>` : ''}</dl>`;
}

function showFin(y, m) {
  const r = finRow(y, m); if (!r) return;
  const v = N(r.value), p = fin(y - 1, m);
  openPanel(`<div class="panel-head"><h2>${y}년 ${esc(r.label)}</h2><button class="x" aria-label="닫기">✕</button></div>
    <div class="ev-val">${eok(v)}</div><div class="kpi-d">${pill(growth(v, p))} 전년 ${eok(p)} · ${esc(r.scope)} 기준</div>
    ${evidenceHTML(r.audit_id)}
    <p class="foot">원 단위 원값: ${v === null ? '없음' : v.toLocaleString('ko-KR')}원. '자동 · 대조 전'은 공식 API 값이지만 사람이 사업보고서와 대조하기 전이라는 뜻입니다.</p>`);
}

function showMetric(y, k) {
  const r = metRow(y, k); if (!r) return;
  const ids = (r.input_audit_ids || '').split(';').filter(Boolean);
  const v = N(r.value);
  openPanel(`<div class="panel-head"><h2>${y}년 ${esc(r.label)}</h2><button class="x" aria-label="닫기">✕</button></div>
    <div class="ev-val">${v === null ? '계산 불가' : r.unit === 'KRW' ? eok(v) : fmt(v, 2) + (r.unit === '%' ? '%' : r.unit)}</div>
    <div class="formula"><b>산식</b><br>${esc(r.formula)}</div>${r.note ? `<div class="note warn" style="margin-top:8px">${esc(r.note)}</div>` : ''}
    <h3 style="font-size:12.5px;margin:12px 0 0">입력값 (${ids.length}개)</h3>
    ${ids.map((id) => { const a = LEDGER().get(id); return a ? `<div class="ev-box"><b>${esc(id)}</b> ${badge(a.result)}<br>${a.value === '' ? '데이터 없음' : eok(N(a.value))} · ${esc(a.source_location)}</div>` : `<div class="ev-box">${esc(id)} — 데이터 없음</div>`; }).join('')}`);
}

/* ---------------- 5) 페이지 ---------------- */
const PAGES = [
  ['screen', '메인 스크린', '발표용 관제 화면 · F 키 전체 화면 · Esc 나가기'],
  ['overview', '개요', '핵심 지표와 실적 흐름'],
  ['compare', '기업 비교', '같은 기준(DART 재무)으로 다른 기업과 비교 — 사업 구성 차이에 유의'],
  ['pl', '손익 추이', '연간 손익과 비용 구조'],
  ['quarterly', '분기 실적', '분기별 단일 실적 (Q4 = 연간 − 3분기 누적)'],
  ['ratios', '재무비율', '수익성·안정성·활동성 — 산식과 입력값 공개'],
  ['bs', '재무상태·현금', '자산·부채·자본과 현금흐름'],
  ['stock', '주가', '주가와 시장지수, 급변일과 같은 시기 공시'],
  ['industry', '산업 KPI', '산업별로 추가 확인할 지표의 확보 현황'],
  ['dart', 'DART 자동 업데이트', '정기보고서를 평일마다 확인해 자동 반영 · 원문 대조 전 값은 따로 표시'],
  ['audit', '출처·검증', '자동 점검 결과, 검증 장부, 출처 목록'],
];

const card = (cls, title, sub, body, foot = '') => `<div class="card ${cls}" data-k="${esc(title)}"><h3>${esc(title)}</h3>${sub ? `<p class="sub">${esc(sub)}</p>` : ''}${body}${foot ? `<p class="foot">${foot}</p>` : ''}</div>`;
const noData = () => `<div class="empty"><b>아직 재무 데이터가 없습니다</b>GitHub 저장소 → Actions → '데이터 업데이트' → Run workflow 를 실행하세요.<br>DART_API_KEY가 Secrets에 등록되어 있어야 합니다.</div>`;

/* 은행·금융지주: '매출액' 자리에 순이자이익, '영업이익률' 자리에 영업이익경비율(CIR)을 쓴다 */
const BANK = () => D?.company?.industry === 'bank';
const TOPK = () => (BANK() ? 'net_interest_income' : 'revenue');
const TOPL = () => (BANK() ? '순이자이익' : '매출액');
const TOPG = () => (BANK() ? 'nii_growth_pct' : 'revenue_growth_pct');
const MRGK = () => (BANK() ? 'cir_pct' : 'operating_margin_pct');
const MRGL = () => (BANK() ? '영업이익경비율(CIR)' : '영업이익률');
function kpiCard(label, value, sub, onclick) {
  return `<button class="kpi" data-act="${esc(onclick || '')}"><span class="kpi-l">${esc(label)}</span><span class="kpi-v">${value}</span><span class="kpi-d">${sub}</span></button>`;
}
const big = (v) => (v === null ? '<small>데이터 없음</small>' : `${fmt(v / 1e8, 0)}<small>억원</small>`);

function pageOverview() {
  if (!D.fin.length) return noData();
  const y = S.year, Y = YEARS();
  const rev = fin(y, TOPK()), op = fin(y, 'operating_profit'), ni = fin(y, 'net_income');
  const k = [
    kpiCard(TOPL(), big(rev), `${pill(met(y, TOPG()))} 전년 대비`, `fin:${y}:${TOPK()}`),
    kpiCard('영업이익', big(op), `${pill(met(y, 'op_growth_pct'))} 전년 대비`, `fin:${y}:operating_profit`),
    kpiCard(MRGL(), met(y, MRGK()) === null ? '<small>데이터 없음</small>' : `${fmt(met(y, MRGK()))}<small>%</small>`, `${pill(met(y - 1, MRGK()) === null || met(y, MRGK()) === null ? null : met(y, MRGK()) - met(y - 1, MRGK()), '%p')} 전년 대비`, `met:${y}:${MRGK()}`),
    kpiCard('당기순이익', big(ni), `${pill(growth(ni, fin(y - 1, 'net_income')))} 전년 대비`, `fin:${y}:net_income`),
  ].join('');
  const sm = D.summary?.verification || {};
  const st = D.status.filter((r) => r.group !== '공통 재무');
  const got = st.filter((r) => ['원문 대조 일치', '자동 수집 · 원문 대조 전'].includes(r.status)).length;
  const vr = D.verify?.counts || {};
  const latest = [...D.reg].filter((r) => r.type === 'DART 정기보고서').sort((a, b) => (a.source_date < b.source_date ? 1 : -1)).slice(0, 5);
  return `<div class="kpis">${k}</div><div class="grid">
    ${card('w4', `${TOPL()}·영업이익 추이`, `막대: 억원 · 선: ${MRGL()}(%) · 막대를 누르면 출처`, `<div class="seg" style="margin-bottom:6px"><button data-per="annual" aria-pressed="${S.period === 'annual'}">연간</button><button data-per="quarter" aria-pressed="${S.period === 'quarter'}">분기</button></div>` + legend([[TOPL(), COLORS()[1]], ['영업이익', COLORS()[0]], [MRGL(), COLORS()[3]]]) + '<div class="chart" id="c1"></div>', S.period === 'quarter' ? 'Q4 = 사업보고서 연간 − 3분기 누적 (연말 결산조정 포함)' : '')}
    ${card('w2', '데이터 검증 현황', '값마다 출처와 대조 상태를 기록', `<table class="tbl"><tbody>
      <tr><td>${badge('원문 대조 일치')}</td><td>${sm['원문 대조 일치'] ?? 0}</td></tr>
      <tr><td>${badge('자동 수집 · 원문 대조 전')}</td><td>${sm['자동 수집 · 원문 대조 전'] ?? 0}</td></tr>
      <tr><td>${badge('불일치')}</td><td>${sm['불일치'] ?? 0}</td></tr>
      <tr><td>${badge('미확인')}</td><td>${sm['미확인'] ?? 0}</td></tr></tbody></table>
      <p class="foot">자동 점검: 통과 ${vr['통과'] ?? '-'} · 실패 ${vr['실패'] ?? (D.verify ? 0 : '-')} · 경고 ${vr['경고'] ?? (D.verify ? 0 : '-')}<br>산업 KPI 확보 ${got}/${st.length}</p>`)}
    ${card('w3', '최근 정기공시', 'DART 원문으로 이동', `<table class="tbl"><tbody>${latest.map((r) => `<tr><td class="l"><a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td><td>${esc(r.source_date)}</td></tr>`).join('') || '<tr><td>없음</td></tr>'}</tbody></table>`)}
    ${card('w3', '분석 범위', '', `<table class="tbl"><tbody>
      <tr><td>기간</td><td>${Y[0]}~${Y[Y.length - 1]}</td></tr><tr><td>재무제표</td><td>${esc(D.fin[0]?.scope || '-')}</td></tr>
      <tr><td>산업 · 카테고리</td><td>${esc(D.industry?.name || D.company.industry)} · ${esc((D.company.categories || []).join(', '))}</td></tr>
      <tr><td>비교 기업</td><td>${esc((D.company.competitors || []).join(', ') || '-')}</td></tr></tbody></table>`, '비교 기업 데이터는 각 기업 대시보드에서 따로 수집합니다 (이 화면에 임의로 넣지 않음).')}
  </div>`;
}
function drawOverview() {
  const Y = YEARS(); const el = $('#c1'); if (!el) return;
  if (S.period === 'quarter') {
    const ps = [...new Set(D.qtr.map((r) => r.period))].sort();
    const qv = (p, m) => N(D.qtr.find((r) => r.period === p && r.metric === m)?.value ?? null);
    const qr = (p, m) => D.qtr.find((r) => r.period === p && r.metric === m);
    barLine(el, ps.map((p) => p.slice(2).replace('-', ' ')), [{ name: TOPL(), color: COLORS()[1], values: ps.map((p) => qv(p, TOPK())) }, { name: '영업이익', color: COLORS()[0], values: ps.map((p) => qv(p, 'operating_profit')) }],
      BANK() ? null : { name: '영업이익률', color: COLORS()[3], unit: '%', values: ps.map((p) => { const r = qv(p, 'revenue'), o = qv(p, 'operating_profit'); return r && o !== null ? (o / r) * 100 : null; }) },
      { onClick: (i, j) => { const r = qr(ps[i], j === '1' ? 'operating_profit' : TOPK()); if (r) openPanel(`<div class="panel-head"><h2>${r.period} ${esc(r.label)}</h2><button class="x">✕</button></div><div class="ev-val">${eok(N(r.value))}</div><div class="formula">${esc(r.method)}</div>${evidenceHTML(r.audit_id)}`); } });
    return;
  }
  barLine(el, Y.map(String), [{ name: TOPL(), color: COLORS()[1], values: Y.map((y) => fin(y, TOPK())) }, { name: '영업이익', color: COLORS()[0], values: Y.map((y) => fin(y, 'operating_profit')) }],
    { name: MRGL(), color: COLORS()[3], unit: '%', values: Y.map((y) => met(y, MRGK())) },
    { onClick: (i, j) => (j === 'L' ? showMetric(Y[i], MRGK()) : showFin(Y[i], [TOPK(), 'operating_profit'][+j])) });
}

const PL_BASE = [['revenue', '매출액'], ['cost_of_sales', '매출원가'], ['sga', '판매비와관리비'], ['operating_profit', '영업이익'], ['net_income', '당기순이익']];
const PL_BANK = [['interest_income', '이자수익'], ['interest_expense', '이자비용'], ['net_interest_income', '순이자이익'], ['net_fee_income', '순수수료이익'], ['general_admin', '일반관리비'],
  ['credit_loss', '신용손실충당금전입액'], ['operating_profit', '영업이익'], ['net_income', '당기순이익'], ['net_income_owners', '지배주주 순이익']];
const PLROWS = () => (BANK() ? PL_BANK : PL_BASE);
const PLKEYS = () => (BANK() ? ['nii_share_pct', 'cir_pct'] : ['cost_ratio_pct', 'sga_ratio_pct', 'operating_margin_pct']);  // 대손비용률(1% 안팎)은 축이 달라 재무비율 화면에서
function finTable(items) {
  const Y = YEARS();
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>항목 (억원)</th>${Y.map((y) => `<th>${y}</th>`).join('')}<th>상태(${Y[Y.length - 1]})</th></tr></thead><tbody>
  ${items.map(([m, l]) => `<tr>${`<td>${esc(l)}</td>`}${Y.map((y) => { const v = fin(y, m); return `<td class="${v < 0 ? 'neg' : ''}" data-act="fin:${y}:${m}" style="cursor:pointer">${v === null ? '–' : fmt(v / 1e8)}</td>`; }).join('')}<td>${badge(finRow(Y[Y.length - 1], m)?.status)}</td></tr>`).join('')}
  </tbody></table></div>`;
}
function pagePL() {
  if (!D.fin.length) return noData();
  return `<div class="grid">${card('w6', '연간 손익', '숫자를 누르면 출처·검증 상태가 오른쪽에 표시됩니다', finTable(PLROWS()))}
    ${card('w6', BANK() ? '수익·비용 구조' : '비용 구조', BANK() ? '% · 총영업이익(계산) 대비 · 대손비용률은 재무비율 화면' : '매출액 대비 비율 (%) · 막대를 누르면 산식', legend(PLKEYS().map((k, j) => [metRow(YEARS()[YEARS().length - 1], k)?.label || k, COLORS()[[1, 2, 0][j]]])) + '<div class="chart" id="c2"></div>')}</div>`;
}
function drawPL() {
  const Y = YEARS(), keys = PLKEYS();
  barLine($('#c2'), Y.map(String), keys.map((k, j) => ({ name: metRow(Y[0], k)?.label || k, color: COLORS()[[1, 2, 0][j]], values: Y.map((y) => met(y, k)) })), null,
    { fmt: (v) => fmt(v, 0) + '%', tipFmt: (v) => pct(v), onClick: (i, j) => showMetric(Y[i], keys[+j]) });
}

function pageQuarterly() {
  if (!D.qtr.length) return noData();
  const metrics = [...new Map(D.qtr.map((r) => [r.metric, r.label])).entries()];
  if (!metrics.some(([m]) => m === S.qmetric)) S.qmetric = (metrics.find(([m]) => m === TOPK()) || metrics[0])[0];  // 은행 등 매출액이 없는 회사
  const periods = [...new Set(D.qtr.map((r) => r.period))].sort();
  const q = (p, m) => D.qtr.find((r) => r.period === p && r.metric === m);
  return `<div class="grid">${card('w6', '분기 실적', '막대: 선택 항목(억원) · 선: 분기 영업이익률(%)', `<div class="seg" style="margin-bottom:8px">${metrics.map(([m, l]) => `<button data-q="${m}" aria-pressed="${S.qmetric === m}">${esc(l)}</button>`).join('')}</div><div class="chart" id="c3"></div>`, 'Q4는 사업보고서 연간 값에서 3분기 누적을 뺀 값이라 연말 결산조정이 함께 들어갑니다.')}
  ${card('w6', '분기 표', '', `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>분기</th>${metrics.map(([, l]) => `<th>${esc(l)}</th>`).join('')}<th>영업이익률</th><th class="l">계산 방법</th></tr></thead><tbody>
    ${periods.map((p) => { const r = q(p, 'revenue'), o = q(p, 'operating_profit'); return `<tr><td>${p}</td>${metrics.map(([m]) => { const x = q(p, m); return `<td>${x ? fmt(N(x.value) / 1e8) : '–'}</td>`; }).join('')}<td>${r && o ? pct((N(o.value) / N(r.value)) * 100) : '–'}</td><td class="l">${esc(r?.method || '')}</td></tr>`; }).join('')}</tbody></table></div>`)}</div>`;
}
function drawQuarterly() {
  const el = $('#c3'); if (!el) return;
  const periods = [...new Set(D.qtr.map((r) => r.period))].sort();
  const q = (p, m) => N(D.qtr.find((r) => r.period === p && r.metric === m)?.value ?? null);
  const label = D.qtr.find((r) => r.metric === S.qmetric)?.label || S.qmetric;
  barLine(el, periods.map((p) => p.slice(2).replace('-', ' ')), [{ name: label, color: COLORS()[1], values: periods.map((p) => q(p, S.qmetric)) }],
    BANK() ? null : { name: '영업이익률', color: COLORS()[0], unit: '%', values: periods.map((p) => { const r = q(p, 'revenue'), o = q(p, 'operating_profit'); return r && o !== null ? (o / r) * 100 : null; }) },
    { onClick: (i) => { const r = D.qtr.find((x) => x.period === periods[i] && x.metric === S.qmetric); if (r) openPanel(`<div class="panel-head"><h2>${r.period} ${esc(r.label)}</h2><button class="x">✕</button></div><div class="ev-val">${eok(N(r.value))}</div><div class="formula">${esc(r.method)}</div>${evidenceHTML(r.audit_id)}`); } });
}

const RATIO_GROUPS_BANK = [['수익성', ['roe_pct', 'roa_pct', 'nii_to_assets_pct', 'nii_share_pct']], ['효율·건전성', ['cir_pct', 'credit_cost_pct']], ['성장성', ['nii_growth_pct', 'ni_growth_pct']], ['안정성·규모', ['debt_ratio_pct', 'equity_ratio_pct', 'loan_deposit_pct', 'total_operating_income']]];
const RATIO_GROUPS_BASE = [['수익성', ['operating_margin_pct', 'net_margin_pct', 'cost_ratio_pct', 'sga_ratio_pct', 'roe_pct', 'roa_pct']], ['성장성', ['revenue_growth_pct', 'op_growth_pct']], ['안정성', ['debt_ratio_pct', 'current_ratio_pct', 'equity_ratio_pct']], ['활동성·투자', ['asset_turnover', 'inventory_turnover', 'capex_to_revenue_pct', 'simple_fcf']]];
function pageRatios() {
  if (!D.met.length) return noData();
  const Y = YEARS();
  const val = (r) => (r.value === '' ? '<span class="pill na">계산 불가</span>' : r.unit === 'KRW' ? fmt(N(r.value) / 1e8) + '억' : fmt(N(r.value), r.unit === '회' ? 2 : 1) + (r.unit === '%' ? '%' : r.unit));
  return `<div class="grid">${(BANK() ? RATIO_GROUPS_BANK : RATIO_GROUPS_BASE).map(([g, keys]) => card('w3', g, '행을 누르면 산식과 입력값 표시', `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>지표</th>${Y.map((y) => `<th>${y}</th>`).join('')}</tr></thead><tbody>
    ${keys.map((k) => { const r0 = metRow(Y[Y.length - 1], k); return r0 ? `<tr class="click" data-act="met:${Y[Y.length - 1]}:${k}"><td>${esc(r0.label)}</td>${Y.map((y) => `<td data-act="met:${y}:${k}">${val(metRow(y, k) || { value: '' })}</td>`).join('')}</tr>` : ''; }).join('')}
    </tbody></table></div>`)).join('')}</div><p class="foot">평균 잔액을 쓰는 지표(ROE·ROA·회전율)와 증가율은 첫 연도에 전기 자료가 없어 '계산 불가'로 둡니다.</p>`;
}

function pageBS() {
  if (!D.fin.length) return noData();
  return `<div class="grid">${card('w3', '자산 = 부채 + 자본', '억원 · 막대를 누르면 출처', legend([['부채총계', COLORS()[3]], ['자본총계', COLORS()[1]]]) + '<div class="chart" id="c4"></div>')}
    ${card('w3', '현금흐름', '억원 · 단순 잉여현금흐름 = 영업활동현금흐름 − 유형자산 취득액', legend([['영업활동현금흐름', COLORS()[2]], ['유형자산 취득', COLORS()[3]], ['단순 FCF', COLORS()[0]]]) + '<div class="chart" id="c5"></div>')}
    ${card('w6', '재무상태·현금흐름 표', '', finTable(BANK() ? [['total_assets', '자산총계'], ['loans', '대출채권'], ['deposits', '예수부채'], ['total_liabilities', '부채총계'], ['total_equity', '자본총계'], ['operating_cashflow', '영업활동현금흐름']] : [['total_assets', '자산총계'], ['current_assets', '유동자산'], ['inventories', '재고자산'], ['cash', '현금및현금성자산'], ['total_liabilities', '부채총계'], ['current_liabilities', '유동부채'], ['total_equity', '자본총계'], ['operating_cashflow', '영업활동현금흐름'], ['capex', '유형자산 취득(지출액)']]))}</div>`;
}
function drawBS() {
  const Y = YEARS();
  barLine($('#c4'), Y.map(String), [{ name: '부채총계', color: COLORS()[3], values: Y.map((y) => fin(y, 'total_liabilities')) }, { name: '자본총계', color: COLORS()[1], values: Y.map((y) => fin(y, 'total_equity')) }], null,
    { stacked: true, onClick: (i, j) => showFin(Y[i], ['total_liabilities', 'total_equity'][+j]) });
  barLine($('#c5'), Y.map(String), [{ name: '영업활동현금흐름', color: COLORS()[2], values: Y.map((y) => fin(y, 'operating_cashflow')) }, { name: '유형자산 취득', color: COLORS()[3], values: Y.map((y) => fin(y, 'capex')) }, { name: '단순 FCF', color: COLORS()[0], values: Y.map((y) => met(y, 'simple_fcf')) }], null,
    { onClick: (i, j) => (+j === 2 ? showMetric(Y[i], 'simple_fcf') : showFin(Y[i], ['operating_cashflow', 'capex'][+j])) });
}

function pageStock() {
  if (!D.stock.length) return `<div class="empty"><b>주가 데이터가 없습니다</b>company.json의 yahoo_ticker를 확인하고 Actions를 실행하세요.</div>`;
  const last = D.stock[D.stock.length - 1];
  return `<div class="grid">${card('w6', '주가 흐름', `${esc(last.source)} · 보라색 점선 = 정기보고서 공시일 (마우스를 올리면 보고서명)`,
    `<div class="seg" style="margin-bottom:8px"><button data-sm="index" aria-pressed="${S.stockMode === 'index'}">시작일=100 지수 비교</button><button data-sm="raw" aria-pressed="${S.stockMode === 'raw'}">주가(원)</button></div>` +
    legend(S.stockMode === 'index' ? [['주가', COLORS()[0]], ['시장지수', COLORS()[1]]] : [['종가', COLORS()[0]]]) + '<div class="chart" id="c6"></div>',
    `마지막 ${esc(last.date)} 종가 ${fmt(N(last.close), 0)}원. 점 = 시장 대비 크게 움직인 날(초록 상승 · 빨강 하락, 큰 점은 주요 공시가 같은 시기에 있음). 누르면 같은 시기 공시가 열립니다. 공시와 주가가 같은 시기에 움직였다고 해서 인과관계가 있다는 뜻은 아닙니다. 비수정 종가라 액면분할이 있으면 해석에 주의하세요.`)}${eventsCard()}</div>`;
}
/* 주가 급변일 (scripts/collect_events.py → events_auto.csv · event_links.csv) */
const EVROWS = () => (D.events || []).slice().sort((a, b) => (a.date < b.date ? 1 : -1));
const spct = (v) => (v === '' || v === undefined ? '–' : `${N(v) > 0 ? '+' : ''}${fmt(N(v), 1)}%`);
function eventsCard() {
  const ev = EVROWS();
  if (!ev.length) return card('w6', '주가 급변일과 같은 시기 공시', '', `<div class="empty"><b>급변일 자료가 아직 없습니다</b>평일 자동 업데이트(collect_events.py)가 돌면 채워집니다.</div>`);
  const lg = D.log?.events || {}, linked = ev.filter((e) => +e.major_count > 0).length;
  const rows = ev.map((e) => `<tr class="click" data-act="ev:${esc(e.date)}"><td>${esc(e.date)}</td><td class="${e.direction === '하락' ? 'neg' : ''}" style="${e.direction === '상승' ? 'color:var(--up)' : ''}">${esc(e.direction)}</td>
    <td>${spct(e.ret_pct)}</td><td>${spct(e.index_ret_pct)}</td><td><b>${spct(e.excess_pct)}</b></td><td>${fmt(N(e.z), 1)}배</td><td>${e.volume_ratio ? fmt(N(e.volume_ratio), 1) + '배' : '–'}</td>
    <td class="l">${+e.major_count ? `<b>${esc(e.headline)}</b>${+e.major_count > 1 ? ` 외 ${+e.major_count - 1}건` : ''}` : `<span style="color:var(--muted)">${esc(e.headline)}</span>`}${+e.other_count ? ` <small style="color:var(--muted)">· 기타 공시 ${esc(e.other_count)}건</small>` : ''}${e.note ? `<br><small style="color:var(--warn)">${esc(e.note)}</small>` : ''}</td></tr>`).join('');
  return card('w6', '주가 급변일과 같은 시기 공시', `시장 대비 크게 움직인 ${ev.length}일 중 ${linked}일에 주요 공시가 같은 시기에 있음 · 행을 누르면 공시 목록과 DART 원문`,
    `<div class="tbl-wrap" style="max-height:420px;overflow-y:auto"><table class="tbl"><thead><tr><th>날짜</th><th>방향</th><th>등락률</th><th>시장지수</th><th>시장 대비</th><th>평소 변동폭 대비</th><th>거래량(20일 평균 대비)</th><th class="l">같은 시기 대표 공시</th></tr></thead><tbody>${rows}</tbody></table></div>`,
    `기준: ${esc(lg.rule || '시장 대비 등락률이 평소 변동폭의 2.5배 이상 또는 5% 이상, 연도별 상위 10일')}. 공시는 급변일 전날~당일 접수분(장 마감 뒤·주말 공시 포함). 같은 시기에 있었던 공시일 뿐 원인이라는 뜻이 아니며, 공시가 없는 날도 숨기지 않습니다. 자동 수집 · 원문 대조 전${lg.checked_at ? ` · ${esc(lg.checked_at)}` : ''}`);
}
function showEvent(date) {
  const e = (D.events || []).find((r) => r.date === date); if (!e) return;
  const lk = (D.evlinks || []).filter((r) => r.date === date).sort((a, b) => (b.major === 'Y') - (a.major === 'Y') || (a.rcept_dt < b.rcept_dt ? -1 : 1));
  const item = (r) => `<div class="ev-box"><b>${esc(r.category)}</b> · ${esc(r.rcept_dt.slice(0, 4))}-${esc(r.rcept_dt.slice(4, 6))}-${esc(r.rcept_dt.slice(6, 8))} 접수${r.flr_nm ? ` · 제출 ${esc(r.flr_nm)}` : ''}<br><a href="${esc(r.viewer_url)}" target="_blank" rel="noopener">${esc(r.report_nm)}</a></div>`;
  const maj = lk.filter((r) => r.major === 'Y'), oth = lk.filter((r) => r.major !== 'Y');
  openPanel(`<div class="panel-head"><h2>${esc(date)} 주가 ${esc(e.direction)}</h2><button class="x" aria-label="닫기">✕</button></div>
    <div class="ev-val">${spct(e.excess_pct)} <small style="font-size:12px;color:var(--muted)">시장 대비</small></div>
    <div class="formula">종가 ${fmt(N(e.close), 0)}원 · 등락률 ${spct(e.ret_pct)} − 시장지수 ${spct(e.index_ret_pct)}<br>평소 변동폭(직전 250거래일 표준편차 ${fmt(N(e.sigma_pct), 2)}%)의 ${fmt(N(e.z), 1)}배 · 거래량 20일 평균의 ${e.volume_ratio ? fmt(N(e.volume_ratio), 1) + '배' : '–'}<br>그해 급변 후보 ${esc(e.candidates_in_year)}일 중 ${esc(e.rank_in_year)}위</div>
    ${e.note ? `<div class="note warn" style="margin-top:8px">${esc(e.note)}</div>` : ''}
    <h3 style="font-size:12.5px;margin:12px 0 0">같은 시기 주요 공시 (${maj.length}건) <small style="color:var(--muted);font-weight:400">${esc(e.window)}</small></h3>
    ${maj.map(item).join('') || '<div class="ev-box">연결된 주요 공시 없음 — 업종 전체 흐름, 수급, 공시 밖 뉴스일 수 있음 (확인 전)</div>'}
    ${oth.length ? `<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px">기타 공시 ${oth.length}건 (지분 신고·IR 안내 등)</summary>${oth.map(item).join('')}</details>` : ''}
    <div class="note" style="margin-top:10px">같은 시기에 있었던 공시를 자동으로 모은 것이며, 이 공시 때문에 주가가 움직였다는 뜻이 아닙니다.</div>`);
}
function drawStock() {
  const xs = D.stock.map((r) => r.date), c = D.stock.map((r) => N(r.close)), k = D.stock.map((r) => N(r.index_close));
  const b0 = c.find((v) => v !== null), k0 = k.find((v) => v !== null);
  const mk = D.reg.filter((r) => r.type === 'DART 정기보고서' && r.source_date).map((r) => ({ date: `${r.source_date.slice(0, 4)}-${r.source_date.slice(4, 6)}-${r.source_date.slice(6, 8)}`, label: `${r.title} (${r.source_date})` }));
  const dots = (D.events || []).map((e) => ({ date: e.date, key: e.date, big: +e.major_count > 0, color: e.direction === '하락' ? css('--down') : css('--up'),
    label: `${e.date} 시장 대비 ${spct(e.excess_pct)}\n${+e.major_count ? e.headline : '연결된 주요 공시 없음'}\n누르면 같은 시기 공시` }));
  const o = { fmt: (v) => fmt(v, 0), dots, onDot: showEvent };
  if (S.stockMode === 'index') lineChart($('#c6'), xs, [{ name: '주가', color: COLORS()[0], values: c.map((v) => (v === null ? null : (v / b0) * 100)) }, { name: '시장지수', color: COLORS()[1], values: k.map((v) => (v === null || !k0 ? null : (v / k0) * 100)) }], mk, o);
  else lineChart($('#c6'), xs, [{ name: '종가(원)', color: COLORS()[0], values: c }], mk, o);
}

/* 산업 KPI: kpi_values.csv에 값이 있으면 KPI별 차트+표, 없으면 '미확인'과 찾을 곳 */
const kpiFmt = (v, u) => (v === null ? '–' : u === 'KRW' ? fmt(v / 1e8, 0) + '억원' : u === '%' ? fmt(v, 2) + '%' : `${fmt(v, v % 1 ? 2 : 0)} ${u}`);
function kpiGroups() {
  const st = D.status.filter((r) => r.group !== '공통 재무');
  return st.map((s) => ({ s, rows: D.kpi.filter((r) => r.kpi_key === s.key) }));
}
function pageIndustry() {
  const ind = D.industry;
  const G = kpiGroups();
  const got = G.filter((g) => g.rows.length);
  const miss = G.filter((g) => !g.rows.length);
  const cardFor = (g, i) => {
    const units = [...new Set(g.rows.map((r) => r.unit))];
    const periods = [...new Set(g.rows.map((r) => r.period || r.year))].sort();
    const items = [...new Set(g.rows.map((r) => r.item))];
    const chartable = units.length === 1 && g.rows.some((r) => r.value !== '');
    const val = (it, p) => g.rows.find((r) => r.item === it && (r.period || r.year) === p);
    const scope = [...new Set(g.rows.map((r) => r.scope).filter(Boolean))].join(' / ');
    const notes = [...new Set(g.rows.map((r) => r.note).filter(Boolean))];
    const st = g.rows.every((r) => r.status === '원문 대조 일치') ? '원문 대조 일치' : g.rows.some((r) => r.status === '불일치') ? '불일치' : '자동 수집 · 원문 대조 전';
    return card('w3', g.s.label, `${scope} · ${chartable ? (units[0] === 'KRW' ? '억원' : units[0]) : '단위가 섞여 표로 표시'}`,
      `<div style="margin-bottom:4px">${badge(st)}</div>${chartable ? legend(periods.map((p, j) => [String(p), COLORS()[(j + 1) % 5]])) + `<div class="chart" id="k${i}"></div>` : ''}
      <div class="tbl-wrap" style="max-height:220px"><table class="tbl"><thead><tr><th>항목</th>${periods.map((p) => `<th>${esc(p)}</th>`).join('')}</tr></thead><tbody>
      ${items.map((it) => `<tr class="click" data-act="kpi:${esc(g.s.key)}:${items.indexOf(it)}"><td class="l">${esc(it)}</td>${periods.map((p) => { const r = val(it, p); return `<td>${r ? kpiFmt(N(r.value), r.unit) : '–'}</td>`; }).join('')}</tr>`).join('')}
      </tbody></table></div>`, notes.map(esc).join('<br>'));
  };
  return `<div class="note">${esc(ind?.name || D.company.industry)} 산업에서 추가로 보는 지표입니다. 사업보고서 원문에서 옮긴 값만 출처와 함께 표시하고, 찾지 못한 지표는 '미확인'으로 둡니다 (추정값 없음). 행을 누르면 원문 위치가 보입니다.</div>
  <div class="grid">${got.map(cardFor).join('')}
  ${card('w6', `확보 현황 · ${got.length}/${G.length}`, '미확인 지표는 아래 위치에서 찾을 수 있습니다', `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>지표</th><th>상태</th><th class="l">결과</th><th class="l">찾을 곳</th><th class="l">주의</th></tr></thead><tbody>
    ${[...got, ...miss].map((g) => `<tr><td>${esc(g.s.label)}</td><td>${badge(g.s.status)}</td><td class="l">${esc(g.s.result)}</td><td class="l">${esc(g.s.where)}</td><td class="l">${esc(g.s.caution)}</td></tr>`).join('') || '<tr><td colspan="5">산업 KPI 목록 없음</td></tr>'}
    </tbody></table></div>`)}</div>`;
}
function drawIndustry() {
  kpiGroups().filter((g) => g.rows.length).forEach((g, i) => {
    const el = $(`#k${i}`); if (!el) return;
    const periods = [...new Set(g.rows.map((r) => r.period || r.year))].sort();
    const items = [...new Set(g.rows.map((r) => r.item))];
    const u = g.rows[0].unit;
    const v = (it, p) => { const r = g.rows.find((x) => x.item === it && (x.period || x.year) === p); return r ? N(r.value) : null; };
    barLine(el, items.map((it) => (it.length > 9 ? it.slice(0, 8) + '…' : it)), periods.map((p, j) => ({ name: String(p), color: COLORS()[(j + 1) % 5], values: items.map((it) => v(it, p)) })), null,
      { fmt: u === 'KRW' ? (x) => fmt(x / 1e8, 0) : (x) => fmt(x, 0), tipFmt: (x) => kpiFmt(x, u), onClick: (ii) => showKpi(g.s.key, ii) });
  });
}
function showKpi(key, ii) {
  const rows = D.kpi.filter((r) => r.kpi_key === key); const item = [...new Set(rows.map((r) => r.item))][ii];
  const rs = rows.filter((r) => r.item === item); const s = D.status.find((x) => x.key === key);
  openPanel(`<div class="panel-head"><h2>${esc(s?.label || key)} · ${esc(item)}</h2><button class="x" aria-label="닫기">✕</button></div>
    ${rs.map((r) => `<dl class="ev-box"><dt>${esc(r.period || r.year)}</dt><dd><b style="font-size:16px">${kpiFmt(N(r.value), r.unit)}</b> ${badge(r.status)}</dd>
      <dt>범위</dt><dd>${esc(r.scope)}</dd><dt>원문 위치</dt><dd>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.source_location)}</a>` : esc(r.source_location)}</dd>
      ${r.note ? `<dt>메모</dt><dd>${esc(r.note)}</dd>` : ''}<dt>입력</dt><dd>${esc(r.checked_on)}</dd></dl>`).join('')}
    ${s?.caution ? `<div class="note warn" style="margin-top:8px">${esc(s.caution)}</div>` : ''}`);
}

function pageAudit() {
  const vr = D.verify;
  const res = S.ledgerFilter;
  const led = D.ledger.filter((r) => res === 'all' || r.result === res);
  const log = D.log || {};
  return `<div class="grid">
  ${card('w3', '자동 점검 결과', vr ? `${esc(vr.checked_at)} · 통과 ${vr.counts['통과'] || 0} · 실패 ${vr.counts['실패'] || 0} · 경고 ${vr.counts['경고'] || 0}` : '아직 점검 전',
    vr ? `<div class="tbl-wrap" style="max-height:340px"><table class="tbl"><tbody>${vr.results.map((r) => `<tr><td>${badge(r.state)}</td><td class="l">${esc(r.name)}${r.detail ? `<br><small style="color:var(--muted)">${esc(r.detail)}</small>` : ''}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">scripts/verify_data.py 실행 후 표시됩니다</div>')}
  ${card('w3', '자동 업데이트 기록', '', `<table class="tbl"><tbody>${Object.entries(log).map(([k, v]) => `<tr><td>${esc({ dart: 'DART 공시', stock: '주가', events: '급변일·공시', text: '사업보고서 본문' }[k] || k)}</td><td>${badge(v.status === '성공' ? '통과' : v.status === '건너뜀' ? '미실행' : '경고')} ${esc(v.status)}</td><td class="l">${esc(v.checked_at || '')}<br><small>${esc(v.message || (v.new_reports || []).slice(-2).join(' / '))}</small></td></tr>`).join('') || '<tr><td>기록 없음</td></tr>'}</tbody></table>`)}
  ${card('w6', '검증 장부', '값 하나하나의 출처·원문 위치·대조 상태', `<div class="seg" style="margin-bottom:8px">${['all', '원문 대조 일치', '자동 수집 · 원문 대조 전', '불일치', '미확인'].map((s) => `<button data-lf="${esc(s)}" aria-pressed="${res === s}">${s === 'all' ? '전체' : esc(ST_SHORT[s] || s)} (${s === 'all' ? D.ledger.length : D.ledger.filter((r) => r.result === s).length})</button>`).join('')}</div>
    <div class="tbl-wrap" style="max-height:420px"><table class="tbl"><thead><tr><th>검증번호</th><th>값(억원)</th><th>상태</th><th class="l">원문 위치</th><th class="l">방법</th></tr></thead><tbody>
    ${led.slice(0, 400).map((r) => `<tr class="click" data-act="aud:${esc(r.audit_id)}"><td>${esc(r.audit_id)}</td><td>${r.value === '' ? '–' : fmt(N(r.value) / 1e8)}</td><td>${badge(r.result)}</td><td class="l">${esc(r.source_location)}</td><td class="l">${esc(r.method)}</td></tr>`).join('')}
    </tbody></table></div>`, '사람이 사업보고서 원문과 대조한 결과는 data/manual/audit_overrides.csv에 적으면 다음 빌드부터 반영됩니다.')}
  ${card('w6', '출처 목록', `${D.reg.length}건`, `<div class="tbl-wrap" style="max-height:300px"><table class="tbl"><thead><tr><th>ID</th><th class="l">문서</th><th>날짜</th><th class="l">처리</th></tr></thead><tbody>
    ${D.reg.map((r) => `<tr><td>${esc(r.source_id)}</td><td class="l"><a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.title)}</a></td><td>${esc(r.source_date)}</td><td class="l">${esc(r.status)} ${esc(r.note)}</td></tr>`).join('')}</tbody></table></div>`)}
  </div>`;
}

/* ---------- 기업 비교 (다른 기업 폴더의 같은 형식 데이터를 읽어 비교) ---------- */
const CMP_BANK = [['net_interest_income', '순이자이익', 'won'], ['net_fee_income', '순수수료이익', 'won'], ['operating_profit', '영업이익', 'won'], ['net_income', '당기순이익', 'won'],
  ['cir_pct', 'CIR(계산)', 'pct'], ['credit_cost_pct', '대손비용률(계산)', 'pct'], ['nii_to_assets_pct', '순이자이익/평균총자산', 'pct'], ['roe_pct', 'ROE', 'pct'], ['roa_pct', 'ROA', 'pct'], ['debt_ratio_pct', '부채비율', 'pct']];
const CMP_BASE = [
  ['revenue', '매출액', 'won'], ['operating_profit', '영업이익', 'won'], ['net_income', '당기순이익', 'won'],
  ['operating_margin_pct', '영업이익률', 'pct'], ['net_margin_pct', '순이익률', 'pct'], ['revenue_growth_pct', '매출 증가율', 'pct'],
  ['cost_ratio_pct', '매출원가율', 'pct'], ['sga_ratio_pct', '판관비율', 'pct'], ['debt_ratio_pct', '부채비율', 'pct'],
  ['current_ratio_pct', '유동비율', 'pct'], ['roe_pct', 'ROE', 'pct'], ['operating_cashflow', '영업활동현금흐름', 'won'],
];
const CMP_ROWS = () => (BANK() ? CMP_BANK : CMP_BASE);
const valOf = (DD, y, k, t) => (t === 'won' ? N(DD.fin.find((r) => +r.year === y && r.metric === k)?.value) : N(DD.met.find((r) => +r.year === y && r.metric === k)?.value));
async function loadOther(slug) {
  if (!OTHER[slug]) OTHER[slug] = await loadAll(slug, COMPARE_KEYS);
  return OTHER[slug];
}
function cmpCandidates() {
  const all = (INDEX?.companies || []).filter((c) => c.slug !== SLUG && c.has_data);
  const ind = D.company.industry;
  return [...all.filter((c) => c.industry === ind), ...all.filter((c) => c.industry !== ind)];
}
function pageCompare() {
  if (!D.fin.length) return noData();
  const cands = cmpCandidates();
  if (!cands.length) return '<div class="empty"><b>비교할 다른 기업이 없습니다</b>기업을 하나 더 추가하면 이 화면에서 비교할 수 있습니다.</div>';
  if (!S.cmp || !cands.some((c) => c.slug === S.cmp)) S.cmp = cands[0].slug;
  const O = OTHER[S.cmp];
  const pick = `<div class="seg seg-wrap">${cands.map((c) => `<button data-cmp="${esc(c.slug)}" aria-pressed="${c.slug === S.cmp}">${esc(c.name)}${c.industry !== D.company.industry ? ' (다른 산업)' : ''}</button>`).join('')}</div>`;
  if (!O) { loadOther(S.cmp).then(() => S.page === 'compare' && render()); return `${pick}<div class="empty" style="margin-top:12px">비교 기업 데이터를 불러오는 중…</div>`; }
  const me = D.company.name, other = O.company?.name || S.cmp;
  const Y = [...new Set([...YEARS(), ...O.fin.map((r) => +r.year)])].sort().filter((y) => YEARS().includes(y) && O.fin.some((r) => +r.year === y));
  const show = (v, t) => (v === null ? '–' : t === 'won' ? fmt(v / 1e8, 0) : fmt(v, 1) + '%');
  const scopeA = D.fin[0]?.scope, scopeB = O.fin[0]?.scope;
  const warn = scopeA !== scopeB ? `<div class="note warn">재무제표 범위가 다릅니다: ${esc(me)} ${esc(scopeA)} / ${esc(other)} ${esc(scopeB)}. 직접 비교에 주의하세요.</div>` : '';
  return `<div style="margin-bottom:10px">${pick}</div>${warn}<div class="grid">
    ${card('w3', `${TOPL()} 비교`, '억원 · 막대를 누르면 산식과 출처', legend([[me, COLORS()[0]], [other, COLORS()[1]]]) + '<div class="chart" id="cp1"></div>')}
    ${card('w3', `${MRGL()} 비교`, '% · 회사마다 비용 분류가 다를 수 있음', legend([[me, COLORS()[0]], [other, COLORS()[1]]]) + '<div class="chart" id="cp2"></div>')}
    ${card('w6', '지표 비교표', `${esc(me)} vs ${esc(other)} · 억원 / % · 셀을 누르면 두 회사 값의 출처`, `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>지표</th>${Y.map((y) => `<th>${y} ${esc(me)}</th><th>${y} ${esc(other)}</th>`).join('')}</tr></thead><tbody>
      ${CMP_ROWS().map(([k, l, t]) => `<tr><td>${esc(l)}</td>${Y.map((y) => `<td data-act="cmp:${y}:${k}" style="cursor:pointer">${show(valOf(D, y, k, t), t)}</td><td data-act="cmp:${y}:${k}" style="cursor:pointer;color:var(--muted)">${show(valOf(O, y, k, t), t)}</td>`).join('')}</tr>`).join('')}
    </tbody></table></div>`, '두 회사의 사업 구성(제품군·해외 비중·관계사 구조)이 달라 수익성 차이를 경쟁력 차이로 단정할 수 없습니다. 같은 DART 연결 계정 기준의 비교입니다.')}
  </div>`;
}
function drawCompare() {
  const O = OTHER[S.cmp]; if (!O || !$('#cp1')) return;
  const Y = YEARS().filter((y) => O.fin.some((r) => +r.year === y));
  barLine($('#cp1'), Y.map(String), [{ name: D.company.name, color: COLORS()[0], values: Y.map((y) => valOf(D, y, TOPK(), 'won')) }, { name: O.company.name, color: COLORS()[1], values: Y.map((y) => valOf(O, y, TOPK(), 'won')) }], null, { onClick: (i) => showCmp(Y[i], TOPK()) });
  barLine($('#cp2'), Y.map(String), [{ name: D.company.name, color: COLORS()[0], values: Y.map((y) => valOf(D, y, MRGK(), 'pct')) }, { name: O.company.name, color: COLORS()[1], values: Y.map((y) => valOf(O, y, MRGK(), 'pct')) }], null, { fmt: (v) => fmt(v, 0) + '%', tipFmt: (v) => pct(v), onClick: (i) => showCmp(Y[i], MRGK()) });
}
function showCmp(y, k) {
  const O = OTHER[S.cmp]; const [, l, t] = CMP_ROWS().find((r) => r[0] === k) || [k, k, 'won'];
  const side = (DD) => {
    const v = valOf(DD, y, k, t);
    const ids = t === 'won' ? [`F-${y}-${k}`] : (DD.met.find((r) => +r.year === y && r.metric === k)?.input_audit_ids || '').split(';').filter(Boolean);
    const led = new Map(DD.ledger.map((r) => [r.audit_id, r])); const reg = new Map(DD.reg.map((r) => [r.source_id, r]));
    const f = t === 'pct' ? DD.met.find((r) => +r.year === y && r.metric === k)?.formula : '';
    return `<div class="ev-box"><b>${esc(DD.company.name)}</b><div class="ev-val" style="font-size:18px">${v === null ? '데이터 없음' : t === 'won' ? eok(v) : pct(v, 2)}</div>${f ? `<div class="formula">${esc(f)}</div>` : ''}
      ${ids.map((id) => { const a = led.get(id); const s = a && reg.get(a.source_id); return a ? `<div style="margin-top:4px"><small>${esc(id)}</small> ${badge(a.result)}${s ? ` · <a href="${esc(s.source_url)}" target="_blank" rel="noopener">원문</a>` : ''}</div>` : ''; }).join('')}</div>`;
  };
  openPanel(`<div class="panel-head"><h2>${y}년 ${esc(l)}</h2><button class="x" aria-label="닫기">✕</button></div>${side(D)}${side(O)}<p class="foot">같은 DART 계정 기준 값입니다. 차이의 원인은 수치만으로 확정하지 않습니다.</p>`);
}

/* ---------- DART 자동 업데이트 ---------- */
function pageDart() {
  const reps = [...D.reports].sort((a, b) => (a.rcept_dt < b.rcept_dt ? 1 : -1));
  const lg = D.log?.dart || {};
  const auto = D.ledger.filter((r) => r.result === '자동 수집 · 원문 대조 전').length;
  const corr = reps.filter((r) => r.is_correction === 'Y').length;
  return `<div class="kpis">
    ${kpiCard('반영한 정기보고서', `${reps.length}<small>건</small>`, `정정보고서 ${corr}건 포함`, '')}
    ${kpiCard('마지막 확인', `<small>${esc(lg.checked_at || '기록 없음')}</small>`, `상태 ${esc(lg.status || '-')}`, '')}
    ${kpiCard('원문 대조 전 값', `${auto}<small>개</small>`, '공식 API 값 · 사람 대조 대기', '')}
    ${kpiCard('자동 실행', '<small>평일 16:40</small>', 'GitHub Actions → Render 자동 배포', '')}
  </div><div class="grid">
    ${card('w6', '정기보고서 처리 기록', '새 보고서·정정보고서가 올라오면 해당 기간을 다시 받아 덮어씁니다', `<div class="tbl-wrap" style="max-height:460px"><table class="tbl"><thead><tr><th class="l">보고서</th><th>접수일</th><th>구분</th><th>처리</th><th class="l">내용</th></tr></thead><tbody>
      ${reps.map((r) => `<tr><td class="l"><a href="${esc(r.viewer_url)}" target="_blank" rel="noopener">${esc(r.report_nm)}</a></td><td>${esc(r.rcept_dt)}</td><td>${r.is_correction === 'Y' ? '<span class="st st-warn">정정</span>' : esc(r.report_type)}</td><td>${badge(r.status === '반영' ? '통과' : '경고')} ${esc(r.status)}</td><td class="l">${esc(r.message)}</td></tr>`).join('') || '<tr><td colspan="5">기록 없음</td></tr>'}
    </tbody></table></div>`, '값은 OpenDART 단일회사 전체 재무제표 API를 그대로 쓰며, 사람이 사업보고서 원문과 대조하기 전까지 &#39;자동 · 대조 전&#39;으로 표시합니다.')}
    ${card('w6', '최근 실행 결과', '', `<ul style="margin:0;padding-left:18px">${(lg.new_reports || []).slice(-8).map((x) => `<li>${esc(x)}</li>`).join('') || '<li>이번 실행에서 새로 반영한 보고서 없음</li>'}</ul>${(lg.errors || []).length ? `<div class="note warn" style="margin-top:8px">${lg.errors.map(esc).join('<br>')}</div>` : ''}`)}
  </div>`;
}

/* ---------- 메인 스크린 (불닭 대시보드와 같은 1920×1080 관제 화면: screen.html을 그대로 띄움) ---------- */
function pageScreen() {
  if (!D.fin.length) return noData();
  return `<iframe class="screen-frame" id="screenFrame" title="메인 스크린" src="screen.html?c=${encodeURIComponent(SLUG)}" allow="fullscreen"></iframe>`;
}
function drawScreen() {
  const f = $('#screenFrame'); if (!f) return;
  f.addEventListener('load', () => { try { f.contentWindow.focus(); } catch (e) { /* 무시 */ } });
}
addEventListener('message', (e) => { if (e.data && e.data.ubda === 'screen-exit' && S.page === 'screen') { S.page = 'overview'; render(); } });

/* ---------- 편집 모드: 카드를 끌어 순서 변경, 이 브라우저에만 저장 ---------- */
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem('ubda:' + k)); } catch (e) { return null; } },
  set(k, v) { try { if (v === null) localStorage.removeItem('ubda:' + k); else localStorage.setItem('ubda:' + k, JSON.stringify(v)); } catch (e) { /* 저장 불가 환경 */ } },
};
function applyOrder() {
  const order = store.get(`order:${SLUG}:${S.page}`); if (!order) return;
  document.querySelectorAll('#workspace .grid').forEach((g) => {
    const cards = [...g.children]; cards.sort((a, b) => { const ia = order.indexOf(a.dataset.k), ib = order.indexOf(b.dataset.k); return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib); });
    cards.forEach((c) => g.append(c));
  });
}
function enableEdit() {
  const page = $('#workspace .page'); if (!page || !S.edit) return;
  page.classList.add('editing');
  page.insertAdjacentHTML('afterbegin', '<div class="edit-banner">배치 편집 — 카드를 끌어 순서를 바꾸세요 (이 브라우저에만 저장). <button data-edit="reset">기본 배치로</button> <button data-edit="done">완료</button></div>');
  let drag = null;
  page.querySelectorAll('.grid > .card').forEach((c) => {
    c.draggable = true;
    c.addEventListener('dragstart', (e) => { drag = c; c.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
    c.addEventListener('dragend', () => { c.classList.remove('dragging'); drag = null; store.set(`order:${SLUG}:${S.page}`, [...page.querySelectorAll('.grid > .card')].map((x) => x.dataset.k)); });
    c.addEventListener('dragover', (e) => { e.preventDefault(); if (!drag || drag === c || drag.parentNode !== c.parentNode) return; const r = c.getBoundingClientRect(); c.parentNode.insertBefore(drag, (e.clientY - r.top) / r.height > 0.5 || (e.clientX - r.left) / r.width > 0.5 ? c.nextSibling : c); });
  });
}

const DRAW = { industry: drawIndustry, screen: drawScreen, compare: drawCompare, overview: drawOverview, pl: drawPL, quarterly: drawQuarterly, bs: drawBS, stock: drawStock };
const RENDER = { screen: pageScreen, compare: pageCompare, dart: pageDart, overview: pageOverview, pl: pagePL, quarterly: pageQuarterly, ratios: pageRatios, bs: pageBS, stock: pageStock, industry: pageIndustry, audit: pageAudit };

function render() {
  const [id, title, desc] = PAGES.find((p) => p[0] === S.page);
  $('#pageTitle').textContent = title; $('#pageDesc').textContent = desc;
  document.querySelectorAll('.nav-btn').forEach((b) => b.setAttribute('aria-current', b.dataset.page === id ? 'page' : 'false'));
  const Y = YEARS();
  $('#topFilters').innerHTML = id === 'overview' && Y.length ? `<div class="seg">${Y.map((y) => `<button data-year="${y}" aria-pressed="${y === S.year}">${y}</button>`).join('')}</div>` : '';
  document.body.classList.toggle('screen-mode', id === 'screen');
  const editable = !['screen', 'audit', 'dart'].includes(id);
  $('#editBtn').hidden = !editable; $('#editBtn').setAttribute('aria-pressed', String(S.edit && editable));
  if (!editable) S.edit = false;
  $('#workspace').innerHTML = `<div class="page">${RENDER[id]()}</div>`;
  applyOrder();
  DRAW[id]?.();
  enableEdit();
  try { history.replaceState(null, '', location.search + '#' + id); } catch (e) { /* 미리보기 환경 */ }
}

function onClick(e) {
  const t = e.target.closest('[data-page],[data-year],[data-act],[data-q],[data-sm],[data-lf],[data-per],[data-cmp],[data-edit]'); if (!t) return;
  if (S.edit && t.closest('.chart')) return; // 편집 중에는 차트 클릭 끔
  if (t.dataset.per) { S.period = t.dataset.per; render(); return; }
  if (t.dataset.cmp) { S.cmp = t.dataset.cmp; closePanel(); render(); return; }
  if (t.dataset.edit) { if (t.dataset.edit === 'reset') store.set(`order:${SLUG}:${S.page}`, null); if (t.dataset.edit === 'done') S.edit = false; render(); return; }
  if (t.dataset.page) { S.page = t.dataset.page; $('#app').classList.remove('nav-open'); if (!t.closest('#panel')) closePanel(); render(); }
  else if (t.dataset.year) { S.year = +t.dataset.year; render(); }
  else if (t.dataset.q) { S.qmetric = t.dataset.q; render(); }
  else if (t.dataset.sm) { S.stockMode = t.dataset.sm; render(); }
  else if (t.dataset.lf) { S.ledgerFilter = t.dataset.lf; render(); }
  else if (t.dataset.act) {
    const [k, a, b] = t.dataset.act.split(':');
    if (k === 'fin') showFin(+a, b); else if (k === 'met') showMetric(+a, b); else if (k === 'cmp') showCmp(+a, b); else if (k === 'kpi') showKpi(a, +b); else if (k === 'ev') showEvent(a);
    else if (k === 'aud') openPanel(`<div class="panel-head"><h2>${esc(a)}</h2><button class="x">✕</button></div>${evidenceHTML(a)}`);
    e.stopPropagation();
  }
}

/* ---------------- 6) 시작 ---------------- */
(async function init() {
  tip.el = $('#tip');
  D = await loadAll();
  const c = D.company;
  if (!SLUG || !c) { $('#workspace').innerHTML = `<div class="empty"><b>${SLUG ? `기업 '${esc(SLUG)}'을(를) 찾지 못했습니다` : '기업이 지정되지 않았습니다'}</b><a href="index.html">전체 기업 목록으로 이동</a><br><small>로컬에서는 파일을 더블클릭하지 말고 <code>python -m http.server 8000</code>으로 여세요.</small></div>`; $('#brandName').textContent = '경영분석'; return; }
  if (c.theme_color) { document.documentElement.style.setProperty('--accent', c.theme_color); document.documentElement.style.setProperty('--accent-soft', c.theme_color + '1a'); }
  document.title = `${c.name} 경영분석`;
  $('#brandMark').textContent = c.name.slice(0, 1);
  $('#brandName').textContent = `${c.name} 경영분석`;
  $('#brandSub').textContent = `${D.industry?.name || c.industry} · ${(c.categories || []).join(', ')}`;
  $('#navList').innerHTML = PAGES.map(([id, t]) => `<li><button class="nav-btn" data-page="${id}"><span class="dot"></span>${esc(t)}</button></li>`).join('');
  const Y = YEARS(); S.year = Y[Y.length - 1] ?? null;
  const fsScope = D.fin[0]?.scope || '-';
  $('#scope').innerHTML = `<span><b>${esc(c.name)}</b> ${esc(c.stock_code || '')}</span><span>재무 <b>${esc(fsScope)}</b> 기준 · DART</span><span>기간 <b>${Y.length ? `${Y[0]}~${Y[Y.length - 1]}` : '-'}</b></span><span>업데이트 ${esc(D.summary?.updated_at || '-')}</span>`;
  $('#navFoot').innerHTML = `<a href="index.html">← 전체 기업</a><br><br>수업용 경영분석이며 투자 추천이 아닙니다.<br>UBDA · 정적 CSV`;
  const h = location.hash.slice(1); if (PAGES.some((p) => p[0] === h)) S.page = h;
  document.addEventListener('click', onClick);
  $('#menuBtn').addEventListener('click', () => $('#app').classList.toggle('nav-open'));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if (S.page === 'screen') { if (document.fullscreenElement) return; S.page = 'overview'; render(); } else closePanel(); }
    if ((e.key === 'f' || e.key === 'F') && S.page === 'screen' && !e.target.closest('input,textarea')) { try { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(); } catch (er) { /* 미지원 */ } }
  });
  $('#editBtn').addEventListener('click', () => { S.edit = !S.edit; render(); });
  $('#askBtn')?.addEventListener('click', () => window.openQuery?.());
  try { INDEX = await (await fetch('companies/index.json', { cache: 'no-cache' })).json(); } catch (e) { INDEX = null; }
  let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => DRAW[S.page]?.(), 150); });
  render();
})();
