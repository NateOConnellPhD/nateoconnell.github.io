// Offline controller checks with a minimal DOM stub; not a rendered browser review.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const reference = require('../../assets/js/cfb-reference.js');
const source = fs.readFileSync(require.resolve('../../assets/js/cfb.js'), 'utf8');

class Element {
  constructor(select = false) {
    this.select = select; this.children = []; this.handlers = {}; this.attributes = {};
    this.textContent = ''; this.hidden = false; this.dataset = {}; this.style = {}; this._value = '';
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
  focus() {}
  scrollIntoView() {}
}

function row(season, week, version = 'new') {
  const id = `${season}-${week}-${version}`;
  return {season, week, id, games: week, reference_rank: 12, methodology: reference.methodology, json: `${id}.json`, csv: `${id}.csv`,
    references: Object.fromEntries(reference.ranks.map(rank => [rank, {reference_rank: rank,
      json: `${id}${rank===12?'':`-ref${rank}`}.json`, csv: `${id}${rank===12?'':`-ref${rank}`}.csv`}])),
    data_cutoff: `${season}-09-${String(week + 1).padStart(2, '0')}T00:00:00Z`, published_at: `${season}-11-21T00:00:00Z`};
}
const rows = [row(2026, 12), row(2026, 12, 'old'), row(2026, 10), row(2026, 0), row(2024, 16), row(2024, 2)];
const index = {schema: 'margin-of-merit-index-v1', latest: rows[0].id, snapshots: rows,
  archive: [{season: 2026, weeks: [0, 1, 10, 11, 12].map(week => ({week}))},
    {season: 2025, weeks: [{week: 1}, {week: 2}]}, {season: 2024, weeks: [{week: 2}, {week: 16}]}]};
const settle = () => new Promise(resolve => setImmediate(resolve));
async function page(query = '', data = index, fixtures = {}, policyRun = null) {
  const nodes = new Map(), get = key => {
    if (!nodes.has(key)) nodes.set(key, new Element(['season', 'week', 'update', 'reference', 'conference', 'limit', 'poll', 'poll-edition'].includes(key)));
    return nodes.get(key);
  };
  for (const [key, values] of [['reference', ['2', '4', '12', '24']], ['poll', ['', 'ap', 'cfp']], ['limit', ['25', 'all']]]) {
    get(key).replaceChildren(...values.map(value => { const option = new Element(); option.value = value; return option; }));
  }
  const root = new Element(); root.dataset.index = '/assets/data/cfb/index.json';
  root.querySelector = selector => get(selector.match(/data-cfb-([^\]]+)/)[1]);
  const location = {href: `https://example.test/blog/cfb/${query}`, search: query};
  const requests = [], shown = [], shownReferences = [], tabs = [];
  const context = {URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    cancelAnimationFrame() {}, requestAnimationFrame(callback) { callback(); return 0; }, location,
    history: {replaceState(_, __, address) { location.href = String(address); location.search = new URL(address).search; }},
    document: {querySelector: () => root, getElementById: () => get('title'), createElement: () => new Element(), createDocumentFragment: () => new Element()},
    window: {CFBReference: reference, CFBExplorer: () => ({show: snapshot => {shown.push(snapshot.id); shownReferences.push(snapshot.reference_rank);}, tab: name => tabs.push(name)}), CFBPolicy: policyRun && {run: policyRun, cancel() {}}},
    fetch: async address => {
      requests.push(String(address));
      const name = String(address).split('/').pop();
      if (name === 'polls.json') {
        const season = String(address).split('/').at(-2), value = fixtures[`polls-${season}`];
        return {ok: Boolean(value), status: value ? 200 : 404, json: async () => value};
      }
      const saved = data.snapshots.find(r => Object.values(r.references).some(ref => ref.json === name));
      const rank = saved && Object.values(saved.references).find(ref => ref.json === name).reference_rank;
      return {ok: true, json: async () => name === 'index.json' ? data : {...saved, publication_ready: true,
        schema: 'margin-of-merit-snapshot-v1', teams: [], policy_sha256: 'same', data_observed_at: saved.data_cutoff,
        reference_rank: rank, ...fixtures[saved.id], ...fixtures[`${saved.id}:${rank}`]}};
    }};
  vm.runInNewContext(source, context);
  await settle();
  return {get, root, location, requests, shown, shownReferences, tabs, async change(key, value) { get(key).value = value; await get(key).handlers.change(); await settle(); }};
}

(async () => {
  const p = await page();
  assert.equal(p.get('week').value, '12');
  assert.deepEqual(p.get('week').options.map(o => o.value), ['0', '1', '10', '11', '12']);
  assert.deepEqual(p.get('week').options.filter(o => o.disabled).map(o => o.value), ['1', '11']);
  assert.equal(p.get('archive').hidden, false);
  assert.equal(p.get('update').options.length, 2);
  assert.equal(p.get('revisions').hidden, false);
  assert.match(p.get('comparison').textContent, /Week 11 has no saved ranking/);
  assert.equal(p.requests.some(u => u.endsWith('2026-10-new.json')), false, 'Never skip a missing week for movement');
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
  await p.change('week', '2');
  const count = p.requests.length;
  await p.change('week', '16');
  await p.change('week', '2');
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
  const obsoleteIndex = JSON.parse(JSON.stringify(index));
  obsoleteIndex.snapshots.forEach(r => { r.methodology = 'margin-of-merit-2026-11-21'; });
  const obsolete = await page('?season=2026&week=12', obsoleteIndex);
  assert.equal(obsolete.shown.length, 0, 'Never display orders using the removed P4 policy');
  assert.equal(obsolete.get('results').hidden, true);
  const exact = await page('?snapshot=2026-12-old&season=2024&week=2');
  assert.equal(exact.shown.at(-1), '2026-12-old', 'Exact snapshot links keep their original revision');
  assert.equal(exact.get('week').value, '12');
  assert.equal(exact.get('update').value, '2026-12-old');
  const retired = {...rows[0], methodology: 'previous-methodology'};
  const migration = await page('', {...index, latest: retired.id, snapshots: [retired]});
  assert.equal(migration.shown.length, 0, 'Never show a prior-methodology ranking while its refit is pending');
  assert.equal(migration.requests.some(u => u.endsWith(retired.json)), false);
  const empty = await page('', {...index, latest: null, snapshots: []});
  assert.equal(empty.get('controls').hidden, false);
  assert.equal(empty.get('results').hidden, true);
  assert.equal(empty.get('latest').disabled, true);

  const weeklyRows = [row(2026, 11), row(2026, 11, 'old'), row(2026, 10), row(2026, 9)];
  const weeklyIndex = {...index, latest: weeklyRows[0].id, snapshots: weeklyRows};
  const teams = ranks => ranks.map((rank, i) => ({id: i + 1, name: `Team ${i + 1}`, rank, wins: 5, losses: 2, wins_fbs: 5, losses_fbs: 2}));
  const fixtures = {'2026-11-new': {teams: teams([1, 2, 3, 4, null])},
    '2026-10-new': {teams: teams([3, 1, 2, 4, null])}};
  const weekly = await page('', weeklyIndex, fixtures);
  assert.equal(weekly.get('change-label').textContent, 'Week 10 → 11');
  assert.match(weekly.get('comparison').textContent, /compares week 10 with week 11/);
  assert.equal(weekly.requests.some(u => u.endsWith('2026-11-old.json')), false, 'Same-week revision is never a baseline');
  const table = weekly.get('rows').children[0].children;
  assert.deepEqual(table.map(tr => tr.children.at(-1).textContent), ['↑ 2', '↓ 1', '↓ 1', '0']);
  assert.equal(table[0].children[2].textContent, '5–2', 'Movement is last, after every statistic');
  assert.equal(table[3].children.at(-1).children[0].textContent, 'Unchanged');

  const references = await page('?reference=2', weeklyIndex, {...fixtures,
    '2026-11-new:2': {teams: teams([2, 1, 3, 4])}, '2026-10-new:2': {teams: teams([1, 2, 3, 4])}});
  assert.equal(references.shownReferences.at(-1), 2);
  assert.match(references.get('csv').href.toString(), /-ref2.csv$/);
  assert.match(references.get('json').href.toString(), /-ref2.json$/);
  assert.match(references.get('permalink').href, /reference=2/);
  assert.match(references.get('comparison').textContent, /2nd reference in both weeks/);
  assert.equal(references.get('rows').children[0].children[0].children.at(-1).textContent, '↑ 1');
  await references.change('reference', '12');
  assert.equal(references.shownReferences.at(-1), 12);
  assert.equal(references.get('rows').children[0].children[0].children.at(-1).textContent, '↑ 2');
  const fetches = references.requests.length;
  await references.change('reference', '2');
  assert.equal(references.requests.length, fetches, 'Switching back reuses both reference-specific snapshots');
  await references.change('update', '2026-11-old');
  await references.change('reference', '24');
  assert.equal(references.shown.at(-1), '2026-11-old', 'Reference switches preserve the chosen revision');
  assert.equal(references.shownReferences.at(-1), 24);
  const mislabeled = await page('?reference=4', weeklyIndex, {...fixtures, '2026-11-new:4': {reference_rank:25}});
  assert.equal(mislabeled.get('results').hidden, true, 'Never relabel another reference as the selected one');

  const incomplete = {...row(2026, 12), week_complete: false};
  const gatedIndex = {...weeklyIndex, latest: incomplete.id, snapshots: [incomplete, ...weeklyRows],
    archive: [{season: 2026, weeks: [{week: 10}, {week: 11}]}]};
  const completed = await page('', gatedIndex, fixtures);
  assert.equal(completed.shown.at(-1), '2026-11-new', 'An incomplete latest pointer falls back to a completed week');
  assert.equal(completed.get('week').options.some(o => o.value === '12'), false);
  assert.equal(completed.requests.some(u => u.endsWith('2026-12-new.json')), false);
  const partialLink = await page('?snapshot=2026-12-new', gatedIndex, fixtures);
  assert.equal(partialLink.shown.at(-1), '2026-11-new', 'An old partial-snapshot link cannot load partial standings');

  const newTeam = await page('', weeklyIndex, {...fixtures, '2026-10-new': {teams: teams([3, 1, null, 4])}});
  assert.equal(newTeam.get('rows').children[0].children[2].children.at(-1).textContent, 'New');
  const incompatible = await page('', weeklyIndex, {...fixtures, '2026-10-new': {teams: teams([3, 1, 2, 4]), policy_sha256: 'older'}});
  assert.equal(incompatible.get('rows').children[0].children[0].children.at(-1).textContent, 'N/A');
  assert.match(incompatible.get('comparison').textContent, /different ranking rules/);
  const malformed = await page('', weeklyIndex, {...fixtures, '2026-10-new': {teams: teams([3, 1, 2, 4]), week: 11}});
  assert.match(malformed.get('comparison').textContent, /Week 10 could not be loaded/);

  const specification = {version: 'margin-of-merit-order-2026-11-21-no-p4', merit_protection: .9,
    head_to_head: .9, common_opponents: .7, proximity: 2, equal_records_only: true};
  const policyFixtures = Object.fromEntries(Object.entries(fixtures).map(([id, value]) => [id, {...value,
    specification, policy_inputs: {schema: 'margin-of-merit-policy-input-v5', id}, order: [1, 2, 3, 4]}]));
  const calls = [];
  const custom = await page('', weeklyIndex, policyFixtures, input => {
    calls.push(input.id); return {order: input.id.includes('-10-') ? [4, 1, 2, 3] : [4, 3, 2, 1]};
  });
  assert.equal(custom.get('reset').textContent, 'Reset ordering rules');
  assert.equal(custom.get('p4').handlers.input, undefined, 'The removed control has no handler');
  custom.get('protect').value = '85'; custom.get('protect').handlers.input();
  await new Promise(resolve => setTimeout(resolve, 200)); await settle();
  assert.deepEqual(calls, ['2026-11-new', '2026-10-new'], 'Apply custom rules to both weeks');
  assert.match(custom.get('comparison').textContent, /Both weeks use your selected rules/);
  assert.deepEqual(custom.get('rows').children[0].children.map(tr => tr.children.at(-1).textContent), ['0', '↑ 2', '0', '↓ 2']);
  await custom.change('reference', '4');
  assert.equal(custom.get('protect').value, '85', 'Reference switches preserve reader ordering controls');
  assert.match(custom.get('comparison').textContent, /4th reference in both weeks/);
  assert.match(custom.get('comparison').textContent, /Both weeks use your selected rules/);
  assert.equal(custom.shownReferences.at(-1), 4);
  custom.get('protect').value = '88'; custom.get('protect').handlers.input();
  await custom.change('reference', '24');
  assert.equal(custom.get('protect').value, '88', 'A pending slider edit survives switching references before its calculation');
  assert.match(custom.get('comparison').textContent, /24th reference in both weeks/);

  const roster = teams(Array.from({length: 138}, (_, i) => i + 1));
  const auditFixture = {...policyFixtures['2026-11-new'], teams: roster, order: roster.map(t => t.id),
    policy_inputs: {schema: 'margin-of-merit-policy-input-v5', teams: roster, opponents: [], games: [],
      probabilities: roster.map(() => roster.map(() => .5))},
    audit: roster.slice(1).map(t => ({winner_id: 1, loser_id: t.id, type: 'merit_protection', status: 'accepted', p_loser_higher_merit: .05}))};
  const focused = await page('', weeklyIndex, {...fixtures, '2026-11-new': auditFixture}, () => {});
  assert.equal(focused.get('team-b').value, '2', 'Default explanation compares the adjacent ranked team');
  assert.equal(focused.get('team-b').options.some(o => o.value === ''), false, 'No all-opponents option');
  focused.get('explanations').open = true; focused.get('explanations').handlers.toggle();
  assert.equal(focused.get('decisions').children.length, 1, 'Opening explanations must not render 137 comparisons');
  await focused.change('team-b', '138');
  assert.equal(focused.get('decisions').children.length, 1, 'A distant opponent still shows only that pair');
  await focused.change('team-a', '50');
  assert.equal(focused.get('team-b').value, '49');
  focused.get('open-rules').handlers.click();
  focused.get('open-rankings').handlers.click();
  assert.deepEqual(focused.tabs, ['rules', 'rankings']);
  focused.get('rows').children[0].children[0].children[1].children.at(-1).handlers.click();
  assert.equal(focused.tabs.at(-1), 'rules', 'Explain rank opens the separate Rules tab');
  assert.equal(focused.get('team-b').value, '2');

  const pollArchive = {schema: 'margin-of-merit-polls-v1', season: 2026, retrieved_at: '2026-11-20T00:00:00Z', editions: [
    {id: 'ap-regular-12', poll: 'ap', season_type: 'regular', week: 12, ranks: [{id: 1, rank: 3}, {id: 2, rank: 1}, {id: 6, rank: 25}]},
    {id: 'ap-regular-11', poll: 'ap', season_type: 'regular', week: 11, ranks: [{id: 1, rank: 1}]},
    {id: 'cfp-regular-13', poll: 'cfp', season_type: 'regular', week: 13, ranks: [{id: 3, rank: 1}]},
    {id: 'cfp-regular-16-final', poll: 'cfp', season_type: 'regular', week: 16, final: true, ranks: [{id: 1, rank: 1}]}]};
  const withPolls = {...fixtures, 'polls-2026': pollArchive,
    '2026-11-new': {teams: teams([1, 2, 3, 4, null, 30])}};
  const compared = await page('', weeklyIndex, withPolls);
  assert.equal(compared.requests.some(u => u.endsWith('/polls.json')), false, 'Do not fetch polls until requested');
  await compared.change('poll', 'ap');
  assert.equal(compared.get('poll-edition').value, 'ap-regular-12');
  let comparedRows = compared.get('rows').children[0].children;
  assert.equal(comparedRows.length, 5, 'Include poll Top 25 teams outside the merit Top 25');
  assert.equal(comparedRows[0].children[2].textContent, 3);
  assert.equal(comparedRows[0].children[3].textContent, '+2');
  assert.equal(comparedRows[1].children[3].textContent, '-1');
  assert.equal(comparedRows[2].children[2].textContent, 'NR');
  assert.equal(comparedRows[2].children[3].textContent, 'N/A', 'NR is not rank 26');
  assert.equal(comparedRows[0].children.at(-1).textContent, '↑ 2', 'Weekly movement stays last and independent of polls');
  assert.match(compared.get('poll-note').textContent, /week 12/);
  await compared.change('poll', 'cfp');
  assert.equal(compared.get('poll-edition').value, '', 'Do not substitute a future CFP edition');
  assert.match(compared.get('poll-note').textContent, /no saved edition/);
  assert.equal(compared.get('rows').children[0].children[0].children[2].textContent, 'N/A');
  await compared.change('poll-edition', 'cfp-regular-16-final');
  assert.match(compared.get('poll-note').textContent, /week 16 \(final\)/);
  await compared.change('week', '10');
  await compared.change('poll', 'ap');
  assert.equal(compared.get('poll-edition').value, 'ap-regular-11', 'Week change selects the matching suggested edition');
  assert.equal(compared.requests.filter(u => u.endsWith('/polls.json')).length, 1, 'Weeks and poll choices reuse one static season file');
  assert.equal(compared.requests.every(u => u.startsWith('https://example.test/') || u === '/assets/data/cfb/index.json'), true);
  await compared.change('poll', '');
  assert.equal(compared.get('poll-rank-heading').hidden, true);
  assert.equal(compared.get('rows').children[0].children[0].children.length, 8);
  const missingPolls = await page('', weeklyIndex, fixtures);
  await missingPolls.change('poll', 'ap');
  assert.match(missingPolls.get('poll-note').textContent, /could not be loaded/);
  assert.equal(missingPolls.get('results').hidden, false, 'Missing polls never hide merit rankings');

  // Exercise the real explorer controller with a stale history file containing
  // the partial week, rather than relying on the main-controller explorer stub.
  const elements = new Map(), get = key => {
    if (!elements.has(key)) elements.set(key, new Element());
    return elements.get(key);
  };
  const tabNames = ['rankings', 'conferences', 'rules', 'posterior', 'history'];
  const buttons = tabNames.map(name => { const n = new Element(); n.dataset.cfbTab = name; return n; });
  const panels = tabNames.map(name => { const n = new Element(); n.dataset.cfbPanel = name; return n; });
  const explorerRoot = {querySelector: s => get(s.match(/data-cfb-([^\]]+)/)[1]),
    querySelectorAll: s => s === '[data-cfb-tab]' ? buttons : panels};
  const explorerContext = {window: {CFBReference: reference, CFBConferences: () => ({show(){},tab(){},resize(){}})}, document: {createElement: () => new Element(), createElementNS: () => new Element()},
    ResizeObserver: class { observe() {} }};
  vm.runInNewContext(fs.readFileSync(require.resolve('../../assets/js/cfb-explorer.js'), 'utf8'), explorerContext);
  const history = {schema: 'margin-of-merit-history-v1', season: 2026,
    weeks: [10, 11, 12].map(week => ({week, id: `2026-${week}-new`, policy_sha256: 'same', teams: teams([1, 2]),
      references: {12: {reference_rank:12, policy_sha256:'same', teams:teams([1,2])},
        2: {reference_rank:2, policy_sha256:'same', teams:teams(week===10?[2,1]:[1,2])}}}))};
  const explorer = explorerContext.window.CFBExplorer(explorerRoot, {fetchJSON: async () => history, url: path => path});
  get('history-metric').value = 'rank';
  explorer.show({season: 2026, reference_rank:12, teams: teams([1, 2]), order: [1, 2]},
    {snapshots: weeklyRows, archive: [{season: 2026, weeks: [{week: 10}, {week: 11}]}]});
  explorer.tab('rules');
  assert.deepEqual(panels.map(n => n.hidden), [true, true, false, true, true]);
  assert.deepEqual(buttons.map(n => n.attributes['aria-selected']), [false, false, true, false, false]);
  explorer.tab('history'); await settle();
  assert.match(get('history-status').textContent, /2 saved weeks/);
  assert.deepEqual(get('history-rows').children.map(tr => tr.children[0].children[0].textContent), ['Week 10', 'Week 11']);
  assert.equal(get('history-rows').children.at(-1).children.at(-1).textContent, '0 (unchanged)');
  explorer.show({season:2026, reference_rank:2, teams:teams([1,2]), order:[1,2]},
    {snapshots:weeklyRows, archive:[{season:2026,weeks:[{week:10},{week:11}]}]});
  await settle();
  assert.match(get('history-status').textContent, /2nd reference/);
  assert.equal(get('history-rows').children.at(-1).children.at(-1).textContent, '↑ 1', 'History movement uses the selected reference for both weeks');
  console.log('Offline controller checks passed: references, preserved ordering controls, downloads, history, movement, polls and cache reuse.');
})().catch(error => { console.error(error); process.exitCode = 1; });
