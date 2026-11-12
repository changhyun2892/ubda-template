/* UBDA 3D 뉴런 포털
 * companies/index.json 하나만 읽어 CORE → 산업 → 카테고리 → 기업 네트워크를 그립니다.
 * 기업 폴더를 추가하고 build_index.py가 돌면 노드가 자동으로 늘어납니다 (이 파일 수정 불필요).
 * 구성: 1) 데이터→노드  2) 장면·효과  3) 노드·연결선·신호  4) 펼치기·선택·카메라  5) 정보 패널·검색  6) 루프
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const MOBILE = matchMedia('(max-width: 760px)').matches;
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v, d = 1) => (v === null || v === undefined || v === '' ? '–' : new Intl.NumberFormat('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(v));

/* ---------- 1) 데이터 → 노드 ---------- */
let IDX;
try { IDX = await (await fetch('companies/index.json', { cache: 'no-cache' })).json(); }
catch (e) { $('#fallback').hidden = false; $('#fallback').querySelector('p').textContent = '기업 목록(companies/index.json)을 읽지 못했습니다.'; throw e; }

const NODES = new Map(); // id → {id,type,label,color,parent,children[],pos,obj,...}
const LINKS = [];        // {a,b,line,...}
function addNode(n) { NODES.set(n.id, { children: [], ...n }); if (n.parent) NODES.get(n.parent).children.push(n.id); return NODES.get(n.id); }
addNode({ id: 'core', type: 'core', label: '경영분석 CORE', color: '#bfe9ff' });
const indIds = Object.keys(IDX.industries);
// 기업이 있는 산업을 앞에 (같은 반구에 모이도록)
indIds.sort((a, b) => IDX.companies.filter((c) => c.industry === b).length - IDX.companies.filter((c) => c.industry === a).length);
indIds.forEach((id) => addNode({ id: `ind:${id}`, type: 'industry', label: IDX.industries[id].name, color: IDX.industries[id].color || '#888', parent: 'core', key: id }));
IDX.companies.forEach((c) => {
  const ind = `ind:${c.industry}`; if (!NODES.has(ind)) addNode({ id: ind, type: 'industry', label: c.industry, color: '#888', parent: 'core', key: c.industry });
  const cats = c.categories?.length ? c.categories : ['기타'];
  cats.forEach((cat) => { const cid = `cat:${c.industry}:${cat}`; if (!NODES.has(cid)) addNode({ id: cid, type: 'category', label: cat, color: NODES.get(ind).color, parent: ind }); });
  // 기업 노드는 1개, 첫 카테고리에 매달고 나머지 카테고리는 연결선만 추가 (기업 정보 중복 저장 안 함)
  addNode({ id: `co:${c.slug}`, type: 'company', label: c.name, color: c.theme_color || NODES.get(ind).color, parent: `cat:${c.industry}:${cats[0]}`, data: c, extraParents: cats.slice(1).map((k) => `cat:${c.industry}:${k}`) });
});

/* 위치: 산업은 구 표면(피보나치 배치), 하위 노드는 부모 바깥 방향으로 고리 모양 */
const R_IND = 64, R_CAT = 22, R_CO = 15;
function basis(dir) { const up = Math.abs(dir.y) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0); const u = new THREE.Vector3().crossVectors(dir, up).normalize(); const v = new THREE.Vector3().crossVectors(dir, u).normalize(); return [u, v]; }
NODES.get('core').pos = new THREE.Vector3();
const inds = [...NODES.values()].filter((n) => n.type === 'industry');
inds.forEach((n, i) => {
  const k = inds.length, y = 1 - ((i + 0.5) / k) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
  n.pos = new THREE.Vector3(Math.cos(th) * r, y * 0.75, Math.sin(th) * r).normalize().multiplyScalar(R_IND);
});
function placeChildren(p, dist, ring) {
  const kids = p.children.map((id) => NODES.get(id)); if (!kids.length) return;
  const dir = p.pos.clone().normalize(); const [u, v] = basis(dir);
  kids.forEach((c, i) => {
    const a = (i / kids.length) * Math.PI * 2 + 0.6; const rr = kids.length === 1 ? 0 : ring;
    c.pos = p.pos.clone().addScaledVector(dir, dist).addScaledVector(u, Math.cos(a) * rr).addScaledVector(v, Math.sin(a) * rr);
  });
}
inds.forEach((n) => { placeChildren(n, R_CAT, 15); n.children.forEach((c) => placeChildren(NODES.get(c), R_CO, 9)); });

/* ---------- 2) 장면·효과 ---------- */
const host = $('#scene');
let renderer;
try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); }
catch (e) { $('#fallback').hidden = false; throw e; }
renderer.setPixelRatio(Math.min(devicePixelRatio, MOBILE ? 1.5 : 2));
renderer.setSize(innerWidth, innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
host.append(renderer.domElement);
const labels = new CSS2DRenderer(); labels.setSize(innerWidth, innerHeight);
Object.assign(labels.domElement.style, { position: 'fixed', inset: '0', pointerEvents: 'none' }); host.append(labels.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#050b16');
scene.fog = new THREE.FogExp2('#050b16', 0.0042);
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 2000);
const HOME = { pos: new THREE.Vector3(0, 38, MOBILE ? 205 : 165), target: new THREE.Vector3(0, 0, 0) };
camera.position.copy(HOME.pos);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.07; controls.minDistance = 18; controls.maxDistance = 420;
controls.autoRotate = !REDUCED; controls.autoRotateSpeed = 0.35;
scene.add(new THREE.AmbientLight('#6f8fb0', 0.55));
const key = new THREE.PointLight('#bfe9ff', 900, 0, 1.6); scene.add(key);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.6, 0.45, 0.2);
composer.addPass(bloom);
composer.addPass(new OutputPass());

// 배경 입자 (별·먼지)
{
  const n = MOBILE ? 600 : 1400, g = new THREE.BufferGeometry(), p = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { const r = 180 + Math.random() * 500, t = Math.random() * Math.PI * 2, f = Math.acos(2 * Math.random() - 1); p.set([r * Math.sin(f) * Math.cos(t), r * Math.cos(f) * 0.6, r * Math.sin(f) * Math.sin(t)], i * 3); }
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: '#4a6f93', size: 1.1, sizeAttenuation: true, transparent: true, opacity: 0.7, depthWrite: false })));
}

/* ---------- 3) 노드·연결선·신호 ---------- */
const SIZE = { core: 7.5, industry: 4.2, category: 2.5, company: 2.1 };
const glowTex = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d'); const g = x.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.25, 'rgba(255,255,255,.45)'); g.addColorStop(1, 'rgba(255,255,255,0)'); x.fillStyle = g; x.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c); })();
const pickables = [];
function makeNode(n) {
  const grp = new THREE.Group(); grp.position.copy(n.pos);
  const col = new THREE.Color(n.color);
  const mat = n.type === 'core'
    ? new THREE.MeshPhysicalMaterial({ color: '#9fdcff', emissive: '#3aa8e0', emissiveIntensity: 0.9, transparent: true, opacity: 0.55, roughness: 0.15, transmission: 0.3, thickness: 2 })
    : new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: { industry: 0.5, category: 0.35, company: 0.45 }[n.type], roughness: 0.35, metalness: 0.1 });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(SIZE[n.type], 40, 28), mat); mesh.userData.id = n.id; grp.add(mesh); pickables.push(mesh);
  if (n.type === 'core') { const inner = new THREE.Mesh(new THREE.SphereGeometry(3, 32, 20), new THREE.MeshBasicMaterial({ color: '#e6f7ff' })); grp.add(inner); n.inner = inner; }
  if (n.type === 'company') { const ring = new THREE.Mesh(new THREE.TorusGeometry(SIZE.company * 1.7, 0.09, 8, 48), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55 })); grp.add(ring); n.ring = ring; }
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: n.type === 'core' ? '#5fc8ff' : col, transparent: true, opacity: { core: 0.75, industry: 0.42, category: 0.25, company: 0.3 }[n.type], depthWrite: false, blending: THREE.AdditiveBlending }));
  halo.scale.setScalar(SIZE[n.type] * { core: 6, industry: 4.2, category: 3.4, company: 3.2 }[n.type]); grp.add(halo); n.halo = halo;
  const div = document.createElement('div'); div.className = `lbl ${n.type}`;
  const cnt = n.type === 'industry' ? IDX.companies.filter((c) => `ind:${c.industry}` === n.id).length : 0;
  div.innerHTML = esc(n.label) + (n.type === 'industry' ? `<small>${cnt ? `${cnt}개 기업` : '준비 중'}</small>` : '');
  const lbl = new CSS2DObject(div); lbl.position.set(0, -SIZE[n.type] - 1.5, 0); grp.add(lbl); n.lbl = lbl; n.div = div;
  grp.visible = false; grp.scale.setScalar(0.001); scene.add(grp); n.obj = grp; n.mesh = mesh;
}
NODES.forEach(makeNode);

function makeLink(a, b, extra = false) {
  const A = NODES.get(a), B = NODES.get(b);
  const g = new THREE.BufferGeometry().setFromPoints([A.pos, B.pos]);
  const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: new THREE.Color(B.type === 'company' ? B.color : A.type === 'core' ? B.color : A.color), transparent: true, opacity: extra ? 0.35 : 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
  line.visible = false; scene.add(line);
  const L = { a, b, line, extra, t: Math.random() }; LINKS.push(L); return L;
}
NODES.forEach((n) => { if (n.parent) makeLink(n.parent, n.id); (n.extraParents || []).forEach((p) => makeLink(p, n.id, true)); });

// 신경 신호: 연결선을 따라 부모 → 자식으로 흐르는 빛 알갱이
const signalGeo = new THREE.SphereGeometry(0.45, 10, 8);
LINKS.forEach((L) => {
  const m = new THREE.Mesh(signalGeo, new THREE.MeshBasicMaterial({ color: L.line.material.color.clone().lerp(new THREE.Color('#ffffff'), 0.5), transparent: true, opacity: 0.95 }));
  m.visible = false; scene.add(m); L.signal = m; L.speed = 0.25 + Math.random() * 0.25;
});

/* ---------- 4) 펼치기·선택·카메라 ---------- */
const expanded = new Set(['core']);
let selected = null;
const isVisible = (n) => n.id === 'core' || expanded.has(n.parent) || (n.extraParents || []).some((p) => expanded.has(p));
function refreshVisibility() {
  NODES.forEach((n) => { const v = isVisible(n); if (v && !n.obj.visible) { n.obj.visible = true; n.grow = 0; } if (!v) { n.obj.visible = false; n.obj.scale.setScalar(0.001); } });
  LINKS.forEach((L) => { const v = NODES.get(L.a).obj.visible && NODES.get(L.b).obj.visible && expanded.has(L.a); L.line.visible = v; L.signal.visible = v && !REDUCED; });
  // 선택한 줄기 강조, 나머지 이름표는 흐리게
  const path = new Set(); let p = selected && NODES.get(selected); while (p) { path.add(p.id); p = p.parent && NODES.get(p.parent); }
  NODES.forEach((n) => n.div.classList.toggle('dim', !!selected && !path.has(n.id) && !(selected && NODES.get(selected).children.includes(n.id))));
}
function collapse(id) { NODES.get(id).children.forEach((c) => { expanded.delete(c); collapse(c); }); }
function toggle(id) {
  const n = NODES.get(id);
  if (n.type === 'company') return;
  if (expanded.has(id) && id !== 'core') { expanded.delete(id); collapse(id); }
  else {
    if (n.type === 'industry') inds.forEach((o) => { if (o.id !== id) { expanded.delete(o.id); collapse(o.id); } }); // 한 번에 한 산업만 펼침 (화면 정리)
    expanded.add(id);
  }
  refreshVisibility();
}
let fly = null;
function flyTo(id, dist) {
  const n = NODES.get(id);
  const target = n.pos.clone();
  let dir;
  if (n.id === 'core') dir = HOME.pos.clone().normalize();
  else {
    const out = n.pos.clone().normalize(); const up = new THREE.Vector3(0, 1, 0);
    const side = new THREE.Vector3().crossVectors(out, up).normalize();
    dir = out.multiplyScalar(n.type === 'industry' ? 0.9 : 0.55).addScaledVector(side, n.type === 'industry' ? 0.25 : 0.75).addScaledVector(up, 0.35).normalize();
  }
  const d = dist ?? { core: 165, industry: 70, category: 48, company: 30 }[n.type] * (MOBILE ? 1.5 : 1);
  const pos = n.id === 'core' ? HOME.pos.clone() : target.clone().addScaledVector(dir, d);
  fly = { start: performance.now(), dur: REDUCED ? 0.01 : 1.1, p0: camera.position.clone(), p1: pos, t0: controls.target.clone(), t1: n.id === 'core' ? HOME.target.clone() : target };
  controls.autoRotate = false;
}
function select(id, { expand = true, move = true } = {}) {
  const n = NODES.get(id); if (!n) return;
  // 경로상의 조상을 모두 펼침 (검색으로 바로 이동할 때)
  const chain = []; let p = n; while (p.parent) { chain.unshift(p.parent); p = NODES.get(p.parent); }
  chain.forEach((a) => { if (!expanded.has(a)) { if (NODES.get(a).type === 'industry') inds.forEach((o) => { if (o.id !== a) { expanded.delete(o.id); collapse(o.id); } }); expanded.add(a); } });
  if (expand && n.type !== 'company' && !expanded.has(id)) { if (n.type === 'industry') inds.forEach((o) => { if (o.id !== id) { expanded.delete(o.id); collapse(o.id); } }); expanded.add(id); }
  selected = id === 'core' ? null : id;
  refreshVisibility();
  if (move) flyTo(id);
  showInfo(n);
  $('#hint').style.opacity = 0;
}
function reset() { expanded.clear(); expanded.add('core'); selected = null; refreshVisibility(); flyTo('core'); $('#info').hidden = true; setOffset(); controls.autoRotate = !REDUCED; }

// 클릭 판정 (드래그와 구분)
const ray = new THREE.Raycaster(); const ptr = new THREE.Vector2(); let down = null; let hoverId = null;
renderer.domElement.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY }; controls.autoRotate = false; });
function pick(e) {
  ptr.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ptr, camera);
  const hit = ray.intersectObjects(pickables.filter((m) => m.parent.visible), false)[0];
  return hit?.object.userData.id || null;
}
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) { down = null; return; }
  down = null; const id = pick(e);
  if (!id) return;
  const n = NODES.get(id);
  if (n.type === 'company' || n.type === 'core') select(id);
  else if (expanded.has(id) && selected === id) { toggle(id); showInfo(n); } // 이미 펼친 노드를 다시 누르면 접기
  else select(id);
});
renderer.domElement.addEventListener('pointermove', (e) => {
  if (down) return; const id = pick(e);
  if (id !== hoverId) { if (hoverId) NODES.get(hoverId).hover = false; hoverId = id; if (id) NODES.get(id).hover = true; renderer.domElement.style.cursor = id ? 'pointer' : 'grab'; }
});

/* ---------- 5) 정보 패널·검색 ---------- */
const coOf = (n) => n.data;
function companyCard(c) {
  const k = c.kpis || {}; const v = c.verification || {};
  return c.has_data ? `<div class="kpi4">
      <div><span>${c.latest_year} 매출액</span><b>${nf(k.revenue / 1e8, 0)}<i>억원</i></b></div>
      <div><span>영업이익률</span><b>${nf(k.operating_margin_pct)}<i>%</i></b></div>
      <div><span>매출 증가율</span><b>${k.revenue_growth_pct === '' || k.revenue_growth_pct == null ? '–' : (k.revenue_growth_pct > 0 ? '+' : '') + nf(k.revenue_growth_pct)}<i>%</i></b></div>
      <div><span>부채비율</span><b>${nf(k.debt_ratio_pct)}<i>%</i></b></div></div>
    <div class="badges"><span>DART ${c.latest_year}년까지</span><span>원문 대조 ${v['원문 대조 일치'] ?? 0} · 자동 ${v['자동 수집 · 원문 대조 전'] ?? 0}</span>${v['불일치'] ? `<span class="warn">불일치 ${v['불일치']}</span>` : ''}<span>산업 KPI ${c.industry_kpis_found ?? 0}/${c.industry_kpis_total ?? 0}</span></div>`
    : '<div class="badges"><span class="warn">데이터 수집 전</span></div>';
}
function setOffset() {
  // 패널이 장면을 가리지 않게: 데스크톱은 오른쪽 패널만큼 왼쪽으로, 모바일은 아래 패널만큼 위로 장면을 옮김
  const box = $('#info');
  if (box.hidden) { camera.clearViewOffset(); return; }
  if (MOBILE) camera.setViewOffset(innerWidth, innerHeight, 0, Math.round(Math.min(box.offsetHeight, innerHeight * 0.52) / 2 + 10), innerWidth, innerHeight);
  else camera.setViewOffset(innerWidth, innerHeight, 175, 0, innerWidth, innerHeight);
}
function showInfo(n) {
  const box = $('#info'); box.hidden = n.type === 'core'; setOffset();
  if (n.type === 'core') return;
  let html = '';
  if (n.type === 'company') {
    const c = coOf(n);
    html = `<div class="kicker">${esc(IDX.industries[c.industry]?.name || c.industry)} · ${esc((c.categories || []).join(', '))}</div><h2>${esc(c.name)}</h2><p class="sub">${esc(c.stock_code)} · 연결 재무 기준 · 갱신 ${esc(c.updated_at || '-')}</p>
      ${companyCard(c)}<div class="btns"><a class="btn" href="${esc(c.dashboard_path)}">대시보드 열기</a><a class="btn ghost" href="${esc(c.dashboard_path)}#screen">메인 스크린</a></div>
      ${c.competitors?.length ? `<p class="note" style="margin-top:10px">비교 기업: ${esc(c.competitors.join(', '))}</p>` : ''}`;
  } else {
    const cos = n.type === 'industry' ? IDX.companies.filter((c) => `ind:${c.industry}` === n.id) : IDX.companies.filter((c) => (c.categories?.length ? c.categories : ['기타']).some((k) => `cat:${c.industry}:${k}` === n.id));
    const cats = n.type === 'industry' ? n.children.map((id) => NODES.get(id)) : [];
    html = `<div class="kicker">${n.type === 'industry' ? '산업' : `카테고리 · ${esc(NODES.get(n.parent).label)}`}</div><h2>${esc(n.label)}</h2><p class="sub">${cos.length ? `기업 ${cos.length}개${cats.length ? ` · 카테고리 ${cats.length}개` : ''}` : '아직 등록된 기업이 없습니다 (준비 중)'}</p>
      ${cats.length ? `<ul class="list">${cats.map((k) => `<li>${esc(k.label)} <button data-go="${esc(k.id)}">펼치기</button></li>`).join('')}</ul>` : ''}
      ${cos.length ? `<ul class="list">${cos.map((c) => `<li><span>${esc(c.name)} <small style="color:var(--muted)">${c.has_data ? `${nf(c.kpis?.revenue / 1e8, 0)}억원` : '수집 전'}</small></span><button data-go="co:${esc(c.slug)}">보기</button></li>`).join('')}</ul>` : '<p class="note">"OOO 경영 대시보드 만들어줘"로 기업을 추가하면 이곳에 자동으로 나타납니다.</p>'}
      ${n.type === 'industry' && expanded.has(n.id) ? '<p class="note">구체를 다시 누르면 접힙니다.</p>' : ''}`;
  }
  box.innerHTML = `<button class="x" aria-label="닫기">✕</button>${html}`;
  box.querySelector('.x').onclick = () => { box.hidden = true; setOffset(); };
  box.querySelectorAll('[data-go]').forEach((b) => (b.onclick = () => select(b.dataset.go)));
  setOffset();
}

// 검색: 기업·카테고리·산업 이름, 종목코드, 영문명
const q = $('#q'), sugg = $('#sugg'); let sel = -1, items = [];
function search(t) {
  t = t.trim().toLowerCase(); if (!t) return [];
  return [...NODES.values()].filter((n) => n.type !== 'core').map((n) => ({ n, s: [n.label, n.data?.stock_code, n.data?.name_en].filter(Boolean).join(' ').toLowerCase() }))
    .filter((x) => x.s.includes(t)).sort((a, b) => ({ company: 0, category: 1, industry: 2 }[a.n.type] - { company: 0, category: 1, industry: 2 }[b.n.type])).slice(0, 8).map((x) => x.n);
}
function paintSugg() {
  sugg.hidden = !items.length;
  sugg.innerHTML = items.map((n, i) => `<li role="option" data-i="${i}" aria-selected="${i === sel}">${esc(n.label)}<small>${{ company: '기업', category: `카테고리 · ${esc(NODES.get(n.parent).label)}`, industry: '산업' }[n.type]}</small></li>`).join('');
  sugg.querySelectorAll('li').forEach((li) => (li.onmousedown = (e) => { e.preventDefault(); go(+li.dataset.i); }));
}
function go(i) { const n = items[i]; if (!n) return; select(n.id); q.value = n.label; items = []; paintSugg(); q.blur(); }
q.addEventListener('input', () => { items = search(q.value); sel = items.length ? 0 : -1; paintSugg(); });
q.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown') { sel = Math.min(items.length - 1, sel + 1); paintSugg(); e.preventDefault(); }
  else if (e.key === 'ArrowUp') { sel = Math.max(0, sel - 1); paintSugg(); e.preventDefault(); }
  else if (e.key === 'Enter') { go(sel < 0 ? 0 : sel); }
  else if (e.key === 'Escape') { items = []; paintSugg(); }
});
q.addEventListener('blur', () => setTimeout(() => { items = []; paintSugg(); }, 120));
$('#resetBtn').onclick = reset;
addEventListener('keydown', (e) => { if (e.key === 'Escape' && document.activeElement !== q) reset(); });
$('#legend').innerHTML = inds.map((n) => `<span data-go="${esc(n.id)}"><i style="background:${esc(n.color)};box-shadow:0 0 8px ${esc(n.color)}"></i>${esc(n.label)} <small>(${IDX.companies.filter((c) => `ind:${c.industry}` === n.id).length})</small></span>`).join('');
$('#legend').querySelectorAll('[data-go]').forEach((s) => (s.onclick = () => select(s.dataset.go)));

/* ---------- 6) 루프 ---------- */
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; setOffset(); camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); labels.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight); });
const clock = new THREE.Clock();
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
function loop() {
  const dt = Math.min(clock.getDelta(), 0.05), time = clock.elapsedTime;
  if (fly) { fly.t = (performance.now() - fly.start) / 1000 / fly.dur; const k = ease(Math.min(1, fly.t)); camera.position.lerpVectors(fly.p0, fly.p1, k); controls.target.lerpVectors(fly.t0, fly.t1, k); if (fly.t >= 1) fly = null; }
  NODES.forEach((n) => {
    if (!n.obj.visible) return;
    if (n.grow !== undefined && n.grow < 1) { n.grow = Math.min(1, n.grow + dt * (REDUCED ? 99 : 2.2)); n.obj.scale.setScalar(ease(n.grow)); }
    const base = n.hover || n.id === selected ? 1.25 : 1;
    n.mesh.scale.lerp(new THREE.Vector3(base, base, base), 0.15);
    if (n.type === 'core' && !REDUCED) { const s = 1 + Math.sin(time * 1.6) * 0.06; n.inner.scale.setScalar(s); n.halo.material.opacity = 0.6 + Math.sin(time * 1.6) * 0.15; }
    if (n.ring && !REDUCED) { n.ring.rotation.x = time * 0.8; n.ring.rotation.y = time * 0.5; }
  });
  LINKS.forEach((L) => {
    if (!L.signal.visible) return;
    L.t = (L.t + dt * L.speed) % 1; const A = NODES.get(L.a).pos, B = NODES.get(L.b).pos;
    L.signal.position.lerpVectors(A, B, L.t); L.signal.material.opacity = Math.sin(L.t * Math.PI);
  });
  key.position.copy(camera.position);
  controls.update();
  composer.render();
  labels.render(scene, camera);
  requestAnimationFrame(loop);
}
refreshVisibility();
loop();
setTimeout(() => ($('#hint').style.opacity = 0), 9000);
// 주소에 #ottogi 같은 기업이 있으면 바로 이동
const h = decodeURIComponent(location.hash.slice(1)); if (h && NODES.has(`co:${h}`)) select(`co:${h}`);
// 화면 좌표 (테스트·접근성 도구용): 노드가 화면 어디에 그려지는지
const screenOf = (id) => { const v = NODES.get(id).pos.clone().project(camera); return { x: (v.x + 1) / 2 * innerWidth, y: (1 - v.y) / 2 * innerHeight, visible: NODES.get(id).obj.visible }; };
window.__portal = { get flying() { return !!fly; }, select, reset, toggle, screenOf, pickAt: (x, y) => pick({ clientX: x, clientY: y }), nodes: NODES, expanded, get selected() { return selected; } };
