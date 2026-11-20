// Offline controller checks with a minimal DOM stub; not a rendered browser review.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../../assets/js/cfb.js'), 'utf8');

class Element {
  constructor(select = false) {
    this.select = select; this.children = []; this.handlers = {}; this.attributes = {};
    this.textContent = ''; this.hidden = false; this.dataset = {}; this._value = '';
  }
  set value(value) { this._value = String(value); }
  get value() { return this.select && !this.children.some(c => c.value === this._value) ? '' : this._value; }
  get options() { return this.children; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; if (this.select) this.value = nodes.find(n => !n.disabled)?.value ?? nodes[0]?.value ?? ''; }
  setAttribute(key, value) { this.attributes[key] = value; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  querySelectorAll() { return []; }
}

function row(season, week, version = 'new') {
  const id = `${season}-${week}-${version}`;
  return {season, week, id, games: week, json: `${id}.json`, csv: `${id}.csv`,
    data_cutoff: `${season}-09-${String(week + 1).padStart(2, '0')}T00:00:00Z`, published_at: `${season}-11-21T00:00:00Z`};
}
const rows = [row(2026, 12), row(2026, 12, 'old'), row(2026, 10), row(2026, 0), row(2024, 16), row(2024, 2)];
const index = {schema: 'margin-of-merit-index-v1', latest: rows[0].id, snapshots: rows,
  archive: [{season: 2026, weeks: [0, 1, 10, 11, 12].map(week => ({week}))},
    {season: 2025, weeks: [{week: 1}, {week: 2}]}, {season: 2024, weeks: [{week: 2}, {week: 16}]}]};
const settle = () => new Promise(resolve => setImmediate(resolve));
async function page(query = '', data = index) {
  const nodes = new Map(), get = key => {
    if (!nodes.has(key)) nodes.set(key, new Element(['season', 'week', 'update', 'conference', 'compare-update', 'limit'].includes(key)));
    return nodes.get(key);
  };
  const root = new Element(); root.dataset.index = '/assets/data/cfb/index.json';
  root.querySelector = selector => get(selector.match(/data-cfb-([^\]]+)/)[1]);
  const location = {href: `https://example.test/blog/cfb/${query}`, search: query};
  const requests = [], shown = [];
  const context = {URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    cancelAnimationFrame() {}, location,
    history: {replaceState(_, __, address) { location.href = String(address); location.search = new URL(address).search; }},
    document: {querySelector: () => root, getElementById: () => get('title'), createElement: () => new Element(), createDocumentFragment: () => new Element()},
    window: {CFBExplorer: () => ({show: snapshot => shown.push(snapshot.id)})},
    fetch: async address => {
      requests.push(String(address));
      const name = String(address).split('/').pop();
      const saved = rows.find(r => `${r.id}.json` === name);
      return {ok: true, json: async () => name === 'index.json' ? data : {...saved, publication_ready: true,
        schema: 'margin-of-merit-snapshot-v1', teams: [], policy_sha256: 'same', data_observed_at: saved.data_cutoff}};
    }};
  vm.runInNewContext(source, context);
  await settle();
  return {get, root, location, requests, shown, async change(key, value) { get(key).value = value; await get(key).handlers.change(); await settle(); }};
}

(async () => {
  const p = await page();
  assert.equal(p.get('week').value, '12');
  assert.deepEqual(p.get('week').options.map(o => o.value), ['0', '1', '10', '11', '12']);
  assert.deepEqual(p.get('week').options.filter(o => o.disabled).map(o => o.value), ['1', '11']);
  assert.equal(p.get('archive').hidden, false);
  assert.equal(p.get('update').options.length, 2);
  assert.equal(p.get('revisions').hidden, false);
  for (const label of [p.get('timing').textContent, ...p.get('week').options.map(o => o.textContent), ...p.get('update').options.map(o => o.textContent)]) {
    assert.doesNotMatch(label, /\d{1,2}:\d{2}|\b(?:AM|PM|UTC|GMT|EST|EDT)\b/, 'Public dates should omit times');
  }
  assert.doesNotMatch(p.get('mode').textContent, /\bv\d+\b/, 'Public labels should omit internal model versions');

  await p.change('week', '0');
  assert.equal(p.shown.at(-1), '2026-0-new');
  assert.equal(p.get('revisions').hidden, true);
  assert.equal(new URL(p.location.href).searchParams.get('week'), '0');
  await p.change('season', '2024');
  assert.equal(p.get('week').value, '16');
  assert.deepEqual(p.get('archive-grid').children.map(n => n.textContent), ['Week 2', 'Week 16']);
  const count = p.requests.length;
  await p.change('week', '2');
  await p.change('week', '16');
  assert.equal(p.requests.length, count, 'Revisiting loaded weeks reuses saved data in memory');
  await p.change('season', '2025');
  assert.equal(p.get('results').hidden, true, 'Pending season must hide previous season results');
  assert.equal(p.get('csv').hidden, true);
  assert.equal(p.get('week').disabled, true);
  assert.match(p.get('status').textContent, /2025/);
  assert.equal(p.root.attributes['aria-busy'], undefined);

  const linked = await page('?season=2024&week=2');
  assert.equal(linked.shown.at(-1), '2024-2-new');
  const pending = await page('?season=2026&week=11');
  assert.equal(pending.shown.length, 0, 'A missing linked week must not silently load another week');
  assert.equal(pending.get('results').hidden, true);
  assert.match(pending.get('status').textContent, /2026 week 11/);
  const exact = await page('?snapshot=2026-12-old&season=2024&week=2');
  assert.equal(exact.shown.at(-1), '2026-12-old', 'Exact snapshot links keep their original revision');
  assert.equal(exact.get('week').value, '12');
  assert.equal(exact.get('update').value, '2026-12-old');
  const empty = await page('', {...index, latest: null, snapshots: []});
  assert.equal(empty.get('controls').hidden, false);
  assert.equal(empty.get('results').hidden, true);
  assert.equal(empty.get('latest').disabled, true);
  console.log('Weekly navigation checks passed: grouping, revisions, week zero, season switching, pending fits, links and cache reuse.');
})().catch(error => { console.error(error); process.exitCode = 1; });
