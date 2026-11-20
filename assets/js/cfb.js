(() => {
  'use strict';
  const root = document.querySelector('[data-cfb]');
  if (!root) return;
  const el = key => root.querySelector(`[data-cfb-${key}]`);
  const base = new URL('./', new URL(root.dataset.index, location.href));
  const snapshots = new Map();
  const explorer = window.CFBExplorer(root, {fetchJSON, url, select});
  let index, current, previous, loadNumber = 0;
  let previousRanks = new Map(), comparisonUnavailable = '', customComparisonUnavailable = '';
  let viewTeams, policyResult, customPolicy = false, policyError = null, policyFrame = 0;
  let sortKey = 'rank', direction = 1;
  const date = value => new Date(value).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'America/New_York'
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
      if (!value.publication_ready || value.schema !== 'margin-of-merit-snapshot-v1' || !Array.isArray(value.teams) ||
          value.season !== row.season || value.week !== row.week) {
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
  function seasonWeeks(season) {
    const rows = index.snapshots.filter(r => r.season === Number(season));
    const expected = (index.archive || []).find(s => s.season === Number(season))?.weeks || [];
    return [...new Set([...rows.map(r => r.week), ...expected.map(w => w.week)])].sort((a, b) => a - b)
      .map(week => ({week, row: rows.find(r => r.week === week)}));
  }
  function populateUpdates(season, selected, requestedWeek = null) {
    el('season').value = String(season);
    const rows = index.snapshots.filter(r => r.season === Number(season));
    const weeks = seasonWeeks(season);
    const week = rows.find(r => r.id === selected)?.week ?? requestedWeek ?? rows[0]?.week ?? weeks[weeks.length - 1]?.week;
    el('week').replaceChildren(...weeks.map(({week, row}) => {
      const node = option(week, `Week ${week} · ${row ? date(row.data_cutoff) : 'awaiting fit'}`);
      node.disabled = !row; return node;
    }));
    el('week').value = String(week ?? '');
    el('week').disabled = !rows.length;
    const revisions = rows.filter(r => r.week === week);
    el('update').replaceChildren(...revisions.map((r, i) =>
      option(r.id, `${i === 0 ? 'Latest version' : `Earlier version ${i}`} · Saved ${date(r.published_at)} · ${r.games} games`)));
    if (selected) el('update').value = selected;
    el('revisions').hidden = revisions.length < 2;
    renderArchive();
  }
  function renderArchive() {
    const grid = el('archive-grid'); grid.replaceChildren();
    const season = Number(el('season').value), weeks = seasonWeeks(season);
    el('archive').hidden = !el('season').value;
    el('archive-title').textContent = `${season} season · ${weeks.filter(w => w.row).length} of ${weeks.length} weeks available`;
    el('archive-status').textContent = index.backfill?.status === 'failed'
      ? 'Historical fitting stopped on a failed check. Completed weeks remain available; missing weeks are not estimated or filled in.'
      : index.backfill?.status === 'pending' ? 'Historical reconstruction is in progress. Completed weeks become available as they pass the model checks.'
      : 'Select a week to explore the rankings and posterior using games played through that cutoff.';
    grid.className = 'cfb-week-grid';
    for (const {week, row} of weeks) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = `Week ${week}`; button.disabled = !row;
      const small = document.createElement('small'); small.textContent = row ? date(row.data_cutoff) : 'Awaiting fit'; button.append(small);
      if (row) button.addEventListener('click', () => select(row.id));
      if (el('week').value === String(week)) button.setAttribute('aria-current', 'true');
      grid.append(button);
    }
  }
  function notice() {
    const attempt = index.last_attempt;
    const sameSeason = attempt && current && attempt.season === current.season;
    el('notice').hidden = !(sameSeason && attempt.status === 'failed');
    if (!el('notice').hidden) el('notice').textContent =
      `The update attempted ${date(attempt.at)} did not finish. The last successful rankings are shown below.`;
  }
  const thresholdControls = {protect: 'merit_protection', direct: 'head_to_head', common: 'common_opponents'};
  const percent = value => `${(value * 100).toFixed(2)}%`;
  const ruleNames = {merit_protection: 'Merit protection', undefeated_p4: 'Undefeated Power Four protection',
    head_to_head: 'Head-to-head', common_opponents: 'Common opponents'};
  const teamName = id => current?.teams.find(t => t.id === id)?.name || String(id);
  function settings() {
    return {version: 'margin-of-merit-order-v4',
      ...Object.fromEntries(Object.entries(thresholdControls).map(([key, field]) => [field, Number(el(key).value) / 100])),
      equal_records_only: el('equal').checked, undefeated_p4_protection: el('p4').checked};
  }
  function ruleSentences() {
    for (const key of Object.keys(thresholdControls)) el(`${key}-value`).textContent = `${el(key).value}%`;
    el('protect-rule').textContent = `If the model gives one team more than a ${el('protect').value}% chance of having higher merit, lock that team ahead of the other.`;
    el('direct-rule').textContent = `If two eligible teams played, put the winner above the loser unless the model gives the loser more than a ${el('direct').value}% chance of higher merit. Any conflict preventing that ordering is shown below.`;
    el('common-rule').textContent = `If one eligible team did at least as well against every shared opponent and better against at least one, put it above the other unless opposing merit confidence exceeds ${el('common').value}%. Only applies if these teams never played each other.`;
  }
  function comparisonLabel() {
    el('rank-label').textContent = customPolicy ? 'Your rules' : 'Official';
    el('change-label').textContent = current.week > 0 ? `Week ${current.week - 1} → ${current.week}` : 'First week';
    el('comparison').textContent = customComparisonUnavailable || comparisonUnavailable ||
      `Weekly change compares week ${previous.week} with week ${current.week}. ↑ means a higher rank; ↓ means a lower rank; 0 means unchanged. ${customPolicy ? 'Both weeks use your selected rules.' : 'Both weeks use the official rules.'}`;
  }
  function setOfficialPolicy() {
    cancelAnimationFrame(policyFrame);
    policyError = null; customPolicy = false; viewTeams = current.teams; policyResult = null;
    previousRanks = new Map((previous?.teams || []).map(t => [t.id, t.rank]));
    customComparisonUnavailable = '';
    const supported = current.specification?.version === 'margin-of-merit-order-v4' &&
      current.policy_inputs?.schema === 'margin-of-merit-policy-input-v4' && window.CFBPolicy;
    el('policy').hidden = !supported; el('explanations').hidden = !supported;
    el('policy-error').hidden = true;
    if (supported) {
      for (const [key, field] of Object.entries(thresholdControls)) el(key).value = Math.round(current.specification[field] * 100);
      el('equal').checked = current.specification.equal_records_only;
      el('p4').checked = current.specification.undefeated_p4_protection;
      policyResult = current;
      const active = current.teams.filter(t => t.rank != null).sort((a,b) => a.name.localeCompare(b.name));
      el('team-a').replaceChildren(...active.map(t => option(t.id, t.name)));
      el('team-b').replaceChildren(option('', 'All comparisons'), ...active.map(t => option(t.id, t.name)));
      if (current.order.length) el('team-a').value = String(current.order[0]);
      el('mode').textContent = 'Official rankings';
      ruleSentences(); renderAudit();
    } else {
      el('mode').textContent = 'Saved official rankings. This older result does not include the information needed to adjust its ranking rules.';
    }
    comparisonLabel();
  }
  function applyPolicy() {
    if (!current?.policy_inputs || el('policy').hidden) return;
    ruleSentences();
    const selected = settings();
    try {
      const isOfficial = Object.keys(selected).every(key => selected[key] === current.specification[key]);
      const result = isOfficial ? current : window.CFBPolicy.run(current.policy_inputs, selected);
      const rank = new Map(result.order.map((id, k) => [id, k + 1]));
      viewTeams = current.teams.map(t => ({...t, rank: rank.get(t.id) ?? null}));
      policyResult = result; customPolicy = !isOfficial; policyError = null;
      el('policy-error').hidden = true;
      const changed = current.teams.filter(t => t.rank !== rank.get(t.id) && t.rank != null).length;
      el('mode').textContent = isOfficial ? 'Official rankings'
        : `Your rules · ${changed} team${changed === 1 ? '' : 's'} changed position from the official ranking. Saved estimates are unchanged.`;
    } catch (error) {
      // An inconsistent graph has no valid custom order. Label the fallback,
      // keep the selected controls, and expose the failing chain for inspection.
      policyError = error; customPolicy = false; viewTeams = current.teams;
      policyResult = {specification: selected, audit: error.audit || []};
      el('policy-error').hidden = false;
      el('policy-error').textContent = `${error.message} No ranking was created for these settings. The table shows the official rankings; adjust a control or use Official defaults.`;
      el('mode').textContent = 'Settings conflict — official rankings shown';
    }
    previousRanks = new Map((previous?.teams || []).map(t => [t.id, t.rank]));
    customComparisonUnavailable = '';
    if (customPolicy && previous) {
      try {
        const priorOrder = window.CFBPolicy.run(previous.policy_inputs, selected).order;
        previousRanks = new Map(priorOrder.map((id, k) => [id, k + 1]));
      } catch (_) {
        previousRanks.clear();
        customComparisonUnavailable = 'Weekly change is unavailable: these rules could not produce a valid ranking for the previous week. The selected week remains available.';
      }
    }
    comparisonLabel(); render(); renderAudit();
  }
  function paragraph(parent, text) {
    const p = document.createElement('p'); p.textContent = text; parent.append(p); return p;
  }
  function decisionNode(row) {
    const details = document.createElement('details'), summary = document.createElement('summary');
    const state = row.status === 'blocked_by_threshold' ? 'Threshold not met'
      : row.status === 'blocked_by_conflict' ? 'Blocked by conflicting requirement'
      : row.status === 'overridden_by_p4' ? 'Merit protection overridden by the separate P4 policy'
      : row.type === 'head_to_head' ? 'Direct result required'
      : row.type === 'common_opponents' ? 'Common result required' : 'Protected';
    summary.textContent = `${state}: ${teamName(row.winner_id)} ahead of ${teamName(row.loser_id)}`;
    details.append(summary);
    paragraph(details, `${ruleNames[row.type]}. Probability that ${teamName(row.loser_id)} has higher earned merit: ${percent(row.p_loser_higher_merit)}.${row.threshold != null ? ` Selected threshold: ${percent(row.threshold)}.` : ''}`);
    if (row.direct_record) paragraph(details, `Direct series: ${row.direct_record[0]}–${row.direct_record[1]} for ${teamName(row.winner_id)}. Common opponents are not considered for this pair.`);
    if (row.shared_results) paragraph(details, row.shared_results.map(r =>
      `Against ${teamName(r.opponent_id)}: ${teamName(row.winner_id)} ${r.winner_wins}/${r.winner_games} wins; ${teamName(row.loser_id)} ${r.loser_wins}/${r.loser_games} wins.`).join(' '));
    if (row.conflict_path) {
      paragraph(details, `Blocking chain: ${row.conflict_path.map(teamName).join(' → ')}. Adding the requested reverse ordering would close a cycle.`);
      const list = document.createElement('ul');
      const ids = current.policy_inputs.teams.map(t => t.id), p = current.policy_inputs.probabilities;
      for (const edge of row.conflict_requirements) {
        const item = document.createElement('li');
        const probability = p[ids.indexOf(edge.winner_id)][ids.indexOf(edge.loser_id)];
        item.textContent = `${teamName(edge.winner_id)} → ${teamName(edge.loser_id)}: ${ruleNames[edge.type]}; ${percent(probability)} probability of higher merit.`;
        list.append(item);
      }
      details.append(list);
    }
    if (row.winner_rank != null) paragraph(details, `Result: ${teamName(row.winner_id)} #${row.winner_rank}; ${teamName(row.loser_id)} #${row.loser_rank}. Raw merit ranks: #${row.winner_raw_rank} and #${row.loser_raw_rank}.`);
    return details;
  }
  function renderAudit() {
    if (!policyResult || !el('explanations').open) return;
    const a = Number(el('team-a').value), b = el('team-b').value ? Number(el('team-b').value) : null;
    const summary = el('pair-summary'); summary.replaceChildren();
    const audit = policyResult.audit || [];
    if (policyError) paragraph(summary, 'These settings are contradictory. Decisions below are the partial audit up to the conflict; the table remains the official ranking.');
    for (const id of [a, b].filter((id, k, list) => id != null && list.indexOf(id) === k)) {
      const original = current.teams.find(t => t.id === id), shown = viewTeams.find(t => t.id === id);
      if (original) paragraph(summary, `${original.name}: ${original.wins_fbs}–${original.losses_fbs} FBS record. Official #${original.rank}; shown #${shown.rank}; raw merit #${original.raw_merit_rank}.`);
    }
    const relevant = audit.filter(r => b == null ? r.winner_id === a || r.loser_id === a
      : (r.winner_id === a && r.loser_id === b) || (r.winner_id === b && r.loser_id === a));
    if (b != null && a !== b) {
      const ids = current.policy_inputs.teams.map(t => t.id);
      paragraph(summary, `Probability that ${teamName(a)} has higher earned merit than ${teamName(b)}: ${percent(current.policy_inputs.probabilities[ids.indexOf(a)][ids.indexOf(b)])}. This is not the probability of winning a future game.`);
      const direct = current.policy_inputs.games.filter(g => (g.home_id === a && g.away_id === b) || (g.home_id === b && g.away_id === a));
      if (direct.length) paragraph(summary, `${direct.length} direct game${direct.length === 1 ? '' : 's'} played. Common-opponent evidence is excluded, even for a split series or a blocked direct rule.`);
      const ta = current.teams.find(t => t.id === a), tb = current.teams.find(t => t.id === b);
      if (policyResult.specification.equal_records_only && (ta.wins_fbs !== tb.wins_fbs || ta.losses_fbs !== tb.losses_fbs)) {
        paragraph(summary, 'Different FBS records: the selected equal-record rule excludes secondary comparisons for this pair. Merit and P4 protection still apply.');
      }
    }
    el('decisions').replaceChildren(...relevant.map(decisionNode));
    if (!relevant.length) paragraph(el('decisions'), a === b ? 'Choose a different second team.'
      : 'Not directly constrained: no rule establishes an ordering for this pair. Stable merit-first completion respects any requirements involving other teams.');
    const rawRanks = new Map(current.teams.map(t => [t.id, t.raw_merit_rank]));
    const low = Math.min(rawRanks.get(a), rawRanks.get(b)), high = Math.max(rawRanks.get(a), rawRanks.get(b));
    const between = b != null && a !== b ? audit.filter(r => ['merit_protection', 'undefeated_p4'].includes(r.type) &&
      ['accepted', 'already_satisfied'].includes(r.status) && [r.winner_id, r.loser_id].every(id => rawRanks.get(id) >= low && rawRanks.get(id) <= high)) : [];
    el('intermediaries').hidden = !between.length;
    el('intermediary-list').replaceChildren(...(el('intermediaries').open ? between.map(decisionNode) : []));
    el('audit-download').disabled = Boolean(policyError);
  }
  function explainTeam(id) {
    el('team-a').value = String(id); el('team-b').value = '';
    el('explanations').open = true; renderAudit();
    el('explanations').scrollIntoView({behavior: 'smooth', block: 'start'});
    el('team-a').focus({preventScroll: true});
  }
  function render() {
    if (!current) return;
    const query = el('search').value.trim().toLocaleLowerCase();
    const conference = el('conference').value;
    const rows = (viewTeams || current.teams).filter(r => (!query || r.name.toLocaleLowerCase().includes(query)) &&
      (!conference || r.conference === conference) &&
      (query || conference || el('limit').value === 'all' || (r.rank != null && r.rank <= 25)));
    rows.sort((a, b) => {
      if (a[sortKey] == null) return b[sortKey] == null ? a.name.localeCompare(b.name) : 1;
      if (b[sortKey] == null) return -1;
      const compare = sortKey === 'name' ? a.name.localeCompare(b.name) : a[sortKey] - b[sortKey];
      return direction * compare || (a.rank ?? Infinity) - (b.rank ?? Infinity) || a.name.localeCompare(b.name);
    });
    const officialRanks = new Map(current.teams.map(r => [r.id, r.rank]));
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
      cell(r.rank ?? '—', customPolicy && r.rank != null ? `Official ${officialRanks.get(r.id)}` : null);
      const teamCell = cell(r.name, r.conference || 'Independent', true);
      const explore = document.createElement('button'); explore.type='button';explore.className='cfb-explain';explore.textContent='Explore posterior';
      explore.setAttribute('aria-label',`Explore ${r.name} posterior`);explore.addEventListener('click',()=>explorer.team(r.id));teamCell.append(explore);
      if (policyResult && r.rank != null) {
        const button = document.createElement('button'); button.type = 'button';
        button.className = 'cfb-explain'; button.textContent = 'Explain rank';
        button.setAttribute('aria-label', `Explain ${r.name} ranking`);
        button.addEventListener('click', () => explainTeam(r.id)); teamCell.append(button);
      }
      cell(`${r.wins_fbs}–${r.losses_fbs}`);
      cell(r.rank == null ? '—' : fixed(r.merit_mean), r.rank == null ? 'No eligible games' : interval(r.merit_lo90, r.merit_hi90, 2));
      cell(Number.isFinite(r.sos_mean) ? `${(100 * r.sos_mean).toFixed(1)}%` : '—',
        Number.isFinite(r.sos_lo90) && Number.isFinite(r.sos_hi90)
          ? `${(100 * r.sos_lo90).toFixed(1)}–${(100 * r.sos_hi90).toFixed(1)}%` : null);
      cell(r.raw_merit_rank ?? '—', interval(r.raw_rank_lo90, r.raw_rank_hi90));
      cell(Number.isFinite(r.p_raw_merit_top10) ? `${(r.p_raw_merit_top10 * 100).toFixed(1)}%` : '—');
      const oldRank = previousRanks.get(r.id);
      const unavailable = customComparisonUnavailable || comparisonUnavailable;
      const change = !unavailable && r.rank != null && oldRank != null ? oldRank - r.rank : null;
      const label = unavailable ? 'N/A' : r.rank == null ? 'Unranked' : oldRank == null ? 'New'
        : change > 0 ? `↑ ${change}` : change < 0 ? `↓ ${-change}` : '0';
      const description = unavailable || (r.rank == null ? 'No eligible games yet' : oldRank == null ? 'No rank last week'
        : change === 0 ? 'Unchanged' : `${change > 0 ? 'Up' : 'Down'} ${Math.abs(change)} places`);
      const movement = cell(label, change === 0 ? 'Unchanged' : label === 'New' ? 'First ranking' : null);
      movement.title = description;
      movement.setAttribute('aria-label', description);
      fragment.append(tr);
    }
    if (!rows.length) {
      const tr = document.createElement('tr'), td = document.createElement('td');
      td.colSpan = 8; td.textContent = 'No matching teams. Try another search or conference.'; tr.append(td); fragment.append(tr);
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
      const older = index.snapshots.find(r => r.season === row.season && r.week === row.week - 1 && r.data_cutoff < row.data_cutoff);
      let prior = null;
      if (older) { try { prior = await read(older); } catch (_) { /* Rankings remain usable without movement. */ } }
      if (sequence !== loadNumber) return;
      current = result;
      previous = prior?.policy_sha256 === current.policy_sha256 ? prior : null;
      comparisonUnavailable = previous ? '' : row.week === 0 ? 'This is the first week; there is no previous-week ranking.'
        : !older ? `Week ${row.week - 1} has no saved ranking yet. Weekly change will appear when that fit is available.`
        : !prior ? `Week ${row.week - 1} could not be loaded. Reload to try the weekly comparison again.`
        : 'The previous week used different ranking rules, so weekly change is unavailable for this saved version.';
      setOfficialPolicy();
      el('label').textContent = `${row.season} season / ${id === index.latest ? 'Latest update' : 'Saved update'}`;
      document.getElementById('cfb-title').textContent = `Week ${row.week} rankings`;
      el('timing').textContent = `${current.games} completed FBS–FBS games through ${date(current.data_cutoff)}. ${current.kind==='reconstruction'?'Reconstructed using only results through this week.':'Unplayed games are not included.'}`;
      el('caption').textContent = `${row.season} Margin of Merit, week ${row.week}, through ${date(current.data_cutoff)}`;
      const chosenConference = el('conference').value;
      el('conference').replaceChildren(option('', 'All conferences'), ...[...new Set(current.teams.map(r => r.conference).filter(Boolean))].sort().map(c => option(c, c)));
      if ([...el('conference').options].some(o => o.value === chosenConference)) el('conference').value = chosenConference;
      const address = new URL(location.href);
      address.searchParams.set('snapshot', id);
      address.searchParams.set('season', row.season); address.searchParams.set('week', row.week); address.hash = '';
      el('permalink').href = address.href;
      el('csv').href = url(row.csv); el('csv').hidden = false;
      el('json').href = url(row.json);
      if (writeURL) history.replaceState(null, '', address);
      notice(); render(); el('results').hidden = false; explorer.show(current,index); renderArchive();
      el('status').textContent = `Loaded ${row.season} week ${row.week}.`;
      el('status').hidden = true;
    } catch (_) {
      if (sequence === loadNumber) el('status').textContent = 'This week’s rankings could not be loaded. Choose another week or reload the page.';
    } finally { if (sequence === loadNumber) root.removeAttribute('aria-busy'); }
  }
  async function browseSeason(season, week = null, writeURL = true) {
    populateUpdates(season, null, week);
    if (el('update').value) return select(el('update').value, writeURL);
    // A season or linked week awaiting fitting must not retain another week's results.
    loadNumber++; current = null; previous = null;
    root.removeAttribute('aria-busy');
    el('results').hidden = true; el('csv').hidden = true; el('notice').hidden = true;
    el('label').textContent = `${season} season`;
    document.getElementById('cfb-title').textContent = week == null ? 'Weekly rankings awaiting fits' : `Week ${week} rankings unavailable`;
    el('timing').textContent = 'Completed weekly fits will appear here as they become available.';
    el('status').hidden = false;
    el('status').textContent = week == null
      ? `No checked rankings are published for ${season} yet.`
      : `No checked rankings are published for ${season} week ${week}. Choose an available week below.`;
    if (writeURL) {
      const address = new URL(location.href);
      address.searchParams.delete('snapshot'); address.searchParams.set('season', season);
      if (week == null) address.searchParams.delete('week'); else address.searchParams.set('week', week);
      history.replaceState(null, '', address);
    }
  }
  el('season').addEventListener('change', () => browseSeason(el('season').value));
  el('week').addEventListener('change', () => browseSeason(el('season').value, Number(el('week').value)));
  el('update').addEventListener('change', () => select(el('update').value));
  function latest() {
    if (!index?.latest) return;
    el('search').value = ''; el('conference').value = '';
    const address = new URL(location.href);
    address.searchParams.delete('snapshot'); address.searchParams.delete('season'); address.searchParams.delete('week');
    history.replaceState(null, '', address);
    select(index.latest, false);
  }
  el('latest').addEventListener('click', latest);
  el('current').addEventListener('click', latest);
  for (const key of [...Object.keys(thresholdControls), 'equal', 'p4']) el(key).addEventListener('input', () => {
    ruleSentences(); cancelAnimationFrame(policyFrame); policyFrame = requestAnimationFrame(applyPolicy);
  });
  el('reset').addEventListener('click', () => { setOfficialPolicy(); render(); });
  for (const key of ['team-a', 'team-b']) el(key).addEventListener('change', renderAudit);
  el('explanations').addEventListener('toggle', renderAudit);
  el('intermediaries').addEventListener('toggle', () => { if (el('intermediaries').open) renderAudit(); });
  el('audit-download').addEventListener('click', () => {
    if (!policyResult || policyError) return;
    const blob = new Blob([JSON.stringify({snapshot: el('update').value, official: !customPolicy,
      specification: policyResult.specification, order: policyResult.order,
      teams: current.teams.map(t => ({id: t.id, name: t.name, wins_fbs: t.wins_fbs, losses_fbs: t.losses_fbs,
        official_rank: t.rank, raw_merit_rank: t.raw_merit_rank})), audit: policyResult.audit}, null, 2) + '\n'], {type: 'application/json'});
    const address = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = address; link.download = `margin-of-merit-${el('update').value}-${customPolicy ? 'reader' : 'official'}-audit.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(address), 1000);
  });
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
      const seasons = [...new Set([...index.snapshots.map(r => r.season), ...(index.archive || []).map(s => s.season)])].sort((a,b) => b-a);
      if (!seasons.length) {
        el('status').textContent = index.last_attempt?.status === 'failed'
          ? 'The first ranking update did not finish. No rankings have been published yet.'
          : 'No rankings have been published yet.';
        return;
      }
      el('controls').hidden = false;
      el('season').replaceChildren(...seasons.map(s => option(s, `${s}${index.snapshots.some(r=>r.season===s)?'':' · awaiting fits'}`)));
      el('latest').disabled = !index.latest;
      const query = new URLSearchParams(location.search);
      const requested = index.snapshots.find(r => r.id === query.get('snapshot'));
      if (requested) await select(requested.id, false);
      else if (seasons.includes(Number(query.get('season')))) {
        const week = /^\d+$/.test(query.get('week') || '') ? Number(query.get('week')) : null;
        await browseSeason(Number(query.get('season')), week, false);
      } else if (index.latest) await select(index.latest, false);
      else await browseSeason(seasons[0], null, false);
    } catch (_) { el('status').textContent = 'The ranking archive could not be loaded. Please reload the page in a moment.'; }
  }
  start();
})();
