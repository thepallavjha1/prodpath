'use strict';
/* prodpath web UI. No framework, no build step. Every string that comes from an analysed
   repository reaches the page through textContent only (never as markup): file names, snippets and
   env var names are attacker-controlled. */

const SVG_NS = 'http://www.w3.org/2000/svg';
const $ = (selector, root = document) => root.querySelector(selector);
const state = { bundle: null, runId: null, scenario: 'expected', tab: 'overview', file: null };

/* ---------- tiny DOM helpers ---------- */
function build(el, props, kids) {
  const p = props || {};
  if (p.cls) el.setAttribute('class', p.cls);
  if (p.text !== undefined) el.textContent = p.text;
  for (const [k, v] of Object.entries(p.attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  for (const [k, v] of Object.entries(p.css || {})) el.style.setProperty(k, String(v));
  for (const [k, v] of Object.entries(p.prop || {})) el[k] = v;
  for (const [k, v] of Object.entries(p.on || {})) el.addEventListener(k, v);
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const h = (tag, props, ...kids) => build(document.createElement(tag), props, kids);
const s = (tag, props, ...kids) => build(document.createElementNS(SVG_NS, tag), props, kids);
const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

function safeUrl(url) {
  return typeof url === 'string' && /^https:\/\/github\.com\//.test(url) ? url : null;
}
function usd(n, digits) {
  const v = Number(n) || 0;
  const d = digits === undefined ? (Math.abs(v) >= 1000 ? 0 : 2) : digits;
  return '$' + v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function num(n) {
  const v = Number(n) || 0;
  return v.toLocaleString('en-US', { maximumFractionDigits: v >= 100 ? 0 : 2 });
}
function toast(message) {
  const t = h('div', { cls: 'toast', text: message });
  document.body.append(t);
  setTimeout(() => t.remove(), 1600);
}
function store(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { /* private mode: fine */ }
  return null;
}

/* ---------- API ---------- */
async function api(path, body) {
  const options = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let response;
  try { response = await fetch(path, options); } catch (e) { throw new Error('Could not reach the prodpath server.'); }
  let data = null;
  try { data = await response.json(); } catch (e) { /* not json */ }
  if (!response.ok) throw new Error((data && data.error) || `Request failed (${response.status}).`);
  return data;
}

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const button = $('#theme');
  clear(button).append(s('svg', { attrs: { viewBox: '0 0 24 24' } }, s('use', { attrs: { href: theme === 'dark' ? '#i-sun' : '#i-moon' } })));
}
function initTheme() {
  const saved = store('prodpath:theme');
  const dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved || (dark ? 'dark' : 'light'));
  $('#theme').addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next); store('prodpath:theme', next);
  });
}

/* ---------- views ---------- */
function show(view) {
  for (const id of ['home', 'progress', 'result']) $(`#view-${id}`).hidden = id !== view;
  window.scrollTo(0, 0);
}
function readOptions() {
  const peak = parseFloat($('#opt-peak').value);
  const options = {
    environment: $('#opt-env').value,
    budget: $('#opt-budget').checked,
    validate: $('#opt-validate').checked,
  };
  if (peak > 0) options.usage = { peak_requests_per_second: peak };
  return options;
}

const STAGE_LABELS = { clone: 'Fetch', scan: 'Scan', facts: 'Read code', plan: 'Plan', forecast: 'Forecast' };
function renderStepper(stages, current, failed) {
  const list = clear($('#stepper'));
  const index = current === 'done' ? stages.length : Math.max(0, stages.indexOf(current));
  stages.forEach((name, i) => {
    let cls = '';
    if (i < index) cls = 'done';
    else if (i === index) cls = failed ? 'failed' : 'active';
    list.append(h('li', { cls }, STAGE_LABELS[name] || name));
  });
}

async function start(url, options) {
  $('#home-error').hidden = true;
  $('#go').disabled = true;
  try {
    const { job_id: jobId } = await api('/api/analyze', { url, options });
    $('#progress-title').textContent = url === 'sample' ? 'Analyzing the built-in sample' : 'Analyzing ' + url.replace('https://github.com/', '');
    $('#progress-error').hidden = true; $('#back').hidden = true; clear($('#log'));
    renderStepper(['clone', 'scan', 'facts', 'plan', 'forecast'], 'clone', false);
    show('progress');
    await poll(jobId);
  } catch (error) {
    $('#home-error').textContent = error.message; $('#home-error').hidden = false;
    show('home');
  } finally {
    $('#go').disabled = false;
  }
}

async function poll(jobId) {
  for (;;) {
    const job = await api(`/api/jobs/${jobId}`);
    $('#log').textContent = job.log.join('\n');
    $('#log').scrollTop = $('#log').scrollHeight;
    renderStepper(job.stages, job.status === 'done' ? 'done' : job.stage, job.status === 'error');
    if (job.status === 'error') {
      $('#progress-error').textContent = job.error; $('#progress-error').hidden = false; $('#back').hidden = false;
      return;
    }
    if (job.status === 'done') break;
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
  await openRun(jobId);
}

async function openRun(runId, tab) {
  state.bundle = await api(`/api/runs/${runId}`);
  state.runId = runId; state.tab = TABS.some((t) => t[0] === tab) ? tab : 'overview'; state.file = null; state.scenario = 'expected';
  history.replaceState(null, '', `#/run/${runId}${state.tab === 'overview' ? '' : '/' + state.tab}`);
  renderResult();
  show('result');
}

/* ---------- result shell ---------- */
const TABS = [
  ['overview', 'Overview'], ['architecture', 'Architecture'], ['cost', 'Cost'],
  ['risks', 'Risks'], ['plan', 'Plan'], ['terraform', 'Terraform'], ['facts', 'Facts'],
];
function renderResult() {
  const b = state.bundle;
  const src = b.source;
  $('#r-kicker').textContent = src.sample ? 'Built-in sample' : 'Analysis of';
  $('#r-title').textContent = src.sample ? 'Sample monorepo' : `${src.owner}/${src.repo}`;
  const bits = [];
  if (!src.sample) bits.push(`commit ${String(src.sha).slice(0, 7)}${src.branch ? ' on ' + src.branch : ''}`);
  bits.push(`${b.forecast.region}, ${b.prefs.environment}${b.prefs.budget ? ', budget network' : ''}`);
  $('#r-sub').textContent = bits.join(' · ');
  $('#r-zip').setAttribute('href', `/api/runs/${state.runId}/download.zip`);
  renderKpis();
  renderTabs();
  renderTab();
}
function renderKpis() {
  const b = state.bundle; const sm = b.summary;
  const span = sm.spike - sm.low || 1;
  const pos = Math.min(100, Math.max(0, ((sm.expected - sm.low) / span) * 100));
  const high = b.traps.filter((t) => t.severity === 'high').length;
  clear($('#kpis')).append(
    h('div', { cls: 'kpi hero-kpi' },
      h('div', { cls: 'label', text: 'Expected per month' }),
      h('div', { cls: 'value', text: usd(sm.expected) }),
      h('div', { cls: 'rangebar' }, h('div', { cls: 'fill', css: { left: '0%', right: '0%' } }), h('div', { cls: 'mark', css: { left: pos + '%' } })),
      h('div', { cls: 'note', text: `${usd(sm.low)} low  ·  ${usd(sm.spike)} spike` })),
    kpi('Services found', sm.services, 'deployable units'),
    kpi('AWS components', sm.components, `${sm.steps} ordered steps`),
    kpi('Risks flagged', sm.traps, high ? `${high} high severity` : 'none high'),
  );
}
const kpi = (label, value, note) => h('div', { cls: 'kpi' }, h('div', { cls: 'label', text: label }), h('div', { cls: 'value', text: value }), h('div', { cls: 'note', text: note }));

function renderTabs() {
  const b = state.bundle;
  const counts = { architecture: b.components.length, risks: b.traps.length, plan: b.steps.length, terraform: Object.keys(b.terraform.files).length, facts: b.services.length };
  const nav = clear($('#tabs'));
  for (const [id, label] of TABS) {
    nav.append(h('button', {
      cls: 'tab', attrs: { role: 'tab', type: 'button', 'aria-selected': String(state.tab === id) },
      on: { click: () => { state.tab = id; history.replaceState(null, '', `#/run/${state.runId}/${id}`); renderTabs(); renderTab(); } },
    }, label, counts[id] !== undefined ? h('span', { cls: 'count', text: counts[id] }) : null));
  }
}
function renderTab() {
  const body = clear($('#tab-body'));
  const render = { overview: tabOverview, architecture: tabArchitecture, cost: tabCost, risks: tabRisks, plan: tabPlan, terraform: tabTerraform, facts: tabFacts }[state.tab];
  body.append(render());
}

/* ---------- shared pieces ---------- */
function evidenceChips(list) {
  if (!list || !list.length) return null;
  return h('div', { cls: 'ev' }, list.slice(0, 6).map((e) => {
    const label = e.line ? `${e.path}:${e.line}` : e.path;
    const link = safeUrl(e.url);
    const attrs = { title: e.snippet || '' };
    if (link) return h('a', { attrs: { ...attrs, href: link, target: '_blank', rel: 'noopener noreferrer' }, text: label });
    return h('span', { attrs, text: label });
  }));
}

/* ---------- overview + service map ---------- */
const INFRA_KINDS = { datastore: 'db', cache: 'cache', queue: 'queue', object_store: 'storage' };
function tabOverview() {
  const b = state.bundle;
  const wrap = h('div');
  if (!b.summary.components) {
    wrap.append(h('div', { cls: 'card notice' }, h('h3', { text: 'Nothing deployable was found' }),
      h('p', { text: 'prodpath found no web service, worker, scheduled job or static site to run in production. Libraries and tooling repositories are not deployed, so there is no AWS plan or cost to show. Try a repository with a Dockerfile, a web framework app or a static site.' })));
  }
  wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'How the pieces connect' }), h('div', { cls: 'map-wrap' }, serviceMap(b)), mapLegend()));
  wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Services found' }),
    h('div', { cls: 'scroll' }, h('table', null,
      h('thead', null, h('tr', null, ['Service', 'Kind', 'Folder', 'Ports', 'Data and queues'].map((t) => h('th', { text: t })))),
      h('tbody', null, b.services.map((svc) => h('tr', null,
        h('td', null, h('b', { text: svc.id })), h('td', null, h('span', { cls: 'pill', text: svc.kind })), h('td', null, h('code', { text: svc.root })),
        h('td', { text: svc.facts.filter((f) => f.kind === 'port').map((f) => f.value).join(', ') || '-' }),
        h('td', { text: svc.facts.filter((f) => f.kind in INFRA_KINDS).map((f) => f.value).join(', ') || '-' }))))))));
  if (b.unknowns.length) wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'What the tool could not determine' }), h('ul', { cls: 'unknowns' }, b.unknowns.map((u) => h('li', { text: u })))));
  if (b.not_analyzed.length) wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Not analyzed' }), h('ul', null, b.not_analyzed.map((u) => h('li', { text: u })))));
  return wrap;
}
function mapLegend() {
  const items = [['http', 'var(--accent)', 'HTTP call'], ['db', 'var(--c2)', 'database'], ['queue', 'var(--c3)', 'queue'], ['cache', 'var(--c4)', 'cache'], ['storage', 'var(--c5)', 'object storage']];
  return h('div', { cls: 'legend' }, items.map(([, color, label]) => h('span', null, h('i', { css: { background: color } }), label)));
}
function serviceMap(b) {
  const NODE_W = 176, NODE_H = 48, GAP = 70, COLS = [24, 300, 590], WIDTH = 790;
  const services = b.services;
  const infra = new Map();
  for (const svc of services) for (const f of svc.facts) if (f.kind in INFRA_KINDS) infra.set(`${f.kind}:${f.value}`, { id: `${f.kind}:${f.value}`, label: f.value, sub: f.kind.replace('_', ' ') });
  for (const f of b.shared_infra) if (f.kind in INFRA_KINDS) infra.set(`${f.kind}:${f.value}`, { id: `${f.kind}:${f.value}`, label: f.value, sub: f.kind.replace('_', ' ') });
  const rows = Math.max(services.length, infra.size, 1);
  const height = rows * GAP + 30;
  const svg = s('svg', { cls: 'map', attrs: { viewBox: `0 0 ${WIDTH} ${height}`, role: 'img', 'aria-label': 'Service map' } });
  const pos = new Map();
  const place = (id, col, i, total) => pos.set(id, { x: COLS[col], y: 20 + (i + (rows - total) / 2) * GAP });
  services.forEach((svc, i) => place(svc.id, 1, i, services.length));
  [...infra.values()].forEach((n, i) => place(n.id, 2, i, infra.size));
  const edge = services.filter((x) => x.kind === 'web' || x.kind === 'static');
  if (edge.length) place('internet', 0, 0, 1);
  const edges = s('g'); const nodes = s('g');
  const link = (from, to, via) => {
    const a = pos.get(from), c = pos.get(to);
    if (!a || !c) return;
    const sameCol = a.x === c.x;
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = sameCol ? c.x + NODE_W : c.x, y2 = c.y + NODE_H / 2;
    const bend = sameCol ? 70 : (x2 - x1) / 2;
    const d = `M${x1},${y1} C${x1 + bend},${y1} ${x2 + (sameCol ? 70 : -bend)},${y2} ${x2},${y2}`;
    edges.append(s('path', { cls: `edge ${via}`, attrs: { d } }));
  };
  if (pos.has('internet')) for (const w of edge) {
    const a = pos.get('internet'), c = pos.get(w.id);
    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
    edges.append(s('path', { cls: 'edge http', attrs: { d: `M${x1},${y1} C${x1 + 60},${y1} ${c.x - 60},${c.y + NODE_H / 2} ${c.x},${c.y + NODE_H / 2}` } }));
  }
  for (const svc of services) for (const f of svc.facts) if (f.kind in INFRA_KINDS) link(svc.id, `${f.kind}:${f.value}`, INFRA_KINDS[f.kind]);
  for (const e of b.edges) if (e.via === 'http' || e.via === 'queue') link(e.src, e.dst, e.via);
  const node = (id, cls, title, sub) => {
    const p = pos.get(id);
    if (!p) return;
    nodes.append(s('g', { cls: `node ${cls}`, attrs: { transform: `translate(${p.x},${p.y})` } },
      s('rect', { attrs: { width: NODE_W, height: NODE_H, rx: 12 } }),
      s('text', { attrs: { x: 14, y: 21 }, text: title.length > 22 ? title.slice(0, 21) + '…' : title }),
      s('text', { cls: 'sub', attrs: { x: 14, y: 38 }, text: sub })));
  };
  if (pos.has('internet')) node('internet', 'infra', 'Internet users', 'load balancer / CDN');
  for (const svc of services) node(svc.id, svc.kind, svc.id, svc.kind + (svc.root && svc.root !== '.' ? ' · ' + svc.root : ''));
  for (const n of infra.values()) node(n.id, 'infra', n.label, n.sub);
  svg.append(edges, nodes);
  return svg;
}

/* ---------- architecture ---------- */
function tabArchitecture() {
  const b = state.bundle;
  const wrap = h('div', { cls: 'grid2' });
  for (const c of b.components) {
    wrap.append(h('article', { cls: 'card comp' },
      h('div', { cls: 'row' }, h('span', { cls: 'name', text: c.name }), h('span', { cls: 'pill', text: c.type }), c.serves.length ? h('span', { cls: 'pill', text: 'serves ' + c.serves.join(', ') }) : null),
      h('p', { cls: 'sizing', text: c.sizing }),
      h('p', { text: c.reason }),
      c.items.length ? h('div', { cls: 'ev' }, c.items.map((i) => h('span', { text: i }))) : null,
      evidenceChips(c.evidence)));
  }
  return wrap;
}

/* ---------- cost ---------- */
const COLORS = ['var(--c1)', 'var(--c2)', 'var(--c3)', 'var(--c4)', 'var(--c5)', 'var(--c6)', 'var(--c7)', 'var(--c8)', 'var(--c9)', 'var(--c10)', 'var(--c11)'];
const SCENARIOS = [['low', 'Quiet month'], ['expected', 'Expected'], ['spike', 'Spike month']];
function donut(groups, scenario) {
  const total = groups.reduce((a, g) => a + g[scenario], 0) || 1;
  const R = 70, C = 2 * Math.PI * R;
  const svg = s('svg', { attrs: { viewBox: '0 0 200 200', role: 'img', 'aria-label': 'Cost by group' } });
  svg.append(s('circle', { attrs: { cx: 100, cy: 100, r: R, fill: 'none', 'stroke-width': 26 }, css: { stroke: 'var(--card2)' } }));
  let offset = 0;
  groups.forEach((g, i) => {
    const len = (g[scenario] / total) * C;
    if (len <= 0) return;
    svg.append(s('circle', {
      attrs: { cx: 100, cy: 100, r: R, fill: 'none', 'stroke-width': 26, 'stroke-dasharray': `${Math.max(len - 1.5, 0.5)} ${C}`, 'stroke-dashoffset': -offset, transform: 'rotate(-90 100 100)' },
      css: { stroke: COLORS[i % COLORS.length] },
    }));
    offset += len;
  });
  return svg;
}
function costSummary() {
  const b = state.bundle; const sc = state.scenario;
  const groups = [...b.forecast.groups].sort((a, c) => c[sc] - a[sc]);
  const total = groups.reduce((a, g) => a + g[sc], 0);
  return h('div', { cls: 'card' },
    h('div', { cls: 'seg', attrs: { role: 'group', 'aria-label': 'Scenario' } }, SCENARIOS.map(([id, label]) => h('button', {
      attrs: { type: 'button', 'aria-pressed': String(sc === id) }, text: label, on: { click: () => { state.scenario = id; refreshCost(); } },
    }))),
    h('div', { cls: 'cost-top' },
      h('div', { cls: 'donut-wrap' }, donut(groups, sc), h('div', { cls: 'donut-center' }, h('b', { text: usd(total) }), h('span', { text: 'per month' }))),
      h('ul', { cls: 'legend-list' }, groups.map((g, i) => h('li', null,
        h('i', { cls: 'dot', css: { background: COLORS[i % COLORS.length] } }), h('span', { text: g.group }),
        h('b', { text: usd(g[sc]) }), h('span', { cls: 'muted', text: Math.round((g[sc] / (total || 1)) * 100) + '%' }),
        h('div', { cls: 'bar' }, h('i', { css: { width: (g[sc] / (total || 1)) * 100 + '%', background: COLORS[i % COLORS.length] } })))))));
}
let whatIfTimer = null;
function whatIf() {
  const u = state.bundle.usage || {};
  const peak0 = u.peak_requests_per_second ?? 20, ratio0 = u.peak_to_average_ratio ?? 5;
  const toSlider = (v) => Math.round((Math.log(Math.max(v, 0.5) / 0.5) / Math.log(1000)) * 100);
  const fromSlider = (v) => Math.round(0.5 * Math.pow(1000, v / 100) * 10) / 10;
  const peakOut = h('output', { text: num(peak0) + ' req/s' });
  const ratioOut = h('output', { text: num(ratio0) + 'x' });
  const budget = h('input', { attrs: { type: 'checkbox' }, prop: { checked: !!state.bundle.prefs.budget } });
  const env = h('select', null, h('option', { attrs: { value: 'prod' }, text: 'Production' }), h('option', { attrs: { value: 'nonprod' }, text: 'Non-production' }));
  env.value = state.bundle.prefs.environment;
  const peak = h('input', { attrs: { type: 'range', min: 0, max: 100, 'aria-label': 'Peak requests per second' }, prop: { value: toSlider(peak0) } });
  const ratio = h('input', { attrs: { type: 'range', min: 1, max: 20, step: 1, 'aria-label': 'Peak to average ratio' }, prop: { value: Math.round(ratio0) } });
  const fire = () => {
    peakOut.textContent = num(peakValue) + ' req/s'; ratioOut.textContent = ratio.value + 'x';
    clearTimeout(whatIfTimer);
    whatIfTimer = setTimeout(async () => {
      const card = $('#whatif-card'); if (card) card.classList.add('busy');
      try {
        state.bundle = await api(`/api/runs/${state.runId}/forecast`, {
          environment: env.value, budget: budget.checked,
          usage: { ...(state.bundle.usage || {}), peak_requests_per_second: peakValue, peak_to_average_ratio: +ratio.value },
        });
        renderKpis(); renderTabs(); refreshCost(true);
      } catch (error) { toast(error.message); } finally { const c = $('#whatif-card'); if (c) c.classList.remove('busy'); }
    }, 350);
  };
  let peakValue = peak0;
  peak.addEventListener('input', () => { peakValue = fromSlider(+peak.value); });
  for (const el of [peak, ratio, budget, env]) el.addEventListener('input', fire);
  return h('div', { cls: 'card', attrs: { id: 'whatif-card' } }, h('h3', { text: 'What if traffic changes?' }),
    h('div', { cls: 'whatif' },
      h('label', null, h('span', null, 'Peak traffic ', peakOut), peak),
      h('label', null, h('span', null, 'Peak is ', ratioOut, ' the average'), ratio),
      h('label', null, 'Environment', env),
      h('label', null, h('span', null, budget, ' Budget network (no endpoints, public IPs)'))));
}
function refreshCost(keepWhatIf) {
  const body = $('#tab-body');
  if (state.tab !== 'cost') return;
  const keep = $('#whatif-card');
  const fresh = tabCost(keepWhatIf || keep ? keep : null);
  clear(body).append(fresh);
}
function tabCost(existingWhatIf) {
  const b = state.bundle; const sc = state.scenario;
  const wrap = h('div');
  wrap.append(costSummary());
  wrap.append(existingWhatIf || whatIf());
  const sorted = [...b.forecast.lines].sort((a, c) => c[`usd_${sc}`] - a[`usd_${sc}`]);
  wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Every cost line' }), h('div', { cls: 'scroll' }, h('table', null,
    h('thead', null, h('tr', null, ['Component', 'What', 'Quantity', 'Unit price', 'USD / month', 'Price ref'].map((t, i) => h('th', { cls: i >= 2 && i < 5 ? 'num' : '', text: t })))),
    h('tbody', null, sorted.map((l) => h('tr', null,
      h('td', null, h('code', { text: l.component })), h('td', { text: l.dimension }),
      h('td', { cls: 'num', text: `${num(l[`qty_${sc}`])} ${l.unit}` }), h('td', { cls: 'num', text: '$' + Number(l.unit_price).toPrecision(4) }),
      h('td', { cls: 'num' }, h('b', { text: usd(l[`usd_${sc}`]) })), h('td', null, h('code', { cls: 'refcell', attrs: { title: l.price_ref }, text: l.price_ref }))))))),
    h('p', { cls: 'muted', text: 'Price snapshot: ' + b.forecast.price_snapshot })));
  wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Assumptions behind these numbers' }), h('div', { cls: 'scroll' }, h('table', null,
    h('thead', null, h('tr', null, ['Assumption', 'Value', 'Source', 'Note'].map((t) => h('th', { text: t })))),
    h('tbody', null, b.forecast.assumptions.map((a) => h('tr', null, h('td', null, h('code', { text: a.name })), h('td', { text: `${num(a.value)} ${a.unit}` }),
      h('td', null, h('span', { cls: 'pill', text: a.source })), h('td', { cls: 'muted', text: a.note }))))))));
  if (b.forecast.not_priced.length || b.forecast.not_included.length) {
    wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Not in these numbers' }),
      h('ul', null, [...b.forecast.not_priced.map((t) => 'No price in snapshot: ' + t), ...b.forecast.not_included].map((t) => h('li', { text: t })))));
  }
  return wrap;
}

/* ---------- risks ---------- */
function tabRisks() {
  const b = state.bundle;
  if (!b.traps.length) return h('div', { cls: 'empty', text: 'No risks flagged for this design.' });
  return h('div', null, b.traps.map((t) => h('article', { cls: `card trap ${t.severity}` },
    h('div', { cls: 'head' }, h('span', { cls: `pill ${t.severity}`, text: t.severity }), h('b', { text: t.id }),
      t.est_monthly_usd_impact !== null ? h('span', { cls: 'impact', text: usd(t.est_monthly_usd_impact) + ' / month' }) : null),
    h('p', { text: t.why }), h('p', { cls: 'muted' }, 'Where: ', h('code', { text: t.where })),
    h('div', { cls: 'fix' }, h('b', { text: 'Fix: ' }), t.fix))));
}

/* ---------- plan ---------- */
function copy(text, button) {
  const done = () => { toast('Copied'); if (button) { button.textContent = 'Copied'; setTimeout(() => { button.textContent = 'Copy'; }, 1200); } };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => toast('Copy is blocked in this browser'));
  else toast('Copy is blocked in this browser');
}
function tabPlan() {
  const b = state.bundle; const key = `prodpath:steps:${state.runId}`;
  let checked = [];
  try { checked = JSON.parse(store(key) || '[]'); } catch (e) { checked = []; }
  const wrap = h('div');
  wrap.append(h('div', { cls: 'card' }, h('div', { cls: 'row' }, h('h3', { text: 'Ordered deployment steps' }),
    h('button', { cls: 'ghost', attrs: { type: 'button' }, text: 'Copy PLAN.md', on: { click: () => copy(b.plan_md) } })),
    h('p', { cls: 'muted', text: 'Click a number to tick a step off. Commands use <PLACEHOLDERS>; nothing here holds credentials or account ids.' })));
  b.steps.forEach((st, i) => {
    const num = h('button', { cls: 'num', attrs: { type: 'button', 'aria-label': `Mark step ${i + 1} done` }, text: i + 1 });
    const box = h('article', { cls: 'card step' + (checked.includes(st.id) ? ' checked' : '') }, num,
      h('div', null, h('h3', { text: st.title }), h('p', { text: st.why }),
        st.commands.map((c) => { const btn = h('button', { cls: 'copy', attrs: { type: 'button' }, text: 'Copy' }); btn.addEventListener('click', () => copy(c, btn)); return h('div', { cls: 'cmd' }, h('pre', null, h('code', { text: c })), btn); }),
        h('p', { cls: 'verify' }, h('b', { text: 'Verify: ' }), st.verify)));
    num.addEventListener('click', () => {
      box.classList.toggle('checked');
      checked = checked.includes(st.id) ? checked.filter((x) => x !== st.id) : [...checked, st.id];
      store(key, JSON.stringify(checked));
    });
    wrap.append(box);
  });
  if (b.unknowns.length) wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Confirm before you deploy' }), h('ul', { cls: 'unknowns' }, b.unknowns.map((u) => h('li', { text: u })))));
  return wrap;
}

/* ---------- terraform ---------- */
const TF_TOKEN = /("(?:[^"\\]|\\.)*")|(\b\d+(?:\.\d+)?\b)|(\b(?:resource|variable|output|data|locals|module|provider|terraform|for_each|count|dynamic|lifecycle|depends_on|true|false|null)\b)/g;
function highlightLine(text) {
  if (/^\s*(#|\/\/)/.test(text)) return [h('span', { cls: 'tok-c', text })];
  const parts = []; let last = 0; let m;
  TF_TOKEN.lastIndex = 0;
  while ((m = TF_TOKEN.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(h('span', { cls: m[1] ? 'tok-s' : m[2] ? 'tok-n' : 'tok-k', text: m[0] }));
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
function codeView(text) {
  const pre = h('pre');
  text.split('\n').forEach((line, i) => pre.append(h('span', { cls: 'ln' }, h('span', { cls: 'no', text: i + 1 }), highlightLine(line))));
  return h('div', { cls: 'code' }, pre);
}
function tabTerraform() {
  const t = state.bundle.terraform; const names = Object.keys(t.files).sort();
  const wrap = h('div');
  wrap.append(h('div', { cls: 'card' }, h('h3', { text: 'Safety and validity checks' }),
    h('div', { cls: 'checks' }, t.checks.map((c) => h('span', { cls: `pill ${c.status}`, attrs: { title: c.detail }, text: `${c.name}: ${c.status}` }))),
    t.gaps.length ? h('div', null, h('b', { text: 'Known gaps: ' }), h('ul', null, t.gaps.map((g) => h('li', { text: g })))) : null));
  if (!names.length) { wrap.append(h('div', { cls: 'empty', text: 'No Terraform was generated for this design.' })); return wrap; }
  if (!state.file || !t.files[state.file]) state.file = names[0];
  const viewer = h('div'); const list = h('ul', { cls: 'files' });
  const select = (name) => {
    state.file = name;
    for (const btn of list.querySelectorAll('button')) btn.setAttribute('aria-current', String(btn.dataset.name === name));
    clear(viewer).append(codeView(t.files[name]));
  };
  for (const name of names) {
    const btn = h('button', { attrs: { type: 'button' }, text: name, on: { click: () => select(name) } });
    btn.dataset.name = name; list.append(h('li', null, btn));
  }
  wrap.append(h('div', { cls: 'tf' }, list, h('div', null,
    h('div', { cls: 'actions' }, h('button', { cls: 'ghost', attrs: { type: 'button' }, text: 'Copy this file', on: { click: () => copy(t.files[state.file]) } })), viewer)));
  select(state.file);
  return wrap;
}

/* ---------- facts ---------- */
function tabFacts() {
  const b = state.bundle;
  return h('div', null, b.services.map((svc) => h('article', { cls: 'card' },
    h('div', { cls: 'row' }, h('h3', { text: svc.id }), ' ', h('span', { cls: 'pill', text: svc.kind }), ' ', h('code', { text: svc.root })),
    svc.facts.length ? h('div', { cls: 'scroll' }, h('table', null,
      h('thead', null, h('tr', null, ['Kind', 'Value', 'How sure', 'Evidence'].map((t) => h('th', { text: t })))),
      h('tbody', null, svc.facts.map((f) => h('tr', null, h('td', null, h('span', { cls: 'pill', text: f.kind })), h('td', null, h('code', { text: f.value })),
        h('td', { text: f.certainty }), h('td', null, evidenceChips(f.evidence))))))) : h('p', { cls: 'muted', text: 'No facts extracted for this service.' }))));
}

/* ---------- wiring ---------- */
function goHome() { history.replaceState(null, '', location.pathname); show('home'); }
function init() {
  initTheme();
  const examples = $('#examples');
  examples.append(h('button', { cls: 'chip sample', attrs: { type: 'button' }, text: 'Try the built-in sample', on: { click: () => start('sample', readOptions()) } }));
  for (const url of ['https://github.com/thepallavjha1/Portfolio_GRPO_Indian_Tickers', 'https://github.com/thepallavjha1/prodpath']) {
    examples.append(h('button', { cls: 'chip', attrs: { type: 'button' }, text: url.replace('https://github.com/', ''), on: { click: () => { $('#url').value = url; } } }));
  }
  $('#form').addEventListener('submit', (event) => { event.preventDefault(); start($('#url').value.trim(), readOptions()); });
  $('#brand').addEventListener('click', (event) => { event.preventDefault(); goHome(); });
  $('#back').addEventListener('click', goHome);
  $('#r-new').addEventListener('click', goHome);
  const hash = location.hash;
  if (hash === '#sample') start('sample', readOptions());
  else if (/^#\/run\/[\w-]+/.test(hash)) {
    const [runId, tab] = hash.slice(6).split('/');
    openRun(runId, tab).catch((error) => { goHome(); $('#home-error').textContent = error.message; $('#home-error').hidden = false; });
  }
}
init();
