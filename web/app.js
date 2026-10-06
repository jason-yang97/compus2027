/* 校招信息汇总 - 纯前端应用（零依赖） */
'use strict';

/* ---------- 配置：分类页签（客户端过滤预设） ---------- */
const TABS = [
  { id: 'all',    name: '校招汇总',     match: () => true },
  { id: 'q27',    name: '27秋招',       match: r => r.yrs.includes(2027) && r.tags.includes('秋招') },
  { id: 's27',    name: '27实习汇总',   match: r => r.yrs.includes(2027) && r.tags.includes('实习') },
  { id: 'q26',    name: '26秋招+补录',  match: r => r.yrs.includes(2026) && (r.tags.includes('秋招') || r.tags.includes('补录')) },
  { id: 'y2425',  name: '24-25可投',    match: r => r.yrs.some(y => y === 2024 || y === 2025) },
  { id: 'freeq',  name: '免笔试秋招',   match: r => r.free === 1 && r.tags.includes('秋招') },
  { id: 'free',   name: '免笔试汇总',   match: r => r.free === 1 },
  { id: 'yq',     name: '央国企',       match: r => r.ent.includes('央国企') },
  { id: 'wq',     name: '外企',         match: r => r.ent.some(e => /外企|合资/.test(e)) },
  { id: 'hl',     name: '互联网',       match: r => r.ind.some(i => i.includes('互联网')) },
  { id: 'jr',     name: '银行金融类',   match: r => r.ent.includes('银行') || r.ind.some(i => /金融|银行|证券|基金|保险|信托|投资|期货|租赁/.test(i)) },
];

const FILTER_KEYS = [
  { key: 'src',  name: '来源',     searchable: true },
  { key: 'ent',  name: '企业类型', searchable: false },
  { key: 'ind',  name: '行业类别', searchable: true },
  { key: 'city', name: '工作地点', searchable: true },
  { key: 'yrs',  name: '招聘届次', searchable: true },
  { key: 'tags', name: '批次类型', searchable: false },
  { key: 'test', name: '是否笔试', searchable: false, special: 'test' },
  { key: 'edu',  name: '学历要求', searchable: false },
  { key: 'dl',   name: '截止日期', searchable: false, special: 'dl' },
  { key: 'start', name: '开始时间', searchable: false, special: 'start' },
];

const TEST_OPTIONS = [
  { v: 'free',  name: '有免笔试机会' },
  { v: 'test',  name: '明确有笔试' },
  { v: 'unk',   name: '未明确' },
];
const DL_OPTIONS = [
  { v: 'w1',      name: '一周内截止' },
  { v: 'm1',      name: '一月内截止' },
  { v: 'm3',      name: '三月内截止' },
  { v: 'later',   name: '三月以上' },
  { v: 'none',    name: '招满为止/未标注' },
  { v: 'expired', name: '已过期' },
];

const PAGE_SIZE = 50;
const BATCH_BADGE = { '秋招': 'b-qiu', '春招': 'b-chun', '实习': 'b-sx', '寒假实习': 'b-hj', '暑假实习': 'b-hj', '补录': 'b-bl', '提前批': 'b-tq', '未标注': 'b-unk' };

/* 列宽（Excel 式拖拽调整，localStorage 持久化） */
const COL_DEFAULTS = [170, 380, 180, 110, 110, 110, 110, 110, 190, 150];
const COL_STORE_KEY = 'jobboard-colw-v3';

/* ---------- 全局状态 ---------- */
let DATA = null;
let state = {
  tab: 'all',
  q: '',
  major: '',
  sel: { src: new Set(), ent: new Set(), ind: new Set(), city: new Set(), yrs: new Set(), tags: new Set(), test: new Set(), edu: new Set(), dl: new Set(), start: new Set() },
  range: { dlFrom: '', dlTo: '', stFrom: '', stTo: '' },
  sort: 'upd',
  full: false,
  page: 1,
};
const expanded = new Set();
let suppressRowClick = false;
let viewList = [];   // 当前筛选+排序后的视图列表，展开详情按此定位
let FACETS = {};   // key -> [{v, n}]
let tabCounts = {};

/* ---------- 工具 ---------- */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

function dlBucket(r) {
  if (!r.dl) return 'none';
  const d = new Date(r.dl + 'T00:00:00');
  const now = new Date(); now.setHours(0, 0, 0, 0);
  const days = (d - now) / 86400000;
  if (days < 0) return 'expired';
  if (days <= 7) return 'w1';
  if (days <= 31) return 'm1';
  if (days <= 93) return 'm3';
  return 'later';
}
function testBucket(r) { return r.free ? 'free' : (r.test ? 'test' : 'unk'); }

function dlClass(r) {
  const b = dlBucket(r);
  if (b === 'expired') return 'dl-exp';
  if (b === 'w1') return 'dl-lv3';
  if (b === 'm1') return 'dl-lv2';
  if (b === 'none') return 'dl-none';
  return 'dl-ok';
}
function dlText(r) {
  if (r.dl) return r.dlRaw !== r.dl ? r.dlRaw : r.dl;
  return r.dlRaw || '—';
}
function yrsText(r) {
  return r.yrs.length ? r.yrs.map(y => (typeof y === 'number' ? y + '届' : y)).join(' / ') : '—';
}

/* ---------- 构建筛选刻面 ---------- */
function buildFacets(records) {
  FACETS = {};
  for (const f of FILTER_KEYS) {
    if (f.special) continue;
    const counter = new Map();
    for (const r of records) {
      const vals = Array.isArray(r[f.key]) ? r[f.key] : [r[f.key]];
      for (const v of vals) counter.set(String(v), (counter.get(String(v)) || 0) + 1);
    }
    let items = [...counter.entries()].map(([v, n]) => ({ v, n }));
    if (f.key === 'yrs') {
      // 年份按时间先后在前，特殊届次（海外/往届/不限）按出现次数在后
      items.sort((a, b) => {
        const an = /^\d{4}$/.test(a.v), bn = /^\d{4}$/.test(b.v);
        if (an && bn) return a.v < b.v ? -1 : 1;
        if (an !== bn) return an ? -1 : 1;
        return b.n - a.n;
      });
    } else {
      items.sort((a, b) => b.n - a.n);
    }
    FACETS[f.key] = items;
  }
}

/* ---------- 匹配 ---------- */
function matchTab(r) { return TABS.find(t => t.id === state.tab).match(r); }

function inRange(dateStr, from, to) {
  if (from || to) {
    if (!dateStr) return false;
    if (from && dateStr < from) return false;
    if (to && dateStr > to) return false;
  }
  return true;
}

/* 开始时间范围：未标注开始时间的记录不排除（排序时放到最后） */
function matchStartRange(r) {
  const f = state.range.stFrom, t = state.range.stTo;
  if (!f && !t) return true;
  if (!r.start) return true;
  if (f && r.start < f) return false;
  if (t && r.start > t) return false;
  return true;
}

function matchFilters(r) {
  const s = state.sel;
  if (s.src.size && !s.src.has(r.src)) return false;
  if (s.ent.size && !r.ent.some(v => s.ent.has(v))) return false;
  if (s.ind.size && !r.ind.some(v => s.ind.has(v))) return false;
  if (s.city.size && !r.city.some(v => s.city.has(v))) return false;
  if (s.yrs.size && !r.yrs.some(y => s.yrs.has(String(y)))) return false;
  if (s.tags.size && !r.tags.some(t => s.tags.has(t))) return false;
  if (s.edu.size && !r.edu.some(v => s.edu.has(v))) return false;
  if (s.test.size && !s.test.has(testBucket(r))) return false;
  if (s.dl.size && !s.dl.has(dlBucket(r))) return false;
  if (!inRange(r.dl, state.range.dlFrom, state.range.dlTo)) return false;
  if (!matchStartRange(r)) return false;
  if (state.major) {
    const hay = `${r.major} ${r.r} ${r.note}`.toLowerCase();
    for (const kw of state.major.toLowerCase().split(/\s+/)) {
      if (kw && !hay.includes(kw)) return false;
    }
  }
  if (state.q) {
    const hay = `${r.c} ${r.r} ${r.note} ${r.major} ${r.ind.join(' ')} ${r.ent.join(' ')} ${r.edu.join(' ')} ${r.batch} ${r.written} ${r.src}`.toLowerCase();
    for (const kw of state.q.toLowerCase().split(/\s+/)) {
      if (kw && !hay.includes(kw)) return false;
    }
  }
  return true;
}

function filteredRecords() {
  const out = [];
  for (const r of DATA.records) {
    if (matchTab(r) && matchFilters(r)) out.push(r);
  }
  return out;
}

/* ---------- 排序 ---------- */
function sortRecords(list) {
  if (state.sort === 'dl') {
    list.sort((a, b) => (a.dl || '9999') < (b.dl || '9999') ? -1 : (a.dl || '9999') > (b.dl || '9999') ? 1 : 0);
  } else if (state.sort === 'c') {
    list.sort((a, b) => a.c.localeCompare(b.c, 'zh-Hans-CN'));
  } else {
    list.sort((a, b) => (a.upd || '') < (b.upd || '') ? 1 : (a.upd || '') > (b.upd || '') ? -1 : 0);
  }
  // 开始时间范围筛选时：有开始时间的按日期升序在前，未标注的排最后
  if (state.range.stFrom || state.range.stTo) {
    list.sort((a, b) => {
      const av = a.start ? 0 : 1, bv = b.start ? 0 : 1;
      if (av !== bv) return av - bv;
      if (!av && a.start !== b.start) return a.start < b.start ? -1 : 1;
      return 0;
    });
  }
}

/* ---------- 渲染：页签 ---------- */
function renderTabs() {
  $('tabs').innerHTML = TABS.map(t => {
    const n = tabCounts[t.id] ?? 0;
    return `<button class="tab${t.id === state.tab ? ' active' : ''}" data-tab="${t.id}">${t.name}<span class="n">${n >= 10000 ? (n / 10000).toFixed(1) + 'w' : n}</span></button>`;
  }).join('');
}

function computeTabCounts() {
  tabCounts = {};
  for (const t of TABS) {
    let n = 0;
    for (const r of DATA.records) if (t.match(r)) n++;
    tabCounts[t.id] = n;
  }
}

/* ---------- 渲染：筛选器 ---------- */
function renderFilters() {
  $('filters').innerHTML = `
    <div class="text-filter">
      <span class="tf-label">专业</span>
      <input id="major-input" type="search" placeholder="专业关键词（专业要求/岗位/备注 包含）" value="${esc(state.major)}">
    </div>` +
    FILTER_KEYS.map(f => {
      const sel = state.sel[f.key];
      const cnt = sel.size ? ` <span class="cnt">(${sel.size})</span>` : '';
      const search = f.searchable ? '<input class="dd-search" placeholder="搜索…" data-dsearch="' + f.key + '">' : '';
      const listHtml = f.special === 'start' ? '' : `<div class="dd-list" data-dlist="${f.key}"></div>`;
      return `<div class="dd${sel.size ? ' on' : ''}" data-dd="${f.key}">
        <button class="dd-btn" type="button">${f.name}${cnt}<span class="caret">▼</span></button>
        <div class="dd-panel">${search}${listHtml}${panelExtra(f)}</div>
      </div>`;
    }).join('');
  for (const f of FILTER_KEYS) if (f.special !== 'start') renderDropdownList(f.key);
  $('major-input').addEventListener('input', e => { state.major = e.target.value.trim(); refresh(); });
}

function panelExtra(f) {
  if (f.special === 'dl') {
    return `<div class="dd-dates">
      <label>从 <input type="date" data-range="dlFrom" value="${state.range.dlFrom}"></label>
      <label>到 <input type="date" data-range="dlTo" value="${state.range.dlTo}"></label>
    </div>
    <div class="dd-note">可自定义截止日期范围，与上方快捷范围叠加</div>`;
  }
  if (f.special === 'start') {
    return `<div class="dd-dates">
      <label>从 <input type="date" data-range="stFrom" value="${state.range.stFrom}"></label>
      <label>到 <input type="date" data-range="stTo" value="${state.range.stTo}"></label>
    </div>
    <div class="dd-note">按记录「开始时间」筛选；未标注开始时间的记录不会被排除，会排在结果最后</div>`;
  }
  return '';
}

function renderDropdownList(key, kw = '') {
  const listEl = document.querySelector(`[data-dlist="${key}"]`);
  if (!listEl) return;
  const sel = state.sel[key];
  let items;
  if (key === 'test') {
    items = TEST_OPTIONS.map(o => ({ v: o.v, name: o.name, n: tabCountBy(testBucket, o.v) }));
  } else if (key === 'dl') {
    items = DL_OPTIONS.map(o => ({ v: o.v, name: o.name, n: tabCountBy(dlBucket, o.v) }));
  } else {
    items = (FACETS[key] || []).map(o => {
      const isYear = /^\d{4}$/.test(o.v);
      return { v: o.v, name: key === 'yrs' && isYear ? o.v + '届' : o.v, n: o.n };
    });
  }
  if (kw) items = items.filter(i => i.name.toLowerCase().includes(kw.toLowerCase()));
  const top = items.slice(0, 400);
  listEl.innerHTML = top.map(i => `
    <label class="dd-item"><input type="checkbox" data-dsel="${key}" value="${esc(i.v)}" ${sel.has(i.v) ? 'checked' : ''}>
    <span class="label">${esc(i.name)}</span><span class="n">${i.n}</span></label>`).join('')
    || '<div class="dd-item"><span class="label">无匹配项</span></div>';
  if (!FILTER_KEYS.find(x => x.key === key).searchable && items.length > 400) {
    listEl.insertAdjacentHTML('beforeend', '<div class="dd-item"><span class="label">…仅显示前 400 项，请用搜索</span></div>');
  }
}
function tabCountBy(fn, v) {
  let n = 0;
  for (const r of DATA.records) if (matchTab(r) && fn(r) === v) n++;
  return n;
}

/* ---------- 渲染：表格 ---------- */
function badgeFor(tag) { return `<span class="badge ${BATCH_BADGE[tag] || 'b-unk'}">${esc(tag)}</span>`; }

function renderTable(list) {
  const start = (state.page - 1) * PAGE_SIZE;
  const pageRows = list.slice(start, start + PAGE_SIZE);
  $('tbody').innerHTML = pageRows.map((r, i) => {
    const idx = start + i;
    const exp = expanded.has(idx);
    const badges = r.tags.map(badgeFor).join('');
    const testBadge = r.free ? '<span class="badge b-free">免笔试机会</span>'
      : r.test ? '<span class="badge b-test">有笔试</span>' : '<span class="badge b-na">未明确</span>';
    const applyBtn = r.url ? `<a class="link-btn link-apply" href="${esc(r.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">投递 ↗</a>` : '';
    const annBtn = r.ann ? `<a class="link-btn link-ann" href="${esc(r.ann)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">公告</a>` : '';
    const main = `<tr class="row${exp ? ' expanded' : ''}" data-idx="${idx}">
      <td class="td-c"><div class="cname">${esc(r.c)}</div></td>
      <td class="td-r"><div class="role">${esc(r.r) || '—'}</div></td>
      <td class="td-loc"><div class="loc">${esc(r.city.join(' / ')) || '—'}</div></td>
      <td class="td-yrs">${esc(yrsText(r))}</td>
      <td class="td-batch">${badges || '—'}</td>
      <td class="td-dl ${dlClass(r)}">${esc(dlText(r))}</td>
      <td class="td-start">${esc(r.start || '—')}</td>
      <td class="td-test">${testBadge}</td>
      <td class="td-ent"><span class="e">${esc(r.ent.join(' · ')) || '—'}</span><span class="e">${esc(r.ind.join(' · ')) || '—'}</span></td>
      <td class="td-link">${applyBtn}${annBtn}</td>
    </tr>`;
    if (!exp) return main;
    return main + detailHtml(idx);
  }).join('');
  $('empty').hidden = pageRows.length > 0;
}

function detailHtml(idx) {
  const r = viewList[idx];
  return `<tr class="detail"><td colspan="10"><dl>
    <dt>学历要求</dt><dd>${esc(r.edu.join(' / ')) || '—'}</dd>
    <dt>专业要求</dt><dd>${esc(r.major) || '（表内未填写具体专业，可参考岗位描述）'}</dd>
    <dt>备注</dt><dd>${esc(r.note) || '—'}</dd>
    <dt>原始批次</dt><dd>${esc(r.batch) || '—'}｜笔试说明：${esc(r.written) || '—'}</dd>
    <dt>时间</dt><dd>开始 ${esc(r.start || '—')}｜更新 ${esc(r.upd || '—')}｜截止 ${esc(r.dlRaw || '—')}</dd>
    <dt>来源</dt><dd>${esc(r.src)}</dd>
  </dl></td></tr>`;
}

function renderPager(total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
  $('pager').innerHTML = pages <= 1 ? '' :
    `<button id="pg-prev" ${state.page <= 1 ? 'disabled' : ''}>上一页</button>
     <span>第 ${state.page} / ${pages} 页 · 共 ${total.toLocaleString()} 条</span>
     <button id="pg-next" ${state.page >= pages ? 'disabled' : ''}>下一页</button>`;
  const prev = $('pg-prev'), next = $('pg-next');
  if (prev) prev.onclick = () => { state.page--; refresh(false); };
  if (next) next.onclick = () => { state.page++; refresh(false); };
}

function renderMeta(total) {
  $('result-meta').innerHTML = `当前页签命中 <b>${total.toLocaleString()}</b> 条（全部数据 ${DATA.total.toLocaleString()} 条，更新于 ${DATA.updated}）` +
    (state.q ? `｜关键词「<b>${esc(state.q)}</b>」` : '') +
    (state.major ? `｜专业「<b>${esc(state.major)}</b>」` : '');
}

function refresh(resetPage = true) {
  if (resetPage) {
    state.page = 1;
    expanded.clear();   // 筛选/页签/排序变化后，展开位置可能指向别的记录，全部收起
  }
  const list = filteredRecords();
  sortRecords(list);
  viewList = list;
  renderMeta(list.length);
  renderTable(list);
  renderPager(list.length);
  const hasFilter = state.q || state.major ||
    Object.values(state.sel).some(s => s.size) ||
    Object.values(state.range).some(v => v);
  $('reset').hidden = !hasFilter;
  $('search-clear').hidden = !state.q;
  try { history.replaceState(null, '', '#' + state.tab); } catch (_) { /* file:// 下忽略 */ }
}

/* ---------- Excel 式列宽拖拽 ---------- */
function initColResize() {
  const ths = document.querySelectorAll('#table thead th');
  const saved = JSON.parse(localStorage.getItem(COL_STORE_KEY) || 'null');
  ths.forEach((th, i) => {
    th.style.width = (saved?.[i] || COL_DEFAULTS[i]) + 'px';
    const rz = document.createElement('span');
    rz.className = 'rz';
    rz.title = '拖动调整列宽';
    th.appendChild(rz);
    rz.addEventListener('mousedown', e => {
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, startW = th.offsetWidth;
      document.body.classList.add('col-resizing');
      const move = ev => {
        const w = Math.max(60, Math.min(900, startW + ev.clientX - startX));
        th.style.width = w + 'px';
      };
      const up = () => {
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        document.body.classList.remove('col-resizing');
        localStorage.setItem(COL_STORE_KEY, JSON.stringify(
          [...document.querySelectorAll('#table thead th')].map(t => parseInt(t.style.width) || 0)));
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
    });
  });
}

/* ---------- 任意行边缘拖拽：竖线调列宽、横线调行高（Excel 式） ---------- */
function initEdgeResize() {
  const table = $('table');
  const thAll = () => table.querySelectorAll('thead th');
  let drag = null;
  let hoverMark = null;   // 当前高亮的感应线 {cell, cls}

  const setEdgeMark = (cell, cls) => {
    if (hoverMark) { hoverMark.cell.classList.remove('edge-col', 'edge-row'); hoverMark = null; }
    if (cell && cls) { cell.classList.add(cls); hoverMark = { cell, cls }; }
  };

  // 判断事件位置是否贴近单元格右缘/下缘
  const nearEdges = e => {
    const cell = e.target.closest('td, th');
    if (!cell || e.target.closest('a, button, input, select, .rz')) return null;
    const rect = cell.getBoundingClientRect();
    const colEdge = rect.width - (e.clientX - rect.left) <= 12;
    const rowEdge = cell.tagName === 'TD' && rect.height - (e.clientY - rect.top) <= 10;
    if (!colEdge && !rowEdge) return null;
    return { cell, colEdge, rowEdge };
  };

  table.addEventListener('mousedown', e => {
    const hit = nearEdges(e);
    if (!hit) return;
    e.preventDefault();
    drag = { hit, startX: e.clientX, startY: e.clientY, moved: false };
    if (hit.colEdge) {
      drag.th = thAll()[hit.cell.cellIndex];
      drag.startW = drag.th.offsetWidth;
    }
    if (hit.rowEdge) {
      drag.tr = hit.cell.parentElement;
      drag.startH = drag.tr.offsetHeight;
    }
    document.body.classList.add(hit.colEdge ? 'col-resizing' : 'row-resizing');
  });

  document.addEventListener('mousemove', e => {
    if (!drag) {
      // 悬停时高亮感应线并给出拖拽光标提示
      const hit = nearEdges(e);
      setEdgeMark(hit?.cell || null, hit ? (hit.colEdge ? 'edge-col' : 'edge-row') : null);
      table.style.cursor = hit ? (hit.colEdge ? 'col-resize' : 'row-resize') : '';
      return;
    }
    const dx = e.clientX - drag.startX, dy = e.clientY - drag.startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    if (drag.th) drag.th.style.width = Math.max(60, Math.min(900, drag.startW + dx)) + 'px';
    if (drag.tr) {
      // Excel 式行高：拖多高，文字就显示多少（解除两行截断，按高度裁剪）
      const h = Math.max(36, Math.min(800, drag.startH + dy));
      drag.tr.style.height = h + 'px';
      drag.tr.classList.add('resized');
      const max = (h - 20) + 'px';
      drag.tr.querySelectorAll('.role, .cname, .loc').forEach(el => { el.style.maxHeight = max; });
    }
  });

  document.addEventListener('mouseup', () => {
    if (!drag) return;
    if (drag.moved) {
      suppressRowClick = true;
      setTimeout(() => { suppressRowClick = false; }, 50);
      if (drag.th) {
        localStorage.setItem(COL_STORE_KEY, JSON.stringify(
          [...thAll()].map(t => parseInt(t.style.width) || 0)));
      }
    }
    document.body.classList.remove('col-resizing', 'row-resizing');
    table.style.cursor = '';
    drag = null;
  });
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  $('tabs').addEventListener('click', e => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    state.tab = btn.dataset.tab;
    expanded.clear();
    renderTabs();
    renderFilters();   // 刻面计数随页签变化
    refresh();
  });

  $('search').addEventListener('input', e => { state.q = e.target.value.trim(); refresh(); });
  $('search-clear').addEventListener('click', () => { state.q = ''; $('search').value = ''; refresh(); });

  $('sort').addEventListener('change', e => { state.sort = e.target.value; refresh(); });
  $('reset').addEventListener('click', () => resetFilters());
  $('full-toggle').addEventListener('click', () => {
    state.full = !state.full;
    $('full-toggle').classList.toggle('active', state.full);
    $('table').classList.toggle('full', state.full);
    // 完整显示时解除手动行高的裁剪，让全文展示
    if (state.full) {
      document.querySelectorAll('#tbody tr.resized').forEach(tr => {
        tr.classList.remove('resized');
        tr.style.height = '';
        tr.querySelectorAll('.role, .cname, .loc').forEach(el => { el.style.maxHeight = ''; });
      });
    }
  });

  // 下拉开合（互斥）
  $('filters').addEventListener('click', e => {
    const btn = e.target.closest('.dd-btn');
    if (btn) {
      const dd = btn.closest('.dd');
      const wasOpen = dd.classList.contains('open');
      document.querySelectorAll('.dd.open').forEach(d => d.classList.remove('open'));
      if (!wasOpen) {
        dd.classList.add('open');
        const inp = dd.querySelector('.dd-search');
        if (inp) inp.focus();
      }
      e.stopPropagation();
      return;
    }
    if (e.target.closest('.dd-panel')) e.stopPropagation();
  });
  document.addEventListener('click', () => document.querySelectorAll('.dd.open').forEach(d => d.classList.remove('open')));

  // 下拉内搜索
  $('filters').addEventListener('input', e => {
    if (e.target.closest('.dd-search')) {
      renderDropdownList(e.target.dataset.dsearch, e.target.value.trim());
      return;
    }
    if (e.target.dataset.range !== undefined) {
      state.range[e.target.dataset.range] = e.target.value;
      refresh();
    }
  });

  // 勾选筛选项
  $('filters').addEventListener('change', e => {
    const cb = e.target.closest('input[data-dsel]');
    if (!cb) return;
    const set = state.sel[cb.dataset.dsel];
    if (cb.checked) set.add(cb.value); else set.delete(cb.value);
    const dd = cb.closest('.dd');
    dd.classList.toggle('on', set.size > 0);
    const cntEl = dd.querySelector('.cnt');
    if (cntEl) { cntEl.textContent = set.size ? ` (${set.size})` : ''; }
    else if (set.size) {
      dd.querySelector('.dd-btn').insertAdjacentHTML('beforeend', ` <span class="cnt">(${set.size})</span>`);
    }
    refresh();
  });

  // 行点击展开
  $('tbody').addEventListener('click', e => {
    if (suppressRowClick || e.target.closest('a')) return;
    const row = e.target.closest('tr.row');
    if (!row) return;
    const idx = +row.dataset.idx;
    const next = row.nextElementSibling;
    if (expanded.has(idx)) {
      expanded.delete(idx);
      row.classList.remove('expanded');
      if (next && next.classList.contains('detail')) next.remove();
    } else {
      expanded.add(idx);
      row.classList.add('expanded');
      row.insertAdjacentHTML('afterend', detailHtml(idx));
    }
  });
}

function resetFilters() {
  state.q = '';
  state.major = '';
  $('search').value = '';
  for (const k in state.sel) state.sel[k].clear();
  for (const k in state.range) state.range[k] = '';
  renderFilters();
  refresh();
}

/* ---------- 启动 ---------- */
async function init() {
  try {
    const res = await fetch('data/records.json', { cache: 'no-cache' });
    DATA = await res.json();
  } catch (err) {
    $('loading').innerHTML = '数据加载失败。若以 file:// 直接打开，请改用 HTTP 访问（如 <code>python -m http.server</code>），部署后可正常访问。';
    return;
  }
  $('loading').remove();

  const hash = location.hash.replace('#', '');
  if (hash && TABS.some(t => t.id === hash)) state.tab = hash;

  const srcLink = $('src-link');
  srcLink.href = DATA.sources[0]?.url || '#';
  srcLink.textContent = DATA.sources[0]?.name || '飞书汇总表';
  $('meta').textContent = `共 ${DATA.total.toLocaleString()} 条 · 更新于 ${DATA.updated}`;

  buildFacets(DATA.records);
  computeTabCounts();
  renderTabs();
  renderFilters();
  bindEvents();
  initColResize();
  initEdgeResize();
  refresh();
}

init();
