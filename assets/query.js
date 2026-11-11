/* 데이터 질의 패널 — 규칙 기반 (AI 호출 없음). 불닭 대시보드의 질의 패널을 기업 무관하게 옮긴 것.
 * 답변 규칙: 사용한 행·산식·단위·기간·출처를 표시 / 데이터에 없으면 '미확인' / 원인을 수치로 단정하지 않음
 * app.js의 D·S·fin·met 등을 그대로 사용합니다 (같은 페이지의 일반 스크립트).
 */
'use strict';
(function () {
  const FEED = [];
  // 지표 사전: 긴 표현 먼저. t = won(원 단위 계정) / pct(비율 %) / turn(회)
  const QM = [
    { re: /재고\s*(자산)?\s*회전율/, k: 'inventory_turnover', t: 'turn', l: '재고자산회전율' },
    { re: /총?\s*자산\s*회전율/, k: 'asset_turnover', t: 'turn', l: '총자산회전율' },
    { re: /영업\s*이익률|이익률/, k: 'operating_margin_pct', t: 'pct', l: '영업이익률' },
    { re: /순\s*이익률/, k: 'net_margin_pct', t: 'pct', l: '순이익률' },
    { re: /매출\s*원가율|원가율/, k: 'cost_ratio_pct', t: 'pct', l: '매출원가율' },
    { re: /판관비율|판매비와관리비율/, k: 'sga_ratio_pct', t: 'pct', l: '판관비율' },
    { re: /부채\s*비율/, k: 'debt_ratio_pct', t: 'pct', l: '부채비율' },
    { re: /유동\s*비율/, k: 'current_ratio_pct', t: 'pct', l: '유동비율' },
    { re: /자기\s*자본\s*비율/, k: 'equity_ratio_pct', t: 'pct', l: '자기자본비율' },
    { re: /ROE|자기자본\s*이익률/i, k: 'roe_pct', t: 'pct', l: 'ROE' },
    { re: /ROA|총자산\s*이익률/i, k: 'roa_pct', t: 'pct', l: 'ROA' },
    { re: /잉여\s*현금|FCF/i, k: 'simple_fcf', t: 'wonm', l: '단순 잉여현금흐름' },
    { re: /영업\s*활동\s*현금\s*흐름|영업\s*현금\s*흐름|영업\s*현금/, k: 'operating_cashflow', t: 'won', l: '영업활동현금흐름' },
    { re: /유형자산\s*취득|설비\s*투자|capex/i, k: 'capex', t: 'won', l: '유형자산 취득' },
    { re: /순\s*이익|당기\s*순이익/, k: 'net_income', t: 'won', l: '당기순이익' },
    { re: /영업\s*이익/, k: 'operating_profit', t: 'won', l: '영업이익' },
    { re: /매출\s*원가/, k: 'cost_of_sales', t: 'won', l: '매출원가' },
    { re: /판관비|판매비/, k: 'sga', t: 'won', l: '판매비와관리비' },
    { re: /재고\s*자산|재고/, k: 'inventories', t: 'won', l: '재고자산' },
    { re: /현금\s*및|현금성/, k: 'cash', t: 'won', l: '현금및현금성자산' },
    { re: /유동\s*자산/, k: 'current_assets', t: 'won', l: '유동자산' },
    { re: /유동\s*부채/, k: 'current_liabilities', t: 'won', l: '유동부채' },
    { re: /자산\s*총계|총\s*자산/, k: 'total_assets', t: 'won', l: '자산총계' },
    { re: /부채\s*총계|총\s*부채/, k: 'total_liabilities', t: 'won', l: '부채총계' },
    { re: /자본\s*총계|자기\s*자본/, k: 'total_equity', t: 'won', l: '자본총계' },
    { re: /매출액|매출/, k: 'revenue', t: 'won', l: '매출액' },
  ];
  // 산업 KPI 단어 → industries/*.json의 kpi key (데이터가 없으면 '미확인')
  const KPI_WORDS = [
    [/수출|해외\s*매출/, ['export_revenue', 'overseas_sales']], [/해외\s*법인|법인/, ['overseas_entities']], [/제품군|품목|제품별|부문별|사업부/, ['product_segment_revenue', 'segment_revenue']],
    [/원재료|원료|밀가루|팜유/, ['raw_material_prices']], [/가동률|생산\s*능력|생산량/, ['capacity_utilization', 'capacity', 'production_volume']],
    [/점유율/, ['market_share']], [/판매\s*경로|채널|대형\s*마트|편의점|특약점|대리점/, ['sales_channels']], [/환율/, ['fx_rate']], [/검색|관심도|트렌드/, ['search_interest']], [/브랜드/, ['brand_sales']],
    [/NIM|순이자마진/i, ['nim']], [/연체율/, ['delinquency_rate']], [/판매\s*대수|판매량/, ['sales_volume']], [/점포/, ['store_count']], [/MAU|이용자/i, ['mau']],
  ];

  const signed = (v, u, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '계산 불가' : `${v > 0 ? '+' : ''}${fmt(v, d)}${u}`);
  const showV = (v, t) => (v === null || v === undefined ? '데이터 없음' : t === 'won' || t === 'wonm' ? eok(v) : t === 'pct' ? pct(v, 2) : `${fmt(v, 2)}회`);
  const val = (DD, y, m) => (m.t === 'won' ? N(DD.fin.find((r) => +r.year === y && r.metric === m.k)?.value) : N(DD.met.find((r) => +r.year === y && r.metric === m.k)?.value));
  const yearsOf = (DD) => [...new Set(DD.fin.map((r) => +r.year))].sort();

  function auditIds(DD, y, m) {
    if (m.t === 'won') return [`F-${y}-${m.k}`];
    return (DD.met.find((r) => +r.year === y && r.metric === m.k)?.input_audit_ids || '').split(';').filter(Boolean);
  }
  function usedRows(DD, ids) {
    const led = new Map(DD.ledger.map((r) => [r.audit_id, r]));
    return ids.map((id) => { const a = led.get(id); return { key: `${DD.company.name} · ${id}`, raw: a ? `${a.value === '' ? '(빈 값)' : Number(a.value).toLocaleString('ko-KR') + ' 원'} · ${a.result}` : '(행 없음)' }; });
  }
  function sourcesOf(DD, ids) {
    const led = new Map(DD.ledger.map((r) => [r.audit_id, r])); const reg = new Map(DD.reg.map((r) => [r.source_id, r]));
    const out = new Map();
    ids.forEach((id) => { const a = led.get(id); const s = a && reg.get(a.source_id); if (s) out.set(s.source_url, s.title); });
    return [...out].map(([url, label]) => ({ url, label }));
  }
  const formulaOf = (DD, y, m) => (m.t === 'won' ? '억원 = 원 ÷ 100,000,000 (표시만 반올림)' : DD.met.find((r) => +r.year === y && r.metric === m.k)?.formula || '');

  function parseQ(q) {
    const t = q.replace(/\s+/g, ' ');
    const years = [...new Set([...t.matchAll(/(20\d{2})\s*년?/g)].map((m) => +m[1]))];
    const qm = t.match(/([1-4])\s*분기|Q\s*([1-4])/i);
    const others = (INDEX?.companies || []).filter((c) => c.slug !== SLUG && (t.includes(c.name) || (c.name_en && t.toLowerCase().includes(c.name_en.toLowerCase()))));
    const metrics = []; let rest = t;
    for (const d of QM) { if (rest.match(d.re)) { metrics.push(d); rest = rest.replace(d.re, ' '); } }
    return {
      t, years, quarter: qm ? +(qm[1] || qm[2]) : null, others, metrics,
      growth: /증가율|성장률|증감|변화|늘었|줄었|감소율|대비|전년/.test(t), trend: /추이|흐름|변화|몇\s*년|연도별|매년/.test(t),
      why: /왜|원인|이유|때문/.test(t), stock: /주가|주식|수익률|시가/.test(t),
    };
  }
  const unknown = (q, why, extra = []) => ({ q, unknown: true, period: '-', conclusion: `미확인 — ${why}`, evidence: extra });

  async function answer(q) {
    const P = parseQ(q);
    const Y = yearsOf(D); const ly = Y[Y.length - 1];
    if (!Y.length) return unknown(q, '이 기업은 아직 재무 데이터가 수집되지 않았습니다.');
    // 산업 KPI 질문
    const kw = KPI_WORDS.find(([re]) => re.test(P.t));
    if (kw && !P.stock) {
      const rows = D.kpi.filter((r) => kw[1].includes(r.kpi_key) && (!P.years.length || P.years.includes(+r.year)));
      if (!rows.length) {
        const st = D.status.find((r) => kw[1].includes(r.key));
        return unknown(q, `${st ? `'${st.label}'` : '해당 지표'}는 아직 공시 원문에서 수집하지 않았습니다. 추정값을 만들지 않습니다.`, st ? [['찾을 곳', st.where], ['주의', st.caution || '-']] : []);
      }
      return {
        q, period: [...new Set(rows.map((r) => r.period || r.year))].join(', '), conclusion: rows.map((r) => `${r.period || r.year} ${r.item}${r.scope ? `(${r.scope})` : ''}: ${r.value === '' ? r.status : r.unit === 'KRW' ? eok(N(r.value)) : `${fmt(N(r.value), 2)} ${r.unit}`}`).join(' / '),
        evidence: rows.map((r) => [`${r.period || r.year} ${r.item}`, `${r.status}`]), used: rows.map((r) => ({ key: `kpi_values.csv · ${r.kpi_key} ${r.year}`, raw: `${r.value} ${r.unit} · ${r.source_location}` })),
        sources: rows.filter((r) => r.source_url).map((r) => ({ url: r.source_url, label: r.source_location || r.source_url })), limits: ['산업 KPI는 AI가 공시 원문에서 옮긴 값일 수 있습니다. 상태가 ‘원문 대조 일치’가 아니면 사람 확인 전입니다.'], goto: 'industry',
      };
    }
    // 주가
    if (P.stock) {
      if (!D.stock.length) return unknown(q, '주가 데이터가 없습니다.');
      const y = P.years.length ? Math.max(...P.years) : ly;
      const rows = D.stock.filter((r) => r.date.startsWith(String(y)));
      if (!rows.length) return unknown(q, `${y}년 주가 자료가 없습니다 (수집 기간 ${D.stock[0].date} ~ ${D.stock[D.stock.length - 1].date}).`);
      const a = rows[0], b = rows[rows.length - 1]; const r = (N(b.close) / N(a.close) - 1) * 100;
      const ka = N(a.index_close), kb = N(b.index_close); const kr = ka && kb ? (kb / ka - 1) * 100 : null;
      return {
        q, period: `${a.date} ~ ${b.date}`, conclusion: `${D.company.name} 주가는 ${a.date} ${fmt(N(a.close), 0)}원에서 ${b.date} ${fmt(N(b.close), 0)}원으로 ${signed(r, '%')} 변했습니다${kr === null ? '' : ` (같은 기간 시장지수 ${signed(kr, '%')})`}.`,
        evidence: [[`${a.date} 종가`, `${fmt(N(a.close), 0)}원`], [`${b.date} 종가`, `${fmt(N(b.close), 0)}원`], ['기간 수익률', signed(r, '%')], ['시장지수 수익률', signed(kr, '%')]],
        formula: ['수익률 = (마지막 종가 ÷ 첫 종가 − 1) × 100', '배당 미포함 · 비수정 종가'], used: [{ key: `stock_daily.csv · ${a.date}`, raw: a.close }, { key: `stock_daily.csv · ${b.date}`, raw: b.close }],
        sources: [{ url: '', label: a.source }], limits: ['주가 변동의 원인은 수치만으로 확정하지 않습니다.', '액면분할이 있으면 비수정 종가 비교가 왜곡될 수 있습니다.'], goto: 'stock',
      };
    }
    if (!P.metrics.length) return unknown(q, '질문에서 지표(매출·영업이익·영업이익률·부채비율 등)를 찾지 못했습니다.', [['예시', '2025년 영업이익률은? / 2024년 대비 2025년 매출 증가율은? / 2025년 3분기 영업이익은?']]);
    const m = P.metrics[0];
    // 분기
    if (P.quarter) {
      const qk = { revenue: 1, cost_of_sales: 1, sga: 1, operating_profit: 1, net_income: 1, operating_margin_pct: 1 };
      if (!qk[m.k]) return unknown(q, `분기 자료에는 매출·매출원가·판관비·영업이익·순이익과 영업이익률만 있습니다 ('${m.l}' 분기값 없음).`);
      const y = P.years.length ? Math.max(...P.years) : ly;
      const get = (yy, k) => D.qtr.find((r) => +r.year === yy && +r.quarter === P.quarter && r.metric === k);
      const vOf = (yy) => (m.k === 'operating_margin_pct' ? (get(yy, 'revenue') && get(yy, 'operating_profit') ? (N(get(yy, 'operating_profit').value) / N(get(yy, 'revenue').value)) * 100 : null) : N(get(yy, m.k)?.value ?? null));
      const v = vOf(y), p = vOf(y - 1);
      if (v === null) return unknown(q, `${y}년 ${P.quarter}분기 ${m.l} 자료가 없습니다.`);
      const ids = m.k === 'operating_margin_pct' ? [get(y, 'revenue').audit_id, get(y, 'operating_profit').audit_id] : [get(y, m.k).audit_id];
      const d = m.k === 'operating_margin_pct' ? (p === null ? null : v - p) : growth(v, p);
      return {
        q, period: `${y}-Q${P.quarter}`, conclusion: `${D.company.name} ${y}년 ${P.quarter}분기 ${m.l}은 ${showV(v, m.t === 'pct' ? 'pct' : 'won')}입니다${p === null ? '' : ` (전년 동기 ${showV(p, m.t === 'pct' ? 'pct' : 'won')} 대비 ${signed(d, m.k === 'operating_margin_pct' ? '%p' : '%')})`}.`,
        evidence: [[`${y}-Q${P.quarter}`, showV(v, m.t === 'pct' ? 'pct' : 'won')], [`${y - 1}-Q${P.quarter}`, showV(p, m.t === 'pct' ? 'pct' : 'won')]],
        formula: [get(y, m.k === 'operating_margin_pct' ? 'revenue' : m.k)?.method || '', ...(m.k === 'operating_margin_pct' ? ['분기 영업이익률 = 분기 영업이익 ÷ 분기 매출액 × 100'] : [])],
        used: usedRows(D, ids), sources: sourcesOf(D, ids), limits: P.quarter === 4 ? ['Q4는 연간 − 3분기 누적이라 연말 결산조정이 포함됩니다.'] : [], goto: 'quarterly',
      };
    }
    // 다른 기업과 비교
    if (P.others.length) {
      const o = P.others[0]; if (!o.has_data) return unknown(q, `${o.name}은(는) 아직 재무 데이터가 수집되지 않았습니다.`);
      const O = await loadOther(o.slug);
      const y = P.years.length ? Math.max(...P.years) : ly;
      const a = val(D, y, m), b = val(O, y, m);
      const ids = auditIds(D, y, m), ido = auditIds(O, y, m);
      S.cmp = o.slug;
      return {
        q, period: String(y), conclusion: `${y}년 ${m.l}: ${D.company.name} ${showV(a, m.t)}, ${O.company.name} ${showV(b, m.t)}.${a !== null && b !== null ? ` 차이 ${m.t === 'pct' ? signed(a - b, '%p') : m.t === 'turn' ? signed(a - b, '회', 2) : signed((a - b) / 1e8, '억원', 0)}.` : ''}`,
        evidence: [[`${D.company.name} ${y}`, showV(a, m.t)], [`${O.company.name} ${y}`, showV(b, m.t)]], formula: [formulaOf(D, y, m)],
        used: [...usedRows(D, ids), ...usedRows(O, ido)], sources: [...sourcesOf(D, ids), ...sourcesOf(O, ido)],
        limits: ['두 회사의 사업 구성(제품군·해외 비중·관계사 구조)이 달라 수익성 차이를 경쟁력 차이로 단정할 수 없습니다.', `재무 범위: ${D.company.name} ${D.fin[0]?.scope || '-'} / ${O.company.name} ${O.fin[0]?.scope || '-'}`], goto: 'compare',
      };
    }
    // 추이 (전 연도)
    if (P.trend && !P.years.length) {
      const vs = Y.map((y) => [y, val(D, y, m)]);
      const ids = Y.flatMap((y) => auditIds(D, y, m));
      const first = vs.find(([, v]) => v !== null), last = [...vs].reverse().find(([, v]) => v !== null);
      return {
        q, period: `${Y[0]}~${ly}`, conclusion: `${D.company.name} ${m.l}: ${vs.map(([y, v]) => `${y} ${showV(v, m.t)}`).join(' → ')}.${first && last && first !== last ? ` ${first[0]}→${last[0]} ${m.t === 'pct' ? signed(last[1] - first[1], '%p') : signed(growth(last[1], first[1]), '%')}.` : ''}`,
        evidence: vs.map(([y, v]) => [String(y), showV(v, m.t)]), formula: [formulaOf(D, ly, m)], used: usedRows(D, ids), sources: sourcesOf(D, ids),
        limits: P.why ? ['원인은 수치만으로 확정하지 않습니다. 사업보고서의 회사 설명(경영진단 및 분석의견)을 확인하세요.'] : [], goto: ['revenue', 'operating_profit', 'net_income', 'cost_of_sales', 'sga'].includes(m.k) ? 'pl' : m.t === 'won' ? 'bs' : 'ratios',
      };
    }
    // 단일 연도 또는 두 연도 비교
    const ys = P.years.length ? P.years : [ly];
    const target = Math.max(...ys), base = ys.length > 1 ? Math.min(...ys) : target - 1;
    if (!Y.includes(target)) return unknown(q, `${target}년 자료가 없습니다 (수집 연도 ${Y[0]}~${ly}).`);
    const growthMode = P.growth || ys.length > 1;
    const a = val(D, target, m), b = val(D, base, m);
    const ids = [...auditIds(D, target, m), ...(growthMode ? auditIds(D, base, m) : [])];
    const d = m.t === 'pct' ? (a === null || b === null ? null : a - b) : growth(a, b);
    const ev = [[`${target} ${m.l}`, showV(a, m.t)]]; if (growthMode) ev.push([`${base} ${m.l}`, showV(b, m.t)], [`${base}→${target}`, m.t === 'pct' ? signed(d, '%p') : signed(d, '%')]);
    return {
      q, period: growthMode ? `${base} → ${target}` : String(target),
      conclusion: growthMode ? `${D.company.name} ${m.l}은 ${base}년 ${showV(b, m.t)}에서 ${target}년 ${showV(a, m.t)}로 ${m.t === 'pct' ? signed(d, '%p') : signed(d, '%')} 변했습니다.` : `${D.company.name} ${target}년 ${m.l}은 ${showV(a, m.t)}입니다.`,
      evidence: ev, formula: [formulaOf(D, target, m), ...(growthMode && m.t !== 'pct' ? ['증가율 = (당기 ÷ 전기 − 1) × 100 · 전기가 0 이하이면 계산 불가'] : [])],
      used: usedRows(D, ids), sources: sourcesOf(D, ids),
      limits: [`${D.fin[0]?.scope || ''} 재무제표 기준 회사 전체 값입니다 (특정 제품·브랜드 매출이 아님).`, ...(P.why ? ['원인은 수치만으로 확정하지 않습니다. 사업보고서의 회사 설명을 확인하세요.'] : [])],
      goto: ['revenue', 'operating_profit', 'net_income', 'cost_of_sales', 'sga'].includes(m.k) ? 'pl' : m.t === 'won' ? 'bs' : 'ratios',
    };
  }

  function cardHTML(a) {
    const sec = (title, body) => (body ? `<h4>${title}</h4>${body}` : '');
    return `<div class="ans${a.unknown ? ' unk' : ''}"><div class="ans-q">${esc(a.q)}</div>
      <div class="tags"><span class="st ${a.unknown ? 'st-warn' : 'st-auto'}">${a.unknown ? '미확인' : 'CSV 계산'}</span><span class="st st-na">기간 ${esc(a.period)}</span></div>
      ${sec(a.unknown ? '답변' : '핵심 결론', `<div class="concl">${esc(a.conclusion)}</div>`)}
      ${sec('근거 수치', a.evidence?.length ? `<table><tbody>${a.evidence.map(([l, v]) => `<tr><td>${esc(l)}</td><td>${esc(v)}</td></tr>`).join('')}</tbody></table>` : '')}
      ${sec('산식', a.formula?.filter(Boolean).length ? `<ul>${a.formula.filter(Boolean).map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : '')}
      ${sec(`사용한 데이터 행 (${a.used?.length || 0})`, a.used?.length ? `<details><summary>행 · 원값 · 상태 보기</summary><table><tbody>${a.used.map((u) => `<tr><td>${esc(u.key)}</td><td>${esc(u.raw)}</td></tr>`).join('')}</tbody></table></details>` : '')}
      ${sec('출처', a.sources?.length ? `<ul>${a.sources.map((s) => `<li>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>` : esc(s.label)}</li>`).join('')}</ul>` : '')}
      ${sec('해석 한계', a.limits?.length ? `<ul>${a.limits.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>` : '')}
      ${a.goto ? `<button class="chip" data-page="${a.goto}" style="margin-top:8px">관련 화면 보기 →</button>` : ''}</div>`;
  }

  function examples() {
    const Y = yearsOf(D); const y = Y[Y.length - 1]; if (!y) return [];
    const other = (INDEX?.companies || []).find((c) => c.slug !== SLUG && c.has_data);
    return [`${y}년 영업이익률은?`, `${y - 1}년 대비 ${y}년 매출 증가율은?`, `${y}년 3분기 영업이익은?`, '부채비율 추이는?', ...(other ? [`${other.name}과 ${y}년 영업이익률 비교`] : []), `${y}년 주가 수익률은?`, `${y}년 수출 비중은?`];
  }
  function paint() {
    const body = $('#panelIn'); if (!body || !body.querySelector('#qaFeed')) return;
    body.querySelector('#qaFeed').innerHTML = FEED.map(cardHTML).join('') || '<p class="foot">질문을 입력하거나 예시를 누르세요. 수집된 CSV로만 계산하며, 없는 자료는 ‘미확인’으로 답합니다.</p>';
  }
  async function ask(q) {
    let a;
    try { a = await answer(q); } catch (e) { console.error(e); a = unknown(q, '계산 중 오류가 발생했습니다. 질문을 바꿔 다시 시도하세요.'); }
    FEED.unshift(a); paint();
  }
  window.openQuery = function () {
    openPanel(`<div class="panel-head"><h2>데이터 질의</h2><button class="x" aria-label="닫기">✕</button></div>
      <p class="foot" style="margin:0">CSV 계산 · 사용 행·산식·출처 표시 · AI 호출 없음</p>
      <form class="qa-form" id="qaForm"><input id="qaInput" placeholder="예: 2025년 영업이익률은?" autocomplete="off"><button>질문</button></form>
      <div class="chips">${examples().map((e) => `<button class="chip" data-ask="${esc(e)}">${esc(e)}</button>`).join('')}</div><div id="qaFeed"></div>`);
    paint();
    $('#qaForm').addEventListener('submit', (e) => { e.preventDefault(); const v = $('#qaInput').value.trim(); if (v) { ask(v); $('#qaInput').value = ''; } });
    $('#panelIn').querySelectorAll('[data-ask]').forEach((b) => b.addEventListener('click', () => ask(b.dataset.ask)));
    $('#qaInput').focus();
  };
  window.__ubdaQuery = { answer, parseQ };
})();
