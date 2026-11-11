/* 기업 목록 화면 — companies/index.json을 읽어 산업 → 카테고리 → 기업 순으로 보여줍니다.
 * 3D 뉴런 포털도 같은 파일(graph.nodes / graph.links)을 읽게 됩니다. */
'use strict';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v, d = 1) => (v === null || v === undefined || v === '' ? '–' : new Intl.NumberFormat('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(v));
let IDX = null;

function card(c, color) {
  const k = c.kpis || {};
  const v = c.verification || {};
  const st = c.has_data
    ? `<span class="st st-auto">재무 ${c.latest_year}년까지</span><span class="st ${v['불일치'] ? 'st-bad' : 'st-ok'}">원문 대조 ${v['원문 대조 일치'] ?? 0}</span><span class="st st-na">산업 KPI ${c.industry_kpis_found ?? 0}/${c.industry_kpis_total ?? 0}</span>`
    : '<span class="st st-warn">데이터 수집 전</span>';
  return `<a class="p-card" href="${esc(c.dashboard_path)}" style="--c:${esc(c.theme_color || color)}">
    <div class="t"><b>${esc(c.name)}</b><small>${esc(c.stock_code)}</small></div>
    ${c.has_data ? `<div class="p-kpi"><div>매출액<b>${nf(k.revenue / 1e8, 0)}억</b></div><div>영업이익률<b>${nf(k.operating_margin_pct)}%</b></div><div>매출 증가율<b>${nf(k.revenue_growth_pct)}%</b></div></div>` : ''}
    <div class="p-badges">${st}</div>
    <span class="p-open">대시보드 열기 →</span></a>`;
}

function render() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const inds = IDX.industries;
  const match = (c) => !q || [c.name, c.name_en, c.stock_code, inds[c.industry]?.name, ...(c.categories || [])].join(' ').toLowerCase().includes(q);
  const groups = {};
  IDX.companies.filter(match).forEach((c) => {
    (c.categories?.length ? c.categories : ['기타']).forEach((cat) => {
      ((groups[c.industry] ||= {})[cat] ||= []).push(c);
    });
  });
  const html = Object.entries(groups).map(([ind, cats]) => `<section class="p-ind"><h2><i style="background:${esc(inds[ind]?.color)}"></i>${esc(inds[ind]?.name || ind)}</h2>
    ${Object.entries(cats).map(([cat, cs]) => `<div class="p-cat">${esc(cat)}</div><div class="p-grid">${cs.map((c) => card(c, inds[ind]?.color)).join('')}</div>`).join('')}</section>`).join('');
  document.getElementById('list').innerHTML = html || '<div class="empty"><b>검색 결과가 없습니다</b></div>';
}

(async function init() {
  try {
    IDX = await (await fetch('companies/index.json', { cache: 'no-cache' })).json();
  } catch (e) {
    document.getElementById('meta').textContent = '';
    document.getElementById('list').innerHTML = '<div class="empty"><b>기업 목록(companies/index.json)을 읽지 못했습니다</b>python scripts/build_index.py 를 실행하거나, 로컬에서는 python -m http.server 8000 으로 여세요.</div>';
    return;
  }
  document.getElementById('meta').textContent = `기업 ${IDX.companies.length}개 · 산업 ${new Set(IDX.companies.map((c) => c.industry)).size}개 · 목록 갱신 ${IDX.updated_at}`;
  document.getElementById('q').addEventListener('input', render);
  render();
})();
