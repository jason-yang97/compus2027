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
const BATCH_BADGE = { '秋招': 'b-qiu', '春招': 'b-chun', '实习': 'b-sx', '寒假实习': 'b-hj', '暑假实习': 'b-hj', '社招': 'b-she', '校招': 'b-qiu', '补录': 'b-bl', '提前批': 'b-tq', '未标注': 'b-unk' };

/* 列宽（Excel 式拖拽调整，localStorage 持久化） */
const COL_DEFAULTS = [170, 380, 180, 110, 110, 110, 110, 110, 190, 150];
const COL_STORE_KEY = 'jobboard-colw-v3';

/* ---------- 全局状态 ---------- */
let DATA = null;
let WORK = [];     // 当前工作数据集（按「岗位拆分」开关预处理后的数组）
let state = {
  tab: 'all',
  q: '',
  major: '',
  sel: { src: new Set(), ent: new Set(), ind: new Set(), city: new Set(), yrs: new Set(), tags: new Set(), test: new Set(), edu: new Set(), dl: new Set(), start: new Set() },
  range: { dlFrom: '', dlTo: '', stFrom: '', stTo: '' },
  sort: 'upd',
  full: false,
  split: true,     // 岗位拆分显示（把一行里的多个岗位展开成独立行）
  hidePast: true,  // 隐藏往届（只保留含 2027 及以后届次或无届次标注的记录）
  cityKw: '',      // 工作地点关键词（空格分隔，任一包含）
  page: 1,
};
let HIDDEN = new Set();   // 隐藏清单（管理后台导出，存于 recruit/data/hidden.json）
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

/* 岗位拆分：把「岗位1、岗位2、岗位3」展开成独立行，其余字段沿用原行（原型继承，省内存） */
const ROLE_SPLIT_RE = /[、,，;；]|\s{2,}|(?<=[^\s])\/(?=[^\s])/;
function splitRole(text) {
  const parts = String(text || '').split(ROLE_SPLIT_RE).map(s => s.trim()).filter(s => s.length >= 2);
  return parts.length > 1 ? parts.slice(0, 60) : [];
}

/* 隐藏清单键：公司||岗位||来源（管理后台导出，构建时过滤） */
const hideKey = r => `${r.c}||${r.r}||${r.src}`;

/* 隐藏往届：有届次但都不含 2027 及以后 → 视为往届 */
function isPastCohort(r) {
  const years = r.yrs.filter(y => typeof y === 'number');
  return years.length > 0 && !years.some(y => y >= 2027);
}

function buildWork(records) {
  const src = records.filter(r => !(state.hidePast && isPastCohort(r)) && !HIDDEN.has(hideKey(r)));
  if (!state.split) return src;
  const out = [];
  for (const r of src) {
    // 官网岗位：逐岗位结构化数据（自带地点/类型/事业群/岗位链接）
    if (r.roles && r.roles.length) {
      const extra = (r.batch || '').includes('提前批') ? ['提前批'] : [];
      for (const role of r.roles) {
        const o = Object.create(r);
        o.r = role.t || '';
        if (role.c) o.city = role.c.split(' / ').filter(Boolean);
        o.tags = [(role.k || '').includes('实习') ? '实习' : '秋招'].concat(extra);
        o._bg = role.b || '';
        o._d = role.d || '';    // 官方岗位描述
        o._q = role.q || '';    // 官方岗位要求
        if (role.u) o.url = role.u;
        o.dl = '';
        o.dlRaw = '尽快投递';
        out.push(o);
      }
      continue;
    }
    const parts = splitRole(r.r);
    if (!parts.length) { out.push(r); continue; }
    for (const p of parts) {
      const o = Object.create(r);   // 其余字段走原型链继承原行
      o.r = p;
      out.push(o);
    }
  }
  return out;
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
  if (!matchCityKw(r)) return false;
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
    const hay = `${r.c} ${r.r} ${r.note} ${r.major} ${r._d || ''} ${r._q || ''} ${r.ind.join(' ')} ${r.ent.join(' ')} ${r.edu.join(' ')} ${r.batch} ${r.written} ${r.src}`.toLowerCase();
    for (const kw of state.q.toLowerCase().split(/\s+/)) {
      if (kw && !hay.includes(kw)) return false;
    }
  }
  return true;
}

/* 工作地点关键词：多个关键词用空格分隔，任一包含即可 */
function matchCityKw(r) {
  if (!state.cityKw) return true;
  const hay = r.city.join(' ');
  return state.cityKw.split(/\s+/).some(kw => kw && hay.includes(kw));
}

/* 关键词/搜索条件（用于筛选器计数，反映当前搜索结果） */
function matchSearchOnly(r) {
  if (!matchCityKw(r)) return false;
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
  for (const r of WORK) {
    if (matchTab(r) && matchFilters(r)) out.push(r);
  }
  return out;
}

/* ---------- 排序 ---------- */
function sortRecords(list) {
  if (state.sort === 'dl') {
    list.sort((a, b) => (a.dl || '9999') < (b.dl || '9999') ? -1 : (a.dl || '9999') > (b.dl || '9999') ? 1 : 0);
  } else if (state.sort === 'start') {
    list.sort((a, b) => (a.start || '0000') < (b.start || '0000') ? 1 : (a.start || '0000') > (b.start || '0000') ? -1 : 0);
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
    for (const r of WORK) if (t.match(r)) n++;
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
  if (f.key === 'city') {
    return `<div class="dd-dates">
      <label>关键词 <input type="search" data-citykw placeholder="如：深圳 北京" value="${esc(state.cityKw)}"></label>
    </div>
    <div class="dd-note">按包含匹配，空格分隔多个关键词（任一包含即命中），与上方勾选叠加</div>`;
  }
  return '';
}

/* 当前搜索结果下的各筛选维度计数（随搜索/页签/关键词变化，反映真实可选数量） */
let countsNow = {};
function computeCountsNow() {
  countsNow = {};
  for (const f of FILTER_KEYS) if (!f.special) countsNow[f.key] = new Map();
  countsNow.test = new Map();
  countsNow.dl = new Map();
  const bump = (m, v) => m.set(v, (m.get(v) || 0) + 1);
  for (const r of WORK) {
    if (!matchTab(r) || !matchSearchOnly(r)) continue;
    for (const f of FILTER_KEYS) {
      if (f.special) continue;
      const vals = Array.isArray(r[f.key]) ? r[f.key] : [r[f.key]];
      for (const v of vals) bump(countsNow[f.key], String(v));
    }
    bump(countsNow.test, testBucket(r));
    bump(countsNow.dl, dlBucket(r));
  }
}

function renderDropdownList(key, kw = '') {
  const listEl = document.querySelector(`[data-dlist="${key}"]`);
  if (!listEl) return;
  const sel = state.sel[key];
  const cnt = v => (countsNow[key] || new Map()).get(v) || 0;
  let items;
  if (key === 'test') {
    items = TEST_OPTIONS.map(o => ({ v: o.v, name: o.name, n: cnt(o.v) }));
  } else if (key === 'dl') {
    items = DL_OPTIONS.map(o => ({ v: o.v, name: o.name, n: cnt(o.v) }));
  } else {
    items = (FACETS[key] || []).map(o => {
      const isYear = /^\d{4}$/.test(o.v);
      return { v: o.v, name: key === 'yrs' && isYear ? o.v + '届' : o.v, n: cnt(o.v) };
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
  for (const r of WORK) if (matchTab(r) && fn(r) === v) n++;
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
    ${r._d ? `<dt>岗位描述</dt><dd>${esc(r._d)}</dd>` : ''}
    ${r._q ? `<dt>岗位要求</dt><dd>${esc(r._q)}</dd>` : ''}
    <dt>备注</dt><dd>${esc(r.note) || '—'}</dd>
    <dt>原始批次</dt><dd>${esc(r.batch) || '—'}｜笔试说明：${esc(r.written) || '—'}</dd>
    ${r._bg ? `<dt>事业群</dt><dd>${esc(r._bg)}</dd>` : ''}
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
  $('result-meta').innerHTML = `当前页签命中 <b>${total.toLocaleString()}</b> 条（全部数据 ${WORK.length.toLocaleString()} 条，更新于 ${DATA.updated}）` +
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
  computeCountsNow();
  // 下拉里的计数随当前搜索结果更新
  for (const f of FILTER_KEYS) {
    if (f.special === 'start') continue;
    const inp = document.querySelector(`[data-dsearch="${f.key}"]`);
    renderDropdownList(f.key, inp ? inp.value.trim() : '');
  }
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

  // 岗位拆分开关：把一行里的多个岗位展开成独立行
  $('split-toggle').addEventListener('click', () => {
    state.split = !state.split;
    $('split-toggle').classList.toggle('active', state.split);
    WORK = buildWork(DATA.records);
    expanded.clear();
    buildFacets(WORK);
    computeTabCounts();
    renderTabs();
    renderFilters();
    refresh();
  });

  // 隐藏往届开关
  $('past-toggle').addEventListener('click', () => {
    state.hidePast = !state.hidePast;
    $('past-toggle').classList.toggle('active', state.hidePast);
    WORK = buildWork(DATA.records);
    expanded.clear();
    buildFacets(WORK);
    computeTabCounts();
    renderTabs();
    renderFilters();
    refresh();
  });

  // 管理后台
  $('admin-link').addEventListener('click', e => { e.preventDefault(); openAdmin(); });

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

  // 下拉内搜索 / 日期范围 / 地点关键词
  $('filters').addEventListener('input', e => {
    if (e.target.closest('.dd-search') && e.target.dataset.dsearch) {
      renderDropdownList(e.target.dataset.dsearch, e.target.value.trim());
      return;
    }
    if (e.target.dataset.citykw !== undefined) {
      state.cityKw = e.target.value.trim();
      refresh();
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
  state.cityKw = '';
  $('search').value = '';
  for (const k in state.sel) state.sel[k].clear();
  for (const k in state.range) state.range[k] = '';
  renderFilters();
  refresh();
}

/* ---------- 管理后台：重复项审查 ---------- */
function duplicateGroups() {
  const map = new Map();
  for (const r of DATA.records) {
    const k = `${r.c}||${r.r}`;
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(r);
  }
  return [...map.entries()].filter(([, v]) => v.length > 1)
    .sort((a, b) => b[1].length - a[1].length);
}

function openAdmin() {
  const groups = duplicateGroups();
  const total = groups.reduce((n, [, v]) => n + v.length, 0);
  const box = document.createElement('div');
  box.className = 'admin-mask';
  box.innerHTML = `
    <div class="admin-panel">
      <div class="admin-head">
        <h2>重复项审查</h2>
        <button class="btn-mode" id="admin-close">关闭</button>
      </div>
      <p class="admin-tip">共 <b>${groups.length}</b> 组重复（<b>${total}</b> 条记录，公司+岗位完全相同）。勾选要隐藏的记录后导出清单，
        保存为 <code>recruit/data/hidden.json</code> 并提交即可全局生效（或发我代为提交）。</p>
      <div class="admin-tools">
        <button class="btn-mode" id="admin-all">全选所有重复项</button>
        <button class="btn-mode" id="admin-none">清空选择</button>
        <button class="btn-mode active" id="admin-export">导出隐藏清单</button>
        <span id="admin-count" class="admin-count">已选 0 条</span>
      </div>
      <div class="admin-list">
        ${groups.map(([k, rows]) => `
          <div class="admin-group">
            <div class="admin-group-head">
              <label><input type="checkbox" data-group="${esc(k)}"> ${esc(rows[0].c)} — ${esc(rows[0].r).slice(0, 60)}（${rows.length} 条）</label>
            </div>
            ${rows.map(r => `
              <label class="admin-row">
                <input type="checkbox" class="admin-pick" data-key="${esc(hideKey(r))}">
                <span class="admin-src">${esc(r.src)}</span>
                <span>${esc(r.yrs.join('/') || '未标注')}</span>
                <span>${esc(r.city.join('/')) || '—'}</span>
                <span>${esc(r.upd || '—')}</span>
                <span class="admin-dl">${esc(r.dlRaw || '—')}</span>
              </label>`).join('')}
          </div>`).join('')}
      </div>
      <textarea id="admin-out" class="admin-out" placeholder="点「导出隐藏清单」生成 JSON，保存为 recruit/data/hidden.json"></textarea>
    </div>`;
  document.body.appendChild(box);
  const picks = () => [...box.querySelectorAll('.admin-pick')];
  const refreshCount = () => {
    box.querySelector('#admin-count').textContent = `已选 ${picks().filter(p => p.checked).length} 条`;
  };
  box.querySelector('#admin-close').onclick = () => box.remove();
  box.querySelector('#admin-all').onclick = () => { picks().forEach(p => { p.checked = true; }); refreshCount(); };
  box.querySelector('#admin-none').onclick = () => { picks().forEach(p => { p.checked = false; }); refreshCount(); };
  box.addEventListener('change', e => {
    const g = e.target.closest('input[data-group]');
    if (g) {
      const grp = g.closest('.admin-group');
      grp.querySelectorAll('.admin-pick').forEach(p => { p.checked = g.checked; });
      refreshCount();
      return;
    }
    refreshCount();
  });
  box.querySelector('#admin-export').onclick = () => {
    const keys = [...new Set(picks().filter(p => p.checked).map(p => p.dataset.key))];
    box.querySelector('#admin-out').value = JSON.stringify(keys, null, 1);
    box.querySelector('#admin-out').select();
  };
  refreshCount();
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
  if (srcLink) {
    srcLink.href = DATA.sources[0]?.url || '#';
    srcLink.textContent = DATA.sources[0]?.name || '汇总表';
  }
  $('meta').textContent = `共 ${DATA.total.toLocaleString()} 条 · 更新于 ${DATA.updated}`;

  // 隐藏清单（管理后台导出）随数据目录一并加载
  try {
    const hr = await fetch('data/hidden.json', { cache: 'no-cache' });
    if (hr.ok) HIDDEN = new Set(await hr.json());
  } catch (_) { /* 无隐藏清单 */ }

  WORK = buildWork(DATA.records);
  buildFacets(WORK);
  computeTabCounts();  renderTabs();
  renderFilters();
  bindEvents();
  initColResize();
  initEdgeResize();
  refresh();
}

init();
