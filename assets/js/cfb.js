(() => {
  'use strict';
  const root = document.querySelector('[data-cfb]');
  if (!root) return;
  const el = key => root.querySelector(`[data-cfb-${key}]`);
  const base = new URL('./', new URL(root.dataset.index, location.href));
  const snapshots = new Map();
  let index, current, previous, loadNumber = 0;
  let sortKey = 'rank', direction = 1;
  const date = value => new Date(value).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  });
  const fixed = value => Number.isFinite(value) ? value.toFixed(2) : '—';
  const interval = (low, high, digits = 1) => Number.isFinite(low) && Number.isFinite(high)
    ? `${low.toFixed(digits)}–${high.toFixed(digits)}` : '—';
  function url(path) {
    const result = new URL(path, base);
    if (result.origin !== base.origin || !result.pathname.startsWith(base.pathname)) throw new Error('Invalid archive URL');
    return result;
  }
  async function fetchJSON(address, cache = 'default') {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(address, {cache, signal: controller.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  async function read(row) {
    if (!snapshots.has(row.id)) {
      const value = await fetchJSON(url(row.json));
      if (!value.publication_ready || value.schema !== 'margin-of-merit-snapshot-v1' || !Array.isArray(value.teams)) {
        throw new Error('Unpublished or invalid ranking');
      }
      snapshots.set(row.id, value);
    }
    return snapshots.get(row.id);
  }
  function option(value, label) {
    const node = document.createElement('option');
    node.value = value; node.textContent = label; return node;
  }
  function populateUpdates(season, selected) {
    el('season').value = String(season);
    el('update').replaceChildren(...index.snapshots.filter(r => r.season === Number(season)).map(r =>
      option(r.id, `Week ${r.week} · ${date(r.data_observed_at)} · ${r.games} games`)));
    if (selected) el('update').value = selected;
  }
  function notice() {
    const attempt = index.last_attempt;
    const sameSeason = attempt && current && attempt.season === current.season;
    el('notice').hidden = !(sameSeason && attempt.status === 'failed');
    if (!el('notice').hidden) el('notice').textContent =
      `The update attempted ${date(attempt.at)} did not finish. The last successful rankings are shown below.`;
  }
  function render() {
    if (!current) return;
    const query = el('search').value.trim().toLocaleLowerCase();
    const conference = el('conference').value;
    const rows = current.teams.filter(r => (!query || r.name.toLocaleLowerCase().includes(query)) &&
      (!conference || r.conference === conference) &&
      (query || conference || el('limit').value === 'all' || (r.rank != null && r.rank <= 25)));
    rows.sort((a, b) => {
      if (a[sortKey] == null) return b[sortKey] == null ? a.name.localeCompare(b.name) : 1;
      if (b[sortKey] == null) return -1;
      const compare = sortKey === 'name' ? a.name.localeCompare(b.name) : a[sortKey] - b[sortKey];
      return direction * compare || (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.name.localeCompare(b.name);
    });
    const oldRanks = new Map((previous?.teams || []).map(r => [r.id, r.rank]));
    const fragment = document.createDocumentFragment();
    for (const r of rows) {
      const tr = document.createElement('tr');
      function cell(text, secondary, strong = false) {
        const td = document.createElement('td');
        if (strong) { const label = document.createElement('strong'); label.textContent = text; td.append(label); }
        else td.textContent = text;
        if (secondary != null) { const small = document.createElement('small'); small.textContent = secondary; td.append(small); }
        tr.append(td); return td;
      }
      cell(r.rank ?? '—');
      cell(r.name, r.conference || 'Independent', true);
      const oldRank = oldRanks.get(r.id);
      const change = r.rank != null && oldRank != null ? oldRank - r.rank : null;
      const movement = cell(change == null ? '—' : change > 0 ? `↑ ${change}` : change < 0 ? `↓ ${-change}` : '·');
      movement.setAttribute('aria-label', change == null ? 'No comparison' : change === 0 ? 'Unchanged' : `${change > 0 ? 'Up' : 'Down'} ${Math.abs(change)} places`);
      cell(`${r.wins_fbs}–${r.losses_fbs}`);
      cell(r.rank == null ? '—' : fixed(r.merit_mean), r.rank == null ? 'No eligible games' : interval(r.merit_lo90, r.merit_hi90, 2));
      cell(interval(r.raw_rank_lo90, r.raw_rank_hi90));
      cell(Number.isFinite(r.p_raw_merit_top10) ? `${(r.p_raw_merit_top10 * 100).toFixed(1)}%` : '—');
      fragment.append(tr);
    }
    if (!rows.length) {
      const tr = document.createElement('tr'), td = document.createElement('td');
      td.colSpan = 7; td.textContent = 'No matching teams. Try another search or conference.'; tr.append(td); fragment.append(tr);
    }
    el('rows').replaceChildren(fragment);
    el('count').textContent = `${rows.length} of ${current.teams.length} teams shown.${query || conference ? ' Search and conference filters include all ranks.' : ''}`;
  }
  async function select(id, writeURL = true) {
    const row = index.snapshots.find(r => r.id === id);
    if (!row) return;
    const sequence = ++loadNumber;
    el('status').hidden = false; el('status').textContent = 'Loading saved update…';
    el('results').hidden = true; el('csv').hidden = true;
    root.setAttribute('aria-busy', 'true');
    populateUpdates(row.season, id);
    try {
      const result = await read(row);
      const older = index.snapshots.find(r => r.season === row.season && r.week < row.week && r.data_cutoff < row.data_cutoff);
      let prior = null;
      if (older) { try { prior = await read(older); } catch (_) { /* Rankings remain usable without movement. */ } }
      if (sequence !== loadNumber) return;
      current = result;
      previous = prior?.policy_sha256 === current.policy_sha256 ? prior : null;
      el('label').textContent = `${row.season} season / ${id === index.latest ? 'Latest update' : 'Saved update'}`;
      document.getElementById('cfb-title').textContent = `Week ${row.week} rankings`;
      const checked = index.last_attempt?.season === row.season && id === index.latest && index.last_attempt.status !== 'failed'
        ? ` Last checked ${date(index.last_attempt.at)}.` : '';
      el('timing').textContent = `${current.games} completed FBS–FBS games. Data observed ${date(current.data_observed_at)}. Published ${date(current.published_at)}.${checked} Unplayed games in this week are not included.`;
      el('caption').textContent = `${row.season} Margin of Merit, week ${row.week}, data observed ${date(current.data_observed_at)}`;
      const chosenConference = el('conference').value;
      el('conference').replaceChildren(option('', 'All conferences'), ...[...new Set(current.teams.map(r => r.conference).filter(Boolean))].sort().map(c => option(c, c)));
      if ([...el('conference').options].some(o => o.value === chosenConference)) el('conference').value = chosenConference;
      el('comparison').textContent = previous ? `Change compares with the saved week ${previous.week} update from ${date(previous.data_observed_at)}.` : 'No earlier saved week with the same ordering policy is available for comparison.';
      const address = new URL(location.href);
      address.searchParams.set('snapshot', id); address.searchParams.delete('season'); address.hash = '';
      el('permalink').href = address.href;
      el('csv').href = url(row.csv); el('csv').hidden = false;
      el('json').href = url(row.json);
      if (writeURL) history.replaceState(null, '', address);
      notice(); render(); el('results').hidden = false;
      el('status').textContent = `Loaded ${row.season} week ${row.week}.`;
      el('status').hidden = true;
    } catch (_) {
      if (sequence === loadNumber) el('status').textContent = 'This saved update could not be loaded. Choose another update or reload the page.';
    } finally { if (sequence === loadNumber) root.removeAttribute('aria-busy'); }
  }
  el('season').addEventListener('change', () => {
    populateUpdates(el('season').value); select(el('update').value);
  });
  el('update').addEventListener('change', () => select(el('update').value));
  function latest() {
    if (!index?.latest) return;
    el('search').value = ''; el('conference').value = '';
    const address = new URL(location.href);
    address.searchParams.delete('snapshot'); address.searchParams.delete('season');
    history.replaceState(null, '', address);
    select(index.latest, false);
  }
  el('latest').addEventListener('click', latest);
  el('current').addEventListener('click', latest);
  for (const key of ['search', 'conference', 'limit']) el(key).addEventListener(key === 'search' ? 'input' : 'change', render);
  root.querySelectorAll('[data-cfb-sort]').forEach(button => button.addEventListener('click', () => {
    const key = button.dataset.cfbSort;
    direction = sortKey === key ? -direction : key === 'rank' || key === 'name' ? 1 : -1;
    sortKey = key;
    root.querySelectorAll('[data-cfb-sort]').forEach(other => {
      const th = other.closest('th');
      th.removeAttribute('aria-sort');
      const arrow = other.querySelector('span'); if (arrow) arrow.remove();
    });
    button.closest('th').setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
    const arrow = document.createElement('span'); arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = direction === 1 ? ' ↑' : ' ↓'; button.append(arrow); render();
  }));
  async function start() {
    try {
      index = await fetchJSON(root.dataset.index, 'no-store');
      if (index.schema !== 'margin-of-merit-index-v1' || !Array.isArray(index.snapshots)) throw new Error('Invalid archive');
      if (!index.snapshots.length) {
        el('status').textContent = index.last_attempt?.status === 'failed'
          ? 'The first ranking update did not finish. No rankings have been published yet.'
          : 'No rankings have been published yet.';
        return;
      }
      el('controls').hidden = false;
      el('season').replaceChildren(...[...new Set(index.snapshots.map(r => r.season))].sort((a,b) => b-a).map(s => option(s, s)));
      const query = new URLSearchParams(location.search);
      const requested = index.snapshots.find(r => r.id === query.get('snapshot')) ||
        index.snapshots.find(r => String(r.season) === query.get('season')) || index.snapshots.find(r => r.id === index.latest);
      if (!requested) throw new Error('Missing latest update');
      await select(requested.id, false);
    } catch (_) { el('status').textContent = 'The ranking archive could not be loaded. Please reload the page in a moment.'; }
  }
  start();
})();
