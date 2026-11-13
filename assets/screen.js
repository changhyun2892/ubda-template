/* =====================================================================
   메인 스크린 (screen.html?c=<기업>) — 발표용 관제 화면
   · 불닭 대시보드 메인 스크린과 같은 배치·연출을 모든 기업에 쓰도록 일반화한 판.
   · 데이터는 companies/<기업>/의 CSV를 그대로 읽는다 (숫자 하드코딩 없음). 금액은 원(KRW) → 억원.
   · 값이 없으면 가짜 값으로 채우지 않고 패널에 '데이터 없음'을 표시하거나 같은 칸에 대체 지표를 보여 준다(제목에 표시).
   · 지구본: 사업보고서 'I. 회사의 개요'의 연결대상 종속회사 표(data/subsidiaries.csv) 중 해외 법인.
     연도 장면은 설립일 기준(그 해 말까지 설립된 법인). 법인별 매출이 아니라 '법인 수'를 보여 준다.
   ===================================================================== */
(function () {
'use strict';
function showGlobeErr(msg) { const e = document.getElementById('globeErr'); if (!e) return; e.style.display = 'block'; e.innerHTML = '<b style="color:#E0574F">지구본 오류</b><br>' + String(msg).replace(/</g, '&lt;'); }
window.addEventListener('error', (ev) => { if (window.__globeInit && !window.__globeOK) showGlobeErr((ev.message || '') + (ev.filename ? ' @ ' + ev.filename.split('/').pop() + ':' + ev.lineno : '')); });

const SLUG = (new URLSearchParams(location.search).get('c') || '').replace(/[^a-z0-9_-]/gi, '');
const KOREA = { lat: 37.57, lng: 126.98 };
const C = { cyan: '#4FC3F7', blue: '#2F80D8', orange: '#F2A03D', green: '#7CC36A', red: '#E0574F', text: '#E8F0F7', sub: '#9FB3C8', unit: '#D98A4A' };
const NUMF = 'Barlow Semi Condensed';
const REDUCED = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

const fmt = (v, d = 0) => (v == null || !isFinite(v) ? '–' : v.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (v) => (v >= 300 ? `${((v + 100) / 100).toFixed(1)}배` : (v >= 0 ? '+' : '') + v.toFixed(1) + '%');
const joEok = (v) => { const j = Math.floor(v / 10000), e = Math.round(v - j * 10000); return j ? `${j}조 ${fmt(e)}억원` : `${fmt(e)}억원`; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = (v) => (v === '' || v == null || !isFinite(+v) ? null : +v);
const EOK = (v) => (v == null ? null : v / 1e8);

/* ---------- 데이터 읽기 ---------- */
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
  const h = rows.shift() || [];
  return rows.filter((r) => r.length > 1 || r[0]).map((r) => Object.fromEntries(h.map((k, i) => [k, r[i] ?? ''])));
}
async function get(url, json) {
  try { const r = await fetch(url, { cache: 'no-cache' }); if (!r.ok) return null; const t = await r.text(); return json ? JSON.parse(t) : parseCSV(t); }
  catch (e) { return null; }
}
async function loadCompany(slug) {
  const b = `companies/${slug}/`;
  const [company, fin, met, qtr, stock, kpi, subs] = await Promise.all([
    get(b + 'company.json', true), get(b + 'data/financials.csv'), get(b + 'data/metrics.csv'), get(b + 'data/quarterly.csv'),
    get(b + 'data/stock_daily.csv'), get(b + 'data/manual/kpi_values.csv'), get(b + 'data/subsidiaries.csv')]);
  return { slug, company, fin: fin || [], met: met || [], qtr: qtr || [], stock: stock || [], kpi: kpi || [], subs: subs || [] };
}
const finV = (c, y, m) => N(c.fin.find((r) => +r.year === y && r.metric === m)?.value);
const metV = (c, y, m) => N(c.met.find((r) => +r.year === y && r.metric === m)?.value);
const qV = (c, p, m) => N(c.qtr.find((r) => r.period === p && r.metric === m)?.value);

let A = null, B = null, IND = null, YRS = [];
const BANK = () => A?.company?.industry === 'bank';
const TOPK = () => (BANK() ? 'net_interest_income' : 'revenue');
const TOPL = () => (BANK() ? '순이자이익' : '매출액');
const TOPG = () => (BANK() ? 'nii_growth_pct' : 'revenue_growth_pct');
const PRFK = () => (BANK() ? 'roe_pct' : 'operating_margin_pct');
const PRFL = () => (BANK() ? 'ROE' : '영업이익률');

/* 수출·해외 매출: 산업 KPI region_revenue·export_revenue 중 '수출'·'해외'로 시작하는 항목(원화) 합계.
   연결 범위를 먼저 쓰고, 없으면 다른 범위(예: 본사 별도)를 쓰되 화면에 범위를 적는다. 없으면 null */
function exportRows(c) {
  const all = c.kpi.filter((r) => ['region_revenue', 'export_revenue'].includes(r.kpi_key) && (r.unit || '').toUpperCase() === 'KRW'
    && /^(수출|해외)/.test(r.item || '') && N(r.value) !== null && !/재작성|비교 표시/.test(r.scope || ''));
  if (!all.length) return { rows: [], scope: '', cons: false };
  const cons = all.filter((r) => /연결/.test(r.scope || ''));
  const use = cons.length ? cons : all;
  const sc = use[0].scope; // 한 범위만 (서로 다른 표를 더하지 않음)
  return { rows: use.filter((r) => r.scope === sc && r.kpi_key === use[0].kpi_key), scope: sc, cons: !!cons.length };
}
function exportOf(c, y, needCons) {
  const e = exportRows(c); if (needCons && !e.cons && !/별도/.test(c.fin[0]?.scope || '')) return null; // 재무가 별도 기준인 회사는 별도 표도 같은 기준
  const rows = e.rows.filter((r) => +r.year === y);
  return rows.length ? rows.reduce((s, r) => s + N(r.value), 0) : null;
}
function exportScope(c) { return exportRows(c).scope; }

/* ---------- stage scaling ---------- */
const stage = $('stage');
function fit() { const s = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `translate(${(innerWidth - 1920 * s) / 2}px,${(innerHeight - 1080 * s) / 2}px) scale(${s})`; }
fit(); addEventListener('resize', fit);

function tick() { const d = new Date(); const z = (n) => String(n).padStart(2, '0'); $('clock').firstChild.nodeValue = `${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`; }
tick(); setInterval(tick, 1000);

function countUp(el, to, { from = 0, dur = 900, dec = 0 } = {}) {
  if (!el) return;
  if (REDUCED || to == null) { el.textContent = fmt(to, dec); return; }
  const t0 = performance.now();
  (function step(t) { const k = Math.max(0, Math.min(1, (t - t0) / dur)), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(from + (to - from) * e, dec); if (k < 1) requestAnimationFrame(step); })(t0);
}
function need(ok, msg) { if (!ok) throw Object.assign(new Error(msg), { soft: true }); }

/* =====================================================================
   KPI
   ===================================================================== */
let cur = 'A';
function renderKpi() {
  const c = cur === 'A' ? A : B;
  need(c && c.fin.length, '재무 데이터(financials.csv)가 없습니다');
  const y = YRS[YRS.length - 1], p = y - 1, y0 = YRS[0];
  $('kpiTitle').textContent = `${c.company.name} 핵심 지표 · ${y}`; $('kpiAside').textContent = `${p} 대비`;
  const g = (a, b) => (a != null && b ? (a / b - 1) * 100 : null);
  const pp = (a, b) => (a != null && b != null ? +(a - b).toFixed(1) : null);
  const top = EOK(finV(c, y, TOPK())), op = EOK(finV(c, y, 'operating_profit'));
  const rows = [
    { lab: TOPL(), val: top, dec: 1, u: '억원', chg: g(top, EOK(finV(c, p, TOPK()))), type: 'pct' },
    { lab: '영업이익', val: op, dec: 1, u: '억원', chg: g(op, EOK(finV(c, p, 'operating_profit'))), type: 'pct' },
  ];
  if (BANK()) {
    rows.push({ lab: '영업이익경비율(CIR)', val: metV(c, y, 'cir_pct'), dec: 1, u: '%', chg: pp(metV(c, y, 'cir_pct'), metV(c, p, 'cir_pct')), type: 'pp', inverse: true });
    rows.push({ lab: 'ROE', val: metV(c, y, 'roe_pct'), dec: 1, u: '%', chg: pp(metV(c, y, 'roe_pct'), metV(c, p, 'roe_pct')), type: 'pp', foot: '지배주주 순이익 ÷ 평균 자본 (계산값)' });
  } else {
    rows.push({ lab: '영업이익률', val: metV(c, y, 'operating_margin_pct'), dec: 1, u: '%', chg: pp(metV(c, y, 'operating_margin_pct'), metV(c, p, 'operating_margin_pct')), type: 'pp' });
    const ex = exportOf(c, y, true), exp = exportOf(c, p, true), rv = finV(c, y, 'revenue'), rvp = finV(c, p, 'revenue');
    if (ex != null && rv) rows.push({ lab: '수출·해외 매출 비중', val: (ex / rv) * 100, dec: 1, u: '%', chg: exp != null && rvp ? pp((ex / rv) * 100, (exp / rvp) * 100) : null, type: 'pp', foot: '사업보고서 매출실적 수출·해외 ÷ 매출액 (계산값)' });
    else rows.push({ lab: '부채비율', val: metV(c, y, 'debt_ratio_pct'), dec: 1, u: '%', chg: pp(metV(c, y, 'debt_ratio_pct'), metV(c, p, 'debt_ratio_pct')), type: 'pp', inverse: true, foot: '수출·해외 매출 공시 없음 → 부채비율 표시' });
  }
  $('kpis').innerHTML = rows.map((r, i) => {
    const good = r.chg == null ? null : (r.inverse ? r.chg <= 0 : r.chg >= 0);
    const b = r.chg == null ? '<span class="badge na">비교 불가</span>'
      : `<span class="badge ${good ? 'up' : 'down'}">${r.chg >= 0 ? '▲' : '▼'} ${Math.abs(r.chg).toFixed(1)}${r.type === 'pp' ? '%p' : '%'}</span>`;
    const v = r.val == null ? '<span style="color:var(--sub);font-size:32px">–</span>' : `<span class="num" id="kv${i}">0</span><span class="u">${r.u}</span>`;
    return `<div class="kpi"><div class="lab">${r.lab}</div><div class="val">${v}</div>${b}${r.foot ? `<div class="foot">${r.foot}</div>` : ''}</div>`;
  }).join('');
  rows.forEach((r, i) => { if (r.val != null) countUp($('kv' + i), r.val, { dec: r.dec, dur: 800 }); });
  const t0 = finV(c, y0, TOPK()), t1 = finV(c, y, TOPK()), o0 = finV(c, y0, 'operating_profit'), o1 = finV(c, y, 'operating_profit');
  const mult = (a, b) => (a && b && a > 0 && b > 0 ? (b / a >= 2 ? `${(b / a).toFixed(1)}배` : pct((b / a - 1) * 100)) : '비교 불가');
  $('kpiInsight').textContent = `${y0}년 대비 ${TOPL()} ${mult(t0, t1)} · 영업이익 ${mult(o0, o1)}`;
}

/* =====================================================================
   ECharts 공통
   ===================================================================== */
const charts = [];
function mk(id) { const c = echarts.init($(id), null, { renderer: 'canvas' }); charts.push(c); return c; }
const axisTxt = { color: C.sub, fontSize: 15, fontFamily: NUMF };
const tip = { trigger: 'axis', backgroundColor: 'rgba(10,22,40,.95)', borderColor: C.cyan, textStyle: { color: '#fff', fontSize: 16 } };
function quarters(c) { return [...new Set(c.qtr.map((r) => r.period))].sort().filter((p) => +p.slice(0, 4) >= YRS[0]); }

function initQuarterlyOp() {
  const QA = quarters(A); need(QA.length, '분기 데이터(quarterly.csv)가 없습니다');
  const Q = QA;
  const a = Q.map((p) => EOK(qV(A, p, 'operating_profit'))), b = B ? Q.map((p) => EOK(qV(B, p, 'operating_profit'))) : null;
  const ch = mk('qopChart');
  const last = (arr, color) => arr.map((v, i) => (i === arr.length - 1 && v != null ? { value: v, label: { show: true, position: v >= 0 ? 'right' : 'left', color, fontSize: 18, fontWeight: 600, fontFamily: NUMF, formatter: (p) => fmt(p.value) } } : v));
  const series = [{ name: A.company.name, type: 'bar', barWidth: 8, barGap: '40%', itemStyle: { color: C.red, borderRadius: [0, 3, 3, 0] }, data: last(a, C.red) }];
  if (b) series.push({ name: B.company.name, type: 'bar', barWidth: 8, itemStyle: { color: C.blue, borderRadius: [0, 3, 3, 0] }, data: last(b, C.blue) });
  ch.setOption({
    animationDuration: 1200, grid: { left: 64, right: 62, top: 38, bottom: 28 },
    legend: { top: 0, textStyle: { color: C.text, fontSize: 16 }, itemWidth: 16, itemHeight: 10 },
    tooltip: { ...tip, axisPointer: { type: 'shadow' }, valueFormatter: (v) => fmt(v) + '억원' },
    xAxis: { type: 'value', axisLabel: { ...axisTxt, fontSize: 14 }, splitLine: { show: false }, axisLine: { show: true, lineStyle: { color: 'rgba(169,189,208,.4)', width: 1.5 } }, splitNumber: 3 },
    yAxis: { type: 'category', data: Q.map((q) => q.slice(2).replace('-', ' ')), axisLabel: { ...axisTxt, fontSize: 14, fontFamily: 'Pretendard, "Malgun Gothic", "Noto Sans KR", sans-serif' }, axisTick: { show: false }, axisLine: { lineStyle: { color: 'rgba(169,189,208,.4)', width: 1.5 } } },
    series,
  });
  const lp = Q[Q.length - 1], la = a[a.length - 1];
  if (b) {
    const i = Q.findIndex((p, k) => a[k] != null && b[k] != null && a[k] > b[k] && Q.slice(k).every((_, j) => a[k + j] == null || b[k + j] == null || a[k + j] > b[k + j]));
    $('qopInsight').textContent = i >= 0 ? `${Q[i].replace('-', ' ')}부터 ${A.company.name}이(가) ${B.company.name}을(를) 앞섬`
      : `${lp.replace('-', ' ')} 영업이익 ${A.company.name} ${fmt(la)}억 · ${B.company.name} ${fmt(b[b.length - 1])}억`;
  } else $('qopInsight').textContent = `${lp.replace('-', ' ')} 영업이익 ${fmt(la)}억원 · 같은 산업 비교 기업 없음`;
}

/* 가동률 게이지 — 은행은 자본비율 게이지, 둘 다 없으면 같은 칸에 사업부문별 매출 */
function gaugeRows(key, pref) {
  const cu = A.kpi.filter((r) => r.kpi_key === key && (r.unit || '') === '%' && N(r.value) !== null);
  if (!cu.length) return null;
  const y = Math.max(...cu.map((r) => +r.year));
  const rows = cu.filter((r) => +r.year === y);
  const pick = rows.filter((r) => pref.test(r.item));
  const list = (pick.length ? pick : rows).slice(0, 3).map((r) => ({ name: r.item.length > 14 ? r.item.slice(0, 14) + '…' : r.item, full: r.item, v: N(r.value) }));
  return { y, rows, list };
}
function drawGauges(g, maxOf, colorOf) {
  const ch = mk('plantChart'); const n = g.list.length, w = 100 / n;
  ch.setOption({ series: g.list.map((p, i) => ({
    type: 'gauge', center: [n === 3 ? `${18 + i * 32}%` : `${w * i + w / 2}%`, '52%'], radius: '86%', startAngle: 225, endAngle: -45, min: 0, max: maxOf(p.v),
    progress: { show: true, roundCap: false, width: 10, itemStyle: { color: colorOf(p.v) } },
    axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(255,255,255,.08)']] } },
    splitNumber: 20, axisTick: { show: true, distance: -22, length: 4, splitNumber: 1, lineStyle: { color: 'rgba(159,179,200,.35)', width: 1 } },
    pointer: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
    title: { offsetCenter: [0, '82%'], color: C.sub, fontSize: 17, fontWeight: 500 },
    detail: { offsetCenter: [0, '0%'], formatter: (v) => v.toFixed(1) + '%', color: '#fff', fontSize: 34, fontWeight: 600, fontFamily: NUMF },
    animationDuration: 1600, data: [{ value: p.v, name: p.name }],
  })) });
}
function initPlantGauges() {
  const cu = gaugeRows('capacity_utilization', /합계|평균|전체/);
  if (cu) {
    $('plantTitle').textContent = `${cu.y} 가동률`; $('plantAside').textContent = (cu.rows[0].scope || '').slice(0, 30);
    drawGauges(cu, (v) => Math.max(100, Math.ceil(v / 10) * 10), (v) => (v >= 80 ? C.cyan : v >= 60 ? C.orange : C.red));
    const top = [...cu.list].sort((a, b) => b.v - a.v)[0];
    $('plantInsight').textContent = `최고 ${top.full} ${top.v.toFixed(1)}%` + (cu.rows.length > cu.list.length ? ` · 사업보고서 ${cu.rows.length}개 항목 중 ${cu.list.length}개 표시` : '');
    return;
  }
  const cr = BANK() ? gaugeRows('capital_ratio', /BIS|총자본|보통주|기본자본/) : null;
  if (cr) {
    $('plantTitle').textContent = `${cr.y} 자본적정성`; $('plantAside').textContent = (cr.rows[0].scope || '').slice(0, 30);
    drawGauges(cr, (v) => Math.max(20, Math.ceil(v / 5) * 5), () => C.cyan);
    $('plantInsight').textContent = cr.list.map((r) => `${r.full} ${r.v.toFixed(2)}%`).join(' · ').slice(0, 70);
    return;
  }
  const sg = A.kpi.filter((r) => r.kpi_key === 'segment_revenue' && (r.unit || '').toUpperCase() === 'KRW' && N(r.value) !== null && !/조정|제거/.test(r.item));
  if (!sg.length) { $('plantTitle').textContent = '가동률'; $('plantAside').textContent = ''; throw Object.assign(new Error('가동률·사업부문 매출이 산업 KPI에 없습니다'), { soft: true }); }
  const y = Math.max(...sg.map((r) => +r.year));
  const sc = sg.filter((r) => +r.year === y); const scope = sc.find((r) => /연결/.test(r.scope))?.scope || sc[0].scope;
  const rows = sc.filter((r) => r.scope === scope).map((r) => ({ k: r.item.replace(/\(.*?\)/g, ''), v: EOK(N(r.value)) })).sort((a, b) => b.v - a.v).slice(0, 6);
  $('plantTitle').textContent = `${y} 사업부문별 매출`; $('plantAside').textContent = '억원 · 가동률 공시 없음';
  const ch = mk('plantChart');
  ch.setOption({ grid: { left: 150, right: 90, top: 10, bottom: 10 }, xAxis: { type: 'value', show: false },
    yAxis: { type: 'category', inverse: true, data: rows.map((r) => r.k), axisLabel: { color: C.text, fontSize: 16, width: 140, overflow: 'truncate' }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{ type: 'bar', barWidth: 14, itemStyle: { color: C.cyan, borderRadius: [0, 3, 3, 0] }, label: { show: true, position: 'right', color: '#fff', fontSize: 16, fontFamily: NUMF, formatter: (p) => fmt(p.value) }, data: rows.map((r) => r.v) }] });
  const tot = rows.reduce((s, r) => s + Math.max(0, r.v), 0);
  $('plantInsight').textContent = `최대 부문 ${rows[0].k} · 비중 ${tot ? ((rows[0].v / tot) * 100).toFixed(1) : '–'}% (표시 부문 합 기준)`;
}

function dial(id, v, color, max, band) {
  const ch = mk(id);
  ch.setOption({ series: [{ type: 'gauge', center: ['50%', '66%'], radius: '92%', min: Math.min(0, Math.floor((v ?? 0) / 10) * 10), max, splitNumber: 3, startAngle: 200, endAngle: -20,
    axisLine: { lineStyle: { width: 8, color: band ? [[band / max, 'rgba(255,255,255,.08)'], [1, 'rgba(124,195,106,.28)']] : [[1, 'rgba(255,255,255,.08)']] } },
    progress: { show: true, width: 8, itemStyle: { color } }, axisTick: { show: false },
    splitLine: { distance: -8, length: 8, lineStyle: { color: 'rgba(159,179,200,.55)', width: 1 } },
    axisLabel: { distance: 12, color: C.sub, fontSize: 13, fontFamily: NUMF, formatter: (x) => Math.round(x) + '%' },
    pointer: { show: false }, anchor: { show: false }, title: { show: false },
    detail: { offsetCenter: [0, '-6%'], formatter: (x) => (v == null ? '–' : x.toFixed(1) + '{u|%}'), color: '#fff', fontSize: 40, fontWeight: 600, fontFamily: NUMF, rich: { u: { fontSize: 18, color: C.unit, padding: [0, 0, 6, 2] } } },
    animationDuration: 1600, animationEasing: 'cubicOut', data: [{ value: v ?? 0 }] }] });
}
function initMarginGauges() {
  const y = YRS[YRS.length - 1];
  const va = metV(A, y, PRFK()), vb = B ? metV(B, y, PRFK()) : null;
  need(va != null, `${PRFL()} 계산값이 없습니다`);
  const max = Math.max(30, Math.ceil(Math.max(va, vb ?? 0) / 10) * 10), band = BANK() ? 10 : 20;
  $('profitAside').textContent = `${y} ${PRFL()} · 초록 ${band}%↑`;
  $('dialAName').textContent = A.company.name; dial('dialA', va, C.red, max, band);
  if (B) { $('dialBName').textContent = B.company.name; dial('dialB', vb, C.blue, max, band); }
  else { $('dialB').innerHTML = '<div class="err" style="color:var(--sub)">같은 산업 비교 기업 없음</div>'; }
  $('profitInsight').textContent = B && vb != null && vb > 0 && va > 0
    ? (va >= vb ? `${A.company.name} ${PRFL()}, ${B.company.name}의 ${(va / vb).toFixed(1)}배` : `${A.company.name} ${PRFL()}, ${B.company.name}보다 ${(vb - va).toFixed(1)}%p 낮음`)
    : `${A.company.name} ${y} ${PRFL()} ${va.toFixed(1)}%`;
}

function initQuarterlyRevenue() {
  const Q = quarters(A); need(Q.length, '분기 데이터가 없습니다');
  $('qrevTitle').textContent = `${A.company.name} 분기 ${TOPL()} & ${BANK() ? '영업이익' : '영업이익률'}`;
  const rev = Q.map((p) => EOK(qV(A, p, TOPK())));
  const line = BANK() ? Q.map((p) => EOK(qV(A, p, 'operating_profit')))
    : Q.map((p) => { const r = qV(A, p, 'revenue'), o = qV(A, p, 'operating_profit'); return r && o != null ? +((o / r) * 100).toFixed(2) : null; });
  const lmax = BANK() ? null : Math.max(30, Math.ceil(Math.max(...line.filter((v) => v != null), 0) / 10) * 10);
  const ch = mk('qrevChart');
  ch.setOption({
    animationDuration: 1200, grid: { left: 56, right: 46, top: 34, bottom: 30 },
    legend: { top: 0, textStyle: { color: C.text, fontSize: 15 }, itemWidth: 14, itemHeight: 9 },
    tooltip: { ...tip, formatter: (ps) => Q[ps[0].dataIndex] + '<br>' + ps.map((p) => `${p.marker}${p.seriesName} ${p.value == null ? '–' : p.seriesIndex && !BANK() ? p.value.toFixed(1) + '%' : fmt(p.value) + '억원'}`).join('<br>') },
    xAxis: { type: 'category', data: Q.map((q) => (q.endsWith('Q1') ? q.slice(0, 4) : '')), axisLabel: { ...axisTxt, interval: 0 }, axisTick: { show: false }, axisLine: { lineStyle: { color: 'rgba(169,189,208,.4)', width: 1.5 } } },
    yAxis: [{ type: 'value', splitNumber: 3, axisLabel: { ...axisTxt, fontSize: 14, formatter: (v) => fmt(v) }, splitLine: { lineStyle: { color: 'rgba(169,189,208,.12)' } } },
      BANK() ? { type: 'value', splitNumber: 3, axisLabel: { ...axisTxt, fontSize: 14, formatter: (v) => fmt(v) }, splitLine: { show: false } }
        : { type: 'value', min: Math.min(0, Math.floor(Math.min(...line.filter((v) => v != null), 0) / 10) * 10), max: lmax, splitNumber: 3, axisLabel: { ...axisTxt, fontSize: 14, formatter: '{value}%' }, splitLine: { show: false } }],
    series: [
      { name: `${TOPL()}(억원)`, type: 'bar', barWidth: 12, itemStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: C.blue }, { offset: 1, color: 'rgba(61,155,240,.35)' }] }, borderRadius: [3, 3, 0, 0] }, data: rev },
      { name: BANK() ? '영업이익(억원)' : '영업이익률(%)', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { width: 3, color: C.green }, itemStyle: { color: C.green }, data: line },
    ],
  });
}

/* 검색 관심도 칸: data/search_monthly.csv가 생기기 전까지는 주가 vs 시장지수 (제목에 표시) */
function initSearchTrend() {
  const S = A.stock.filter((r) => +r.date.slice(0, 4) >= YRS[0]);
  need(S.length, '주가 데이터(stock_daily.csv)가 없습니다');
  // 월말 값으로 줄여 원본 검색 관심도 차트와 같은 월 단위 모양
  const byM = {}; S.forEach((r) => { byM[r.date.slice(0, 7)] = r; });
  const months = Object.keys(byM).sort();
  const c = months.map((m) => N(byM[m].close)), k = months.map((m) => N(byM[m].index_close));
  const c0 = c.find((v) => v != null), k0 = k.find((v) => v != null);
  const ci = c.map((v) => (v == null ? null : +((v / c0) * 100).toFixed(1))), ki = k.map((v) => (v == null || !k0 ? null : +((v / k0) * 100).toFixed(1)));
  const peakI = ci.indexOf(Math.max(...ci.filter((v) => v != null))); const peakM = months[peakI];
  $('searchTitle').textContent = '주가 vs 시장지수'; $('searchAside').textContent = `월말 · ${months[0]}=100`;
  const ch = mk('searchChart');
  ch.setOption({
    animationDuration: 1600, grid: { left: 46, right: 18, top: 40, bottom: 30 },
    legend: { top: 0, textStyle: { color: C.text, fontSize: 15 }, itemWidth: 16, itemHeight: 9 },
    tooltip: { ...tip },
    xAxis: { type: 'category', data: months, boundaryGap: false, axisTick: { show: false }, axisLabel: { ...axisTxt, interval: 0, formatter: (v) => (v.endsWith('-01') ? v.slice(0, 4) : '') }, axisLine: { lineStyle: { color: 'rgba(169,189,208,.4)', width: 1.5 } } },
    yAxis: { type: 'value', scale: true, splitNumber: 2, axisLabel: { ...axisTxt, fontSize: 14 }, splitLine: { lineStyle: { color: 'rgba(169,189,208,.12)' } } },
    series: [
      { name: A.company.name + ' 주가', type: 'line', smooth: true, symbol: 'none', itemStyle: { color: C.cyan }, lineStyle: { width: 2.5, color: C.cyan }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(79,195,247,.32)' }, { offset: 1, color: 'rgba(0,0,0,0)' }] } }, data: ci,
        markLine: { symbol: 'none', silent: true, lineStyle: { type: 'dashed', color: C.orange, width: 1.5 }, label: { show: false }, data: [{ xAxis: peakM }] },
        markPoint: { symbol: 'circle', symbolSize: 12, itemStyle: { color: C.orange, borderColor: '#fff', borderWidth: 2 }, label: { show: true, position: peakI > months.length * 0.6 ? 'left' : 'right', distance: 10, color: '#fff', fontSize: 16, fontWeight: 500, formatter: `최고점 ${peakM}` }, data: [{ coord: [peakM, ci[peakI]] }] } },
      { name: '시장지수', type: 'line', smooth: true, symbol: 'none', itemStyle: { color: C.orange }, lineStyle: { width: 3, color: C.orange }, areaStyle: { color: 'rgba(242,160,61,.10)' }, data: ki },
    ],
  });
  const lc = ci[ci.length - 1], lk = ki[ki.length - 1];
  $('searchInsight').textContent = `${months[0]} 대비 주가 ${lc == null ? '–' : pct(lc - 100)} · 시장지수 ${lk == null ? '–' : pct(lk - 100)}`;
}

/* =====================================================================
   3D 지구본 (globe.gl) — 해외 종속회사
   ===================================================================== */
let TOPO = null;
let globe = null, playing = true, token = 0, sceneIdx = 0, idleTimer = null, userHold = false;
let maxCnt = 1, maxExp = 1;
const st = { points: [], arcs: [], rings: [], labels: [], polys: [] };
const countryFeat = {};
let GEO = {}; // 국가 → {lat,lng,en}
let EXPORT = {}; // 연도 → 억원

function estYear(r) { const m = String(r.established || '').match(/(19|20)\d{2}/); return m ? +m[0] : null; }
function foreign() { return A.subs.filter((r) => r.country && r.country !== '대한민국' && r.country !== '미확인' && N(r.lat) !== null); }
function entRows(y) {
  const by = {};
  foreign().forEach((r) => {
    const ey = estYear(r); if (ey !== null && ey > y) return;
    const o = (by[r.country] ??= { k: r.country, v: 0, prev: 0, nu: 0, names: [] });
    o.v++; o.names.push(r.name); if (ey === null || ey < y) o.prev++; if (ey === y) o.nu++;
  });
  return Object.values(by).sort((a, b) => b.v - a.v || a.k.localeCompare(b.k));
}
/* 해외 종속회사가 없는 회사: 같은 칸에 수출·해외 매출 비중을 보여 준다 (산업 KPI region_revenue, 매출과 같은 범위일 때만 비중 계산) */
function renderExportShare(y) {
  $('hudRankT').textContent = '수출·해외 매출 비중';
  const v = EXPORT[y], cons = exportOf(A, y, true), rev = finV(A, y, TOPK());
  const share = cons != null && rev ? (cons / rev) * 100 : null;
  const prevC = exportOf(A, y - 1, true), prevR = finV(A, y - 1, TOPK());
  const pShare = prevC != null && prevR ? (prevC / prevR) * 100 : null;
  const row = (rk, nm, val, g, gc) => `<div class="rrow"><span class="rk">${rk}</span><span class="nm">${nm}</span><span class="rv num">${val}</span><span class="rg num" style="color:${gc || C.sub}">${g}</span></div>`;
  let h = '<div style="color:var(--sub);font-size:15px;padding:2px 2px 8px">해외 종속회사 없음 (사업보고서 기준)</div>';
  if (v == null) h += '<div style="color:var(--sub);font-size:16px;padding:6px 2px">수출·해외 매출 공시 없음 (산업 KPI)</div>';
  else {
    h += row('', '수출 매출', fmt(v) + '억', '');
    if (share != null) h += row('', `${TOPL()} 대비`, share.toFixed(1) + '%', pShare == null ? '–' : (share - pShare >= 0 ? '+' : '') + (share - pShare).toFixed(1) + '%p', pShare == null ? null : share >= pShare ? C.green : C.red);
    else h += '<div style="color:var(--sub);font-size:14px;padding:4px 2px">매출과 집계 범위가 달라 비중은 계산하지 않음</div>';
  }
  $('rankRows').innerHTML = h;
}
function renderRank(y, activeK, shown) {
  $('hudRankY').textContent = y;
  if (!foreign().length) return renderExportShare(y);
  $('hudRankT').textContent = '국가별 해외 종속회사';
  const rows = entRows(y);
  $('rankRows').innerHTML = rows.slice(0, 8).map((r, i) => {
    const cls = (r.k === activeK ? 'active' : '') + (shown && !shown.has(r.k) ? ' wait' : '');
    return `<div class="rrow ${cls}"><span class="rk">${i + 1}</span><span class="nm">${esc(r.k)}</span><span class="rv num">${r.v}곳</span>
      <span class="rg num" style="color:${r.nu ? C.green : C.sub}">${r.prev === 0 && y > YRS[0] ? 'NEW' : r.nu ? '+' + r.nu : '–'}</span></div>`;
  }).join('') + (rows.length > 8 ? `<div class="rrow"><span class="rk"></span><span class="nm" style="color:var(--sub)">외 ${rows.length - 8}개국</span></div>` : '')
    + (rows.length ? '' : '<div style="color:var(--sub);font-size:16px;padding:6px 2px">해외 종속회사 없음 (사업보고서 기준)</div>');
}
function setTimeline(y) { document.querySelectorAll('.tl-dot').forEach((d) => d.classList.toggle('on', +d.dataset.y === y)); }
function setExport(y, from, anim) {
  const v = EXPORT[y];
  if (v == null) { $('expV').textContent = '공시 없음'; return; }
  if (anim) countUp($('expV'), v, { from: from ?? 0, dur: 1400 }); else $('expV').textContent = fmt(v);
}
function koreaPoint(y) {
  const v = EXPORT[y];
  return { kind: 'kr', lat: KOREA.lat, lng: KOREA.lng, alt: v == null ? 0.25 : 0.15 + 0.45 * (v / maxExp), color: C.cyan, r: 0.32,
    label: `<b>대한민국 · ${esc(A.company.name)}</b>` + (v == null ? '' : `<br>${y} ${esc($('expL').textContent)} ${fmt(v)}억원`) };
}
function rowOf(k, y) { return entRows(y).find((r) => r.k === k); }
function tipHtml(k, y) { const r = rowOf(k, y); return `<b>한국 → ${esc(k)}</b><br>${y}년 말 종속회사 ${r.v}곳` + (r.nu ? ` (그 해 설립 ${r.nu})` : '') + `<br><small>${r.names.slice(0, 4).map(esc).join('<br>')}${r.names.length > 4 ? '<br>외 ' + (r.names.length - 4) + '곳' : ''}</small>`; }
function entPoint(k, y) { const g = GEO[k], r = rowOf(k, y); return { kind: 'ent', k, lat: g.lat, lng: g.lng, alt: 0.04 + 0.32 * (r.v / maxCnt), color: C.orange, r: 0.28, label: tipHtml(k, y) }; }
function arcOf(k, y) { const g = GEO[k], r = rowOf(k, y); return { k, startLat: KOREA.lat, startLng: KOREA.lng, endLat: g.lat, endLng: g.lng, stroke: 0.5 + 1.3 * (r.v / maxCnt), label: tipHtml(k, y) }; }
function labelOf(k, y, animate) { const g = GEO[k]; return { k, y, lat: g.lat, lng: g.lng, animate }; }
function sync() { if (!globe) return; globe.pointsData([...st.points]).arcsData([...st.arcs]).ringsData([...st.rings]).htmlElementsData([...st.labels]).polygonsData([...st.polys]); }
function polyFor(k) { const n = GEO[k]?.en; return n && countryFeat[n] ? { k, f: countryFeat[n], kind: 'ent' } : null; }
function midView(a, b, extra = 0) {
  const toR = Math.PI / 180, toD = 180 / Math.PI;
  const [la1, lo1, la2, lo2] = [a.lat * toR, a.lng * toR, b.lat * toR, b.lng * toR];
  const x = Math.cos(la1) * Math.cos(lo1) + Math.cos(la2) * Math.cos(lo2), y = Math.cos(la1) * Math.sin(lo1) + Math.cos(la2) * Math.sin(lo2), z = Math.sin(la1) + Math.sin(la2);
  const d = Math.acos(Math.min(1, Math.sin(la1) * Math.sin(la2) + Math.cos(la1) * Math.cos(la2) * Math.cos(lo2 - lo1)));
  return { lat: Math.atan2(z, Math.hypot(x, y)) * toD - 14, lng: Math.atan2(y, x) * toD, altitude: Math.min(3.2, 1.5 + d * 1.15 + extra) };
}
function view(p, ms) { if (globe) globe.pointOfView(p, REDUCED ? 0 : ms); }
function burst(lat, lng, color, ms = 2600) { const r = { lat, lng, color, maxR: 5, speed: 4, period: 600 }; st.rings.push(r); sync(); setTimeout(() => { st.rings = st.rings.filter((x) => x !== r); sync(); }, ms); }
const krRing = { lat: KOREA.lat, lng: KOREA.lng, color: C.cyan, maxR: 6, speed: 3, period: 900 };
function krPoly() { return countryFeat['South Korea'] ? [{ kind: 'kr', f: countryFeat['South Korea'] }] : []; }
function clearScene() { st.points = []; st.arcs = []; st.labels = []; st.polys = krPoly(); st.rings = [krRing]; sync(); }
function overview() { const rows = entRows(YRS[YRS.length - 1]); if (!rows.length) return { lat: KOREA.lat - 10, lng: KOREA.lng, altitude: 2.2 };
  const lng = rows.reduce((s, r) => s + GEO[r.k].lng, 0) / rows.length; return { lat: 12, lng: Math.abs(lng - KOREA.lng) > 120 ? KOREA.lng : (lng + KOREA.lng) / 2, altitude: 2.8 }; }

function staticYear(y) {
  clearScene();
  const rows = entRows(y);
  st.points = [koreaPoint(y), ...rows.map((r) => entPoint(r.k, y))];
  st.arcs = rows.map((r) => arcOf(r.k, y));
  st.labels = rows.slice(0, 10).map((r) => labelOf(r.k, y, false));
  st.polys.push(...rows.map((r) => polyFor(r.k)).filter(Boolean));
  sync();
  $('hudYearV').textContent = y; setExport(y, null, false);
  renderRank(y, null, null); setTimeline(y);
  view(overview(), 1200);
}
async function guard(t, ms) { await sleep(ms); if (t !== token) throw 'cancel'; while (!playing || userHold) { await sleep(150); if (t !== token) throw 'cancel'; } }

async function sceneIntro(t) {
  const y0 = YRS[0];
  clearScene(); setTimeline(null);
  $('hudYearV').textContent = y0; $('expV').textContent = EXPORT[y0] == null ? '공시 없음' : '0'; renderRank(y0, null, new Set());
  view({ lat: 15, lng: -170, altitude: 3.5 }, 0);
  await guard(t, 300);
  view({ lat: KOREA.lat - 20, lng: KOREA.lng + 4, altitude: 1.8 }, 2200);
  await guard(t, 1400);
  st.points = [{ ...koreaPoint(y0), alt: 0.01 }]; sync();
  await guard(t, 50);
  st.points = [koreaPoint(y0)]; sync(); burst(KOREA.lat, KOREA.lng, C.cyan, 2000);
  $('caption').textContent = `${A.company.name}, 대한민국에서 세계로`; $('caption').classList.add('show');
  await guard(t, 2400);
  $('caption').classList.remove('show');
}
async function sceneYear(y, t) {
  setTimeline(y);
  st.arcs = []; st.labels = []; st.polys = krPoly(); st.points = st.points.filter((p) => p.kind === 'kr'); sync();
  const by = $('bigYear'); by.textContent = y; by.classList.remove('show'); void by.offsetWidth; by.classList.add('show');
  await guard(t, 900);
  $('hudYearV').textContent = y;
  setExport(y, y > YRS[0] ? EXPORT[y - 1] : 0, true);
  st.arcs = []; st.labels = []; st.polys = krPoly();
  st.points = [koreaPoint(y)]; sync(); burst(KOREA.lat, KOREA.lng, C.cyan, 1800);
  view({ lat: KOREA.lat - 20, lng: KOREA.lng + 4, altitude: 1.9 }, 1000);
  const rows = entRows(y); const shown = new Set();
  renderRank(y, null, shown);
  await guard(t, 1300);
  // 국가가 많으면 상위 6개국만 하나씩 날아가고 나머지는 한 번에 표시
  const step = rows.slice(0, 6), rest = rows.slice(6);
  for (const r of step) {
    const g = GEO[r.k];
    view(midView(KOREA, g), 1200);
    renderRank(y, r.k, shown);
    st.arcs.push(arcOf(r.k, y)); sync();
    await guard(t, 1300);
    shown.add(r.k);
    st.points.push(entPoint(r.k, y));
    const pf = polyFor(r.k); if (pf) st.polys.push(pf);
    st.labels.push(labelOf(r.k, y, true)); sync();
    burst(g.lat, g.lng, C.orange, 2600);
    renderRank(y, r.k, shown);
    await guard(t, r.prev === 0 && y > YRS[0] ? 1700 : 900);
  }
  if (rest.length) {
    rest.forEach((r) => { shown.add(r.k); st.arcs.push(arcOf(r.k, y)); st.points.push(entPoint(r.k, y)); const pf = polyFor(r.k); if (pf) st.polys.push(pf); });
    sync(); view(overview(), 1500); await guard(t, 1500);
  }
  renderRank(y, null, shown);
  view(overview(), 1500);
  await guard(t, 3200);
}
async function sceneOutro(t) {
  const y = YRS[YRS.length - 1];
  setTimeline(y);
  st.arcs = st.arcs.map((a) => ({ ...a, stroke: a.stroke * 1.4, bright: true })); sync();
  const rows = entRows(y), cnt = rows.reduce((s, r) => s + r.v, 0);
  $('caption').textContent = (EXPORT[y] != null ? `${y} ${$('expL').textContent} ${joEok(EXPORT[y])} · ` : '') + (cnt ? `해외 종속회사 ${cnt}곳 · ${rows.length}개국` : '해외 종속회사 없음 (사업보고서 기준)');
  $('caption').classList.add('show');
  globe.controls().autoRotate = true; globe.controls().autoRotateSpeed = 0.6;
  try { await guard(t, 5200); } finally { globe.controls().autoRotate = false; $('caption').classList.remove('show'); }
}
let SCENES = [];
let runningToken = -1;
async function runFrom(i) {
  const t = ++token; runningToken = t;
  try { for (let k = i; ; k = (k + 1) % SCENES.length) { sceneIdx = k; await SCENES[k](t); } }
  catch (e) { if (e !== 'cancel') console.error(e); }
}
function setPlaying(p) { playing = p; $('playBtn').textContent = p ? '❚❚' : '▶'; }
function playGlobe() { if (REDUCED || !globe) return; setPlaying(true); if (runningToken !== token) runFrom(Math.max(1, Math.min(YRS.length, sceneIdx))); }
function pauseGlobe() { setPlaying(false); }
function gotoYear(y) {
  if (!globe) return;
  token++; setPlaying(false); sceneIdx = YRS.indexOf(y) + 1;
  $('caption').classList.remove('show'); $('bigYear').classList.remove('show'); globe.controls().autoRotate = false;
  staticYear(y);
}
function restartGlobe() { setPlaying(true); runFrom(0); }

function initExportGlobe() {
  window.__globeInit = true;
  const el = $('globe');
  const hasGL = (() => { try { const c = document.createElement('canvas'); return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl'))); } catch (e) { return false; } })();
  if (typeof Globe !== 'function') { showGlobeErr('globe.gl 라이브러리를 불러오지 못했습니다'); return initGlobeFallback(); }
  if (!TOPO) { showGlobeErr('지도 데이터(assets/geo/countries-110m.json)를 불러오지 못했습니다'); return initGlobeFallback(); }
  if (typeof topojson === 'undefined') { showGlobeErr('topojson 라이브러리를 불러오지 못했습니다'); return initGlobeFallback(); }
  if (!hasGL) { showGlobeErr('이 브라우저에서 WebGL을 쓸 수 없어 막대 차트로 대신 표시합니다'); return initGlobeFallback(); }
  const feats = topojson.feature(TOPO, TOPO.objects.countries).features.filter((f) => f.properties.name !== 'Antarctica');
  feats.forEach((f) => { if (f.geometry.type === 'MultiPolygon') f.geometry.coordinates = f.geometry.coordinates.filter((poly) => new Set(poly[0].map((pt) => pt.join(','))).size >= 3); });
  feats.forEach((f) => { countryFeat[f.properties.name] = f; });
  const W = el.clientWidth, H = el.clientHeight;
  globe = Globe({ animateIn: false })(el)
    .width(W).height(H)
    .backgroundColor('rgba(0,0,0,0)')
    .showAtmosphere(true).atmosphereColor('#3E9BD8').atmosphereAltitude(0.14)
    .showGraticules(false)
    .hexPolygonsData(feats).hexPolygonResolution(3).hexPolygonMargin(0.5).hexPolygonUseDots(true)
    .hexPolygonColor((f) => (f.properties.name === 'South Korea' ? C.cyan : 'rgba(150,185,215,0.42)'))
    .polygonsData([]).polygonGeoJsonGeometry((d) => d.f.geometry).polygonAltitude(0.006)
    .polygonCapColor((d) => (d.kind === 'kr' ? 'rgba(79,195,247,0.22)' : 'rgba(255,255,255,0.05)'))
    .polygonSideColor(() => 'rgba(0,0,0,0)').polygonStrokeColor((d) => (d.kind === 'kr' ? 'rgba(79,195,247,.95)' : 'rgba(242,160,61,.9)')).polygonsTransitionDuration(600)
    .pointsData([]).pointAltitude('alt').pointColor('color').pointRadius('r').pointsMerge(false).pointsTransitionDuration(REDUCED ? 0 : 900)
    .pointLabel('label')
    .arcsData([]).arcStartLat('startLat').arcStartLng('startLng').arcEndLat('endLat').arcEndLng('endLng')
    .arcStroke('stroke').arcAltitudeAutoScale(0.45)
    .arcColor((d) => (d.bright ? ['rgba(150,220,255,1)', 'rgba(255,255,255,1)'] : ['rgba(79,195,247,0.9)', 'rgba(255,255,255,0.85)']))
    .arcDashLength(0.35).arcDashGap(0.15).arcDashInitialGap(() => 1).arcDashAnimateTime(REDUCED ? 0 : 1800)
    .arcsTransitionDuration(REDUCED ? 0 : 1200).arcLabel('label')
    .ringsData([krRing]).ringColor((d) => (tt) => (d.color === C.cyan ? `rgba(79,195,247,${0.8 * (1 - tt)})` : `rgba(242,160,61,${0.8 * (1 - tt)})`))
    .ringMaxRadius('maxR').ringPropagationSpeed('speed').ringRepeatPeriod('period')
    .htmlElementsData([]).htmlAltitude(0.02)
    .htmlElement((d) => {
      const r = rowOf(d.k, d.y) || { v: 0, prev: 0, nu: 0 };
      const isNew = r.prev === 0 && d.y > YRS[0];
      const wrap = document.createElement('div'); wrap.style.cssText = 'width:0;height:0;position:relative;pointer-events:none';
      const div = document.createElement('div'); div.className = 'glabel ' + (GEO[d.k].lng < KOREA.lng - 60 ? 'left' : GEO[d.k].lat < KOREA.lat - 25 ? 'right' : 'below'); wrap.appendChild(div);
      div.innerHTML = `<div class="n">${esc(d.k)}${isNew ? '<span class="new">NEW</span>' : ''}</div>
        <div class="v num"><span class="cv">${d.animate ? 0 : r.v}</span><span class="u">곳</span></div>
        ${r.nu && !isNew ? `<div class="g num" style="color:${C.green}">${d.y}년 설립 +${r.nu}</div>` : ''}`;
      if (d.animate) countUp(div.querySelector('.cv'), r.v, { dur: 1000 });
      return wrap;
    });
  if (globe.htmlElementVisibilityModifier) globe.htmlElementVisibilityModifier((e, vis) => { e.style.opacity = vis ? 1 : 0; });
  const mat = globe.globeMaterial(); mat.color.set('#0D2033'); if (mat.emissive) { mat.emissive.set('#0b2238'); mat.emissiveIntensity = 0.25; } mat.shininess = 4;
  window.__globe = globe; window.__globeOK = true;
  globe.renderer().domElement.addEventListener('webglcontextlost', (e) => { e.preventDefault(); showGlobeErr('그래픽(WebGL) 연결이 끊겼습니다. 새로고침(F5) 해주세요.'); });
  const ctr = globe.controls(); ctr.minDistance = 100 * 2.2; ctr.maxDistance = 100 * 5; ctr.enablePan = false;
  ctr.addEventListener('start', () => { userHold = true; clearTimeout(idleTimer); });
  ctr.addEventListener('end', () => { clearTimeout(idleTimer); idleTimer = setTimeout(() => { userHold = false; }, 6000); });
  globe.renderer().setPixelRatio(Math.min(2, devicePixelRatio || 1));
  document.addEventListener('visibilitychange', () => { if (!globe) return; document.hidden ? globe.pauseAnimation() : globe.resumeAnimation(); });
  if (REDUCED) { setPlaying(false); staticYear(YRS[YRS.length - 1]); } else restartGlobe();
}
function initGlobeFallback() {
  const fb = $('globeFallback'); fb.style.display = 'block';
  ['hudYear', 'hudRank', 'hudExport', 'hudTimeline'].forEach((id) => { $(id).style.display = 'none'; });
  const rows = entRows(YRS[YRS.length - 1]).slice(0, 10);
  if (!rows.length) { fb.innerHTML = '<div class="err" style="color:var(--sub)">해외 종속회사 없음 (사업보고서 기준)</div>'; return; }
  const ch = mk('globeFallback');
  ch.setOption({ grid: { left: 130, right: 80, top: 30, bottom: 30 }, xAxis: { type: 'value', axisLabel: axisTxt, splitLine: { lineStyle: { color: 'rgba(169,189,208,.12)' } } },
    yAxis: { type: 'category', inverse: true, data: rows.map((r) => r.k), axisLabel: { ...axisTxt, fontSize: 20, color: '#fff' } },
    series: [{ type: 'bar', barWidth: 22, itemStyle: { color: C.red }, label: { show: true, position: 'right', color: '#fff', fontSize: 18, formatter: (p) => p.value + '곳' }, data: rows.map((r) => r.v) }] });
}

/* =====================================================================
   발표 모드
   ===================================================================== */
function toggleFS() { try { if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {}); else document.exitFullscreen().catch(() => {}); } catch (e) { /* 미지원 */ } }
function setCompany(c) {
  if (c === 'B' && !B) return;
  cur = c;
  document.querySelectorAll('#coToggle button').forEach((b) => b.classList.toggle('on', b.dataset.co === c));
  $('hudNS').style.display = c === 'B' ? 'block' : 'none';
  safe(renderKpi, 'kpis');
}
function initPresenterKeys() {
  $('fsBtn').onclick = toggleFS;
  $('playBtn').onclick = () => (playing ? pauseGlobe() : playGlobe());
  addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    const k = e.key;
    if (k === 'f' || k === 'F') toggleFS();
    else if (k === ' ') { e.preventDefault(); playing ? pauseGlobe() : playGlobe(); }
    else if (/^[1-9]$/.test(k) && YRS[+k - 1]) gotoYear(YRS[+k - 1]);
    else if (k === 'ArrowRight' || k === 'ArrowLeft') { const c0 = Math.min(YRS.length, Math.max(1, sceneIdx)); const n = Math.min(YRS.length, Math.max(1, c0 + (k === 'ArrowRight' ? 1 : -1))); gotoYear(YRS[n - 1]); }
    else if (k === 's' || k === 'S') setCompany(cur === 'A' ? 'B' : 'A');
    else if (k === 'r' || k === 'R') { if (!REDUCED && globe) restartGlobe(); }
    else if (k === '?' || k === '/') $('help').classList.toggle('show');
    else if (k === 'Escape') {
      if ($('help').classList.contains('show')) { $('help').classList.remove('show'); return; }
      if (document.fullscreenElement) return;
      if (window.parent !== window) window.parent.postMessage({ ubda: 'screen-exit' }, '*'); else location.href = `dashboard.html?c=${SLUG}`;
    }
  });
  let ct; const show = () => { document.body.classList.remove('hide-cursor'); clearTimeout(ct); ct = setTimeout(() => document.body.classList.add('hide-cursor'), 3000); };
  addEventListener('mousemove', show); show();
}
function safe(fn, id) {
  try { fn(); }
  catch (e) {
    if (!e?.soft) console.error(e);
    if (id && $(id)) $(id).innerHTML = e?.soft ? `<div class="err" style="color:var(--sub)">${esc(e.message)}</div>` : '<div class="err">데이터를 불러오지 못했습니다<br><small>' + esc(e && e.message || e) + '</small></div>';
  }
}

/* 비교 기업: company.json competitors 중 UBDA에 있는 첫 기업 → 없으면 같은 산업의 다른 기업 */
function pickPeer(index) {
  const all = Array.isArray(index?.companies) ? index.companies : [];
  const me = A.company;
  for (const n of me.competitors || []) { const f = all.find((c) => c.name === n && c.slug !== SLUG && c.has_data !== false); if (f) return f.slug; }
  const same = all.filter((c) => c.industry === me.industry && c.slug !== SLUG && c.has_data !== false);
  return same.length ? same[0].slug : null;
}

(async function boot() {
  initPresenterKeys();
  if (!SLUG) { document.body.innerHTML = '<p style="color:#fff;padding:40px">주소에 ?c=기업 이 필요합니다.</p>'; return; }
  A = await loadCompany(SLUG);
  if (!A.company) { $('mainTitle').textContent = '기업 정보를 불러오지 못했습니다'; return; }
  const index = await get('companies/index.json', true);
  const peer = pickPeer(index);
  B = peer ? await loadCompany(peer) : null;
  if (B && !B.company) B = null;
  const sy = +A.company.start_year || 0;
  const ys = [...new Set(A.fin.map((r) => +r.year))].filter((y) => y >= sy).sort();
  YRS = ys.slice(-3);
  foreign().forEach((r) => { GEO[r.country] = { lat: +r.lat, lng: +r.lng, en: r.country_en || null }; });
  YRS.forEach((y) => { const v = exportOf(A, y); EXPORT[y] = v == null ? null : v / 1e8; });
  maxCnt = Math.max(1, ...entRows(YRS[YRS.length - 1]).map((r) => r.v));
  maxExp = Math.max(1, ...Object.values(EXPORT).filter((v) => v != null));
  SCENES = [sceneIntro, ...YRS.map((y) => (t) => sceneYear(y, t)), sceneOutro];

  const name = A.company.name, y0 = YRS[0], y1 = YRS[YRS.length - 1];
  document.title = `${name} 경영 모니터링 · 메인 스크린`;
  $('mainTitle').textContent = `${name} 경영 모니터링`;
  const scope = A.fin.find((r) => +r.year === y1)?.scope || '';
  $('metaLeft').innerHTML = `${esc(name)}${B ? ` <b>vs</b> ${esc(B.company.name)}` : ''} · <b class="num">${y0}–${y1}</b> · ${esc(scope)} 재무제표 기준`;
  $('clockSub').textContent = `사업보고서 ${y0}–${y1}`;
  $('coToggle').innerHTML = `<button data-co="A" class="on">${esc(name)}</button>` + (B ? `<button data-co="B">${esc(B.company.name)}</button>` : '');
  document.querySelectorAll('#coToggle button').forEach((b) => { b.onclick = () => setCompany(b.dataset.co); });
  $('globeTitle').textContent = `${name}, 대한민국에서 세계로`;
  $('hudNS').textContent = `해외 진출 지구본은 ${name} 기준`;
  $('hudYearS').textContent = `${(A.company.name_en || '').toUpperCase()} · GLOBAL`;
  const sub = A.subs[0];
  $('hudNote').innerHTML = `해외 종속회사: 사업보고서 '연결대상 종속회사 현황' · 설립일 기준 연도별 누적<br>출처: ${esc(name)} ${esc(sub?.report || '사업보고서')}`
    + (!A.subs.length ? '<br><b style="color:var(--orange)">종속회사 표 미수집</b>' : A.subs.every((r) => r.country === '종속회사 없음') ? '<br>종속회사 없음 (원문 표 \'-\')' : '');
  const hasExp = Object.values(EXPORT).some((v) => v != null);
  $('expN').textContent = hasExp ? exportScope(A).slice(0, 40) : '산업 KPI에 수출·해외 매출 없음';
  if (!hasExp) { $('hudExport').style.opacity = '.6'; $('hudExport').querySelector('.u').style.display = 'none'; $('expV').style.fontSize = '24px'; }
  $('tlDots').innerHTML = YRS.map((y, i) => `${i ? '<span class="tl-line"></span>' : ''}<span class="tl-dot" data-y="${y}"><i></i>${y}</span>`).join('');
  document.querySelectorAll('.tl-dot').forEach((d) => { d.onclick = () => gotoYear(+d.dataset.y); });

  safe(renderKpi, 'kpis');
  safe(initQuarterlyOp, 'qopChart');
  safe(initPlantGauges, 'plantChart');
  safe(initMarginGauges, 'dialA');
  safe(initQuarterlyRevenue, 'qrevChart');
  safe(initSearchTrend, 'searchChart');
  try { TOPO = await (await fetch('assets/geo/countries-110m.json')).json(); } catch (e) { console.error(e); TOPO = null; }
  try { initExportGlobe(); }
  catch (e) { console.error(e); showGlobeErr(e && e.message || e); try { initGlobeFallback(); } catch (_) { /* 무시 */ } }
  addEventListener('resize', () => { charts.forEach((c) => c.resize()); });
  addEventListener('mousedown', () => window.focus());
  window.__screenReady = true;
})();
})();
