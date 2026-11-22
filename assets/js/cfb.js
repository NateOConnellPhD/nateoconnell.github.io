(() => {
  'use strict';
  const root = document.querySelector('[data-cfb]');
  if (!root) return;
  const el = key => root.querySelector(`[data-cfb-${key}]`);
  const reference = window.CFBReference;
  el('reference').value = String(reference.choice(new URLSearchParams(location.search).get('reference')));
  const savedLabel = () => current?.reference_rank === reference.defaultRank ? 'Official rankings' : `${reference.label(current?.reference_rank)}-reference rankings`;
  const base = new URL('./', new URL(root.dataset.index, location.href));
  const snapshots = new Map();
  const pollSeasons = new Map();
  let pollData = null, activePoll = null, pollLoadNumber = 0;
  const explorer = window.CFBExplorer(root, {fetchJSON, url, select});
  let index, current, previous, loadNumber = 0;
  let previousRanks = new Map(), comparisonUnavailable = '', customComparisonUnavailable = '';
  let viewTeams, policyResult, customPolicy = false, policyError = null, policyFrame = 0, policyGeneration = 0;
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
  async function read(row, rank) {
    const descriptor = reference.descriptor(row, rank), key = `${row.id}:${rank}`;
    if (!snapshots.has(key)) {
      const value = await fetchJSON(url(descriptor.json));
      if (!reference.valid(value, row, rank)) {
        throw new Error('Unpublished or invalid ranking');
      }
      snapshots.set(key, value);
    }
    return snapshots.get(key);
  }
  function option(value, label) {
    const node = document.createElement('option');
    node.value = value; node.textContent = label; return node;
  }
  function pollName() { return el('poll').value === 'cfp' ? 'CFP' : 'AP'; }
  function renderPollEdition() {
    if (!current) return;
    activePoll = pollData?.editions.find(p => p.poll === el('poll').value && p.id === el('poll-edition').value) || null;
    const expected = current.week + 1;
    const shown = activePoll ? `${activePoll.season_type === 'postseason' ? 'postseason' : 'regular-season'} week ${activePoll.week}${activePoll.final ? ' (final)' : ''}` : `regular-season week ${expected}`;
    el('poll-note').textContent = `${pollName()} ${shown}: ${activePoll ? 'saved' : 'no saved edition available'}. Margin of Merit uses results through week ${current.week}. Poll weeks use the provider’s labels; exact release dates are not supplied. The following poll week is suggested, and you can select another edition. Differences compare the rank shown here with the poll: positive means higher here. NR means outside that poll’s Top 25; N/A means the edition is unavailable. Saved ${date(pollData.retrieved_at)}.`;
    render();
  }
  async function loadPolls() {
    const sequence = ++pollLoadNumber, snapshot = current, chosen = el('poll').value;
    pollData = null; activePoll = null;
    const enabled = Boolean(chosen);
    if (!enabled && ['poll_rank', 'poll_gap'].includes(sortKey)) sortBy('rank', 1);
    el('poll-edition-control').hidden = !enabled;
    el('poll-note').hidden = !enabled;
    el('poll-rank-heading').hidden = !enabled; el('poll-gap-heading').hidden = !enabled;
    el('poll-rank-label').textContent = `${pollName()} rank`;
    el('poll-gap-label').textContent = `Vs. ${pollName()}`;
    if (el('limit').options[0]) el('limit').options[0].textContent = enabled ? 'Either Top 25' : 'Top 25';
    if (!enabled || !snapshot) { render(); return; }
    el('poll-edition').replaceChildren(option('', 'Loading poll editions…'));
    el('poll-edition').disabled = true;
    el('poll-note').textContent = 'Loading saved poll editions…'; render();
    try {
      if (!pollSeasons.has(snapshot.season)) {
        const pending = fetchJSON(url(`seasons/${snapshot.season}/polls.json`), 'no-cache').then(data => {
          if (data.schema !== 'margin-of-merit-polls-v1' || data.season !== snapshot.season || !Array.isArray(data.editions)) throw new Error('Invalid poll archive');
          return data;
        });
        pollSeasons.set(snapshot.season, pending);
        pending.catch(() => pollSeasons.delete(snapshot.season));
      }
      const data = await pollSeasons.get(snapshot.season);
      if (sequence !== pollLoadNumber || snapshot !== current) return;
      pollData = data;
      const editions = data.editions.filter(p => p.poll === chosen);
      // A provider poll week is not an observed game cutoff. Keep the exact
      // edition visible and adjustable instead of claiming date alignment.
      const suggested = editions.filter(p => p.season_type === 'regular' && p.week === current.week + 1);
      const preferred = suggested.find(p => p.final) || suggested[0];
      el('poll-edition').replaceChildren(...(preferred ? [] : [option('', `Week ${current.week + 1} · not available`)]),
        ...editions.map(p => option(p.id, `${p.season_type === 'postseason' ? 'Postseason week' : 'Week'} ${p.week}${p.final ? ' · final' : ''}`)));
      el('poll-edition').value = preferred?.id || '';
      el('poll-edition').disabled = !editions.length;
      renderPollEdition();
    } catch (_) {
      if (sequence !== pollLoadNumber || snapshot !== current) return;
      el('poll-edition').replaceChildren(option('', 'Poll archive unavailable'));
      el('poll-note').textContent = `Saved ${pollName()} polls for ${snapshot.season} could not be loaded. Rankings remain available. The poll archive appears after its first successful scheduled update; reload to try again.`;
      render();
    }
  }
  function seasonWeeks(season) {
    const rows = index.snapshots.filter(r => r.season === Number(season));
    const expected = (index.archive || []).find(s => s.season === Number(season))?.weeks || [];
    return [...new Set([...rows.map(r => r.week), ...expected.map(w => w.week)])].sort((a, b) => a - b)
      .map(week => ({week, row: rows.find(r => r.week === week), status: expected.find(w => w.week === week)?.status}));
  }
  function populateUpdates(season, selected, requestedWeek = null) {
    el('season').value = String(season);
    const rows = index.snapshots.filter(r => r.season === Number(season));
    const weeks = seasonWeeks(season);
    const week = rows.find(r => r.id === selected)?.week ?? requestedWeek ?? rows[0]?.week ?? weeks[weeks.length - 1]?.week;
    el('week').replaceChildren(...weeks.map(({week, row, status}) => {
      const node = option(week, `Week ${week} · ${row ? date(row.data_cutoff) : status === 'needs_attention' ? 'sampling checks failed' : 'awaiting fit'}`);
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
    const awaitingData = index.archive?.find(s => s.season === season)?.status === 'awaiting_data';
    el('archive').hidden = !el('season').value;
    el('archive-title').textContent = awaitingData ? `${season} season · awaiting saved game data`
      : `${season} season · ${weeks.filter(w => w.row).length} of ${weeks.length} weeks available`;
    el('archive-status').textContent = ['failed', 'blocked'].includes(index.backfill?.status)
      ? 'Historical updates are paused after an unsuccessful update. Completed weeks remain available.'
      : index.backfill?.status === 'needs_attention' ? 'The archive pass has finished. Some weeks failed sampling checks and need review; their rankings have not been published.'
      : index.backfill?.status === 'pending' ? 'Missing weeks are queued, starting with the latest season and working backward. Weeks that fail sampling checks are marked below while other weeks continue.'
      : 'Select a week to explore the rankings and posterior using games played through that cutoff.';
    grid.className = 'cfb-week-grid';
    for (const {week, row, status} of weeks) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = `Week ${week}`; button.disabled = !row;
      const small = document.createElement('small'); small.textContent = row ? date(row.data_cutoff) : status === 'needs_attention' ? 'Sampling checks failed' : 'Awaiting fit'; button.append(small);
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
  const ruleNames = {merit_protection: 'Merit protection',
    head_to_head: 'Head-to-head', common_opponents: 'Common opponents'};
  const teamName = id => current?.teams.find(t => t.id === id)?.name || current?.policy_inputs?.opponents?.find(t => t.id === id)?.name || String(id);
  const isV5 = () => current?.specification?.version === 'margin-of-merit-order-2026-11-21-no-p4';
  const wins = team => team.wins;
  const losses = team => team.losses;
  function settings() {
    return {version: current.specification.version,
      proximity: Number(el('proximity').value),
      ...Object.fromEntries(Object.entries(thresholdControls).map(([key, field]) => [field, Number(el(key).value) / 100])),
      equal_records_only: el('equal').checked};
  }
  function ruleSentences() {
    for (const key of Object.keys(thresholdControls)) el(`${key}-value`).textContent = `${el(key).value}%`;
    const places=el('proximity').value;
    el('proximity-value').textContent = `±${places} places`;
    el('protect-rule').textContent = `At least ${el('protect').value}% probability of greater merit creates a merit preference. Qualifying direct and common-opponent results take priority when they conflict.`;
    el('direct-rule').textContent = `A decisive direct result qualifies if opposing merit probability is below ${el('direct').value}% OR the teams are within ${places} places in the current order. Nearby comparisons are rechecked after each reorder. Any direct meeting rules out common-opponent fallback.`;
    el('common-rule').textContent = `For teams that never met, dominance against every shared FBS opponent qualifies if opposing merit probability is below ${el('common').value}% OR current ranks are within ${places} places.`;
    el('record-rule').textContent = 'Compare actual results only when overall wins and losses match, including FCS games.';
    el('boundary-rule').textContent = 'Merit protection includes equality at its threshold; probability eligibility uses strictly below. Proximity is a separate OR condition. Conflicts are resolved globally: direct results, common opponents, merit, then the fewest changes to the raw order.';
  }
  function comparisonLabel() {
    el('rank-label').textContent = customPolicy ? 'Your rules' : current.reference_rank === reference.defaultRank ? 'Official' : 'Selected reference';
    el('change-label').textContent = current.week > 0 ? `Week ${current.week - 1} → ${current.week}` : 'First week';
    el('comparison').textContent = customComparisonUnavailable || comparisonUnavailable ||
      `Weekly change compares week ${previous.week} with week ${current.week}, using the ${reference.label(current.reference_rank)} reference in both weeks. ↑ means a higher rank; ↓ means a lower rank; 0 means unchanged. ${customPolicy ? 'Both weeks use your selected rules.' : 'Both weeks use the default ordering rules.'}`;
  }
  function setOfficialPolicy() {
    clearTimeout(policyFrame);
    policyGeneration++; window.CFBPolicy?.cancel();
    policyError = null; customPolicy = false; viewTeams = current.teams; policyResult = null;
    previousRanks = new Map((previous?.teams || []).map(t => [t.id, t.rank]));
    customComparisonUnavailable = '';
    const supported = isV5() &&
      current.policy_inputs?.schema === 'margin-of-merit-policy-input-v5' && window.CFBPolicy;
    el('policy').hidden = !supported; el('explanations').hidden = !supported;
    el('rules-unavailable').hidden = Boolean(supported);
    el('policy-error').hidden = true;
    el('record-label').textContent = 'Overall W–L';
    el('record-label').title = 'Overall wins and losses, including FCS games';
    if (supported) {
      for (const [key, field] of Object.entries(thresholdControls)) el(key).value = Math.round(current.specification[field] * 100);
      el('equal').checked = current.specification.equal_records_only;
      el('proximity-control').hidden = false;
      el('proximity').value = current.specification.proximity ?? 2;
      el('reset').textContent = 'Reset ordering rules';
      policyResult = current;
      const active = current.teams.filter(t => t.rank != null).sort((a,b) => a.name.localeCompare(b.name));
      el('team-a').replaceChildren(...active.map(t => option(t.id, t.name)));
      if (current.order.length) el('team-a').value = String(current.order[0]);
      chooseOpponent();
      el('mode').textContent = savedLabel();
      ruleSentences(); renderAudit();
    } else {
      el('mode').textContent = 'This week is awaiting a refit under the current model and rules.';
    }
    comparisonLabel();
  }
  async function applyPolicy() {
    if (!current?.policy_inputs || el('policy').hidden) return;
    ruleSentences();
    const selected = settings(), snapshot=current, generation=++policyGeneration;
    window.CFBPolicy.cancel();
    el('mode').textContent = 'Calculating your selected rules… Saved rankings for this reference are shown while this runs.';
    previousRanks = new Map((previous?.teams || []).map(t => [t.id, t.rank]));
    customComparisonUnavailable = '';
    policyResult=null; viewTeams=current.teams; customPolicy=false; comparisonLabel(); render(); el('decisions').replaceChildren(); el('pair-summary').replaceChildren(); el('game-contributions').replaceChildren();
    el('audit-download').disabled=true; el('policy-error').hidden=true;
    try {
      const isOfficial = Object.keys(selected).every(key => selected[key] === current.specification[key]);
      const result = isOfficial ? current : await window.CFBPolicy.run(current.policy_inputs, selected);
      if (generation !== policyGeneration || snapshot !== current) return;
      const rank = new Map(result.order.map((id, k) => [id, k + 1]));
      viewTeams = current.teams.map(t => ({...t, rank: rank.get(t.id) ?? null}));
      policyResult = result; customPolicy = !isOfficial; policyError = null;
      el('policy-error').hidden = true;
      const changed = current.teams.filter(t => t.rank !== rank.get(t.id) && t.rank != null).length;
      el('mode').textContent = isOfficial ? savedLabel()
        : `Your rules · ${reference.label(current.reference_rank)} reference · ${changed} team${changed === 1 ? '' : 's'} changed position from the saved ranking. Saved estimates are unchanged.`;
    } catch (error) {
      if (error.name === 'AbortError' || generation !== policyGeneration || snapshot !== current) return;
      // Failed or unproven optimization must not display a custom ranking.
      policyError = error; customPolicy = false; viewTeams = current.teams;
      policyResult = {specification: selected, audit: error.audit || []};
      el('policy-error').hidden = false;
      el('policy-error').textContent = `${error.message} No ranking was created for these settings. The table shows the saved rankings for this reference; adjust a control or use Reset ordering rules.`;
      el('mode').textContent = 'Calculation unavailable — saved rankings shown';
    }
    previousRanks = new Map((previous?.teams || []).map(t => [t.id, t.rank]));
    customComparisonUnavailable = '';
    if (customPolicy && previous) {
      try {
        const priorOrder = (await window.CFBPolicy.run(previous.policy_inputs, selected)).order;
        if (generation !== policyGeneration || snapshot !== current) return;
        previousRanks = new Map(priorOrder.map((id, k) => [id, k + 1]));
      } catch (_) {
        if (generation !== policyGeneration || snapshot !== current) return;
        previousRanks.clear();
        customComparisonUnavailable = 'Weekly change is unavailable: these rules could not produce a valid ranking for the previous week. The selected week remains available.';
      }
    }
    comparisonLabel(); render(); renderAudit();
  }
  function paragraph(parent, text) {
    const p = document.createElement('p'); p.textContent = text; parent.append(p); return p;
  }
  function chooseOpponent() {
    const active = (viewTeams || current.teams).filter(t => t.rank != null).sort((a, b) => a.rank - b.rank);
    const position = active.findIndex(t => t.id === Number(el('team-a').value));
    const neighbor = active[position - 1] || active[position + 1];
    el('team-b').replaceChildren(...active.filter(t => t.id !== Number(el('team-a').value))
      .sort((a, b) => a.name.localeCompare(b.name)).map(t => option(t.id, t.name)));
    el('team-b').value = neighbor ? String(neighbor.id) : '';
    el('team-b').disabled = !neighbor;
  }
  function decisionNode(row) {
    const details = document.createElement('details'), summary = document.createElement('summary');
    const state = row.status === 'not_eligible' ? 'Neither eligibility route met'
      : row.status === 'overridden_by_global_objective' ? 'Overridden by the global evidence priorities'
      : row.type === 'head_to_head' ? 'Direct result required'
      : row.type === 'common_opponents' ? 'Common result required' : 'Protected';
    summary.textContent = `${state}: ${teamName(row.winner_id)} ahead of ${teamName(row.loser_id)}`;
    details.append(summary);
    if (row.type === 'merit_protection') {
      const ids=current.policy_inputs.teams.map(t=>t.id), p=current.policy_inputs.probabilities;
      paragraph(details, `Merit preference: ${percent(p[ids.indexOf(row.winner_id)][ids.indexOf(row.loser_id)])} probability that ${teamName(row.winner_id)} has greater merit; selected threshold ${percent(row.threshold)}.`);
    } else paragraph(details, `${ruleNames[row.type]}. Probability that ${teamName(row.loser_id)} has higher earned merit: ${percent(row.p_loser_higher_merit)}.${row.threshold != null ? ` Selected threshold: ${percent(row.threshold)}.` : ''}`);
    const routes = {both: 'probability and proximity', probability: 'probability threshold', proximity: 'initial ranking proximity', neither: 'neither condition', posterior_merit: 'merit probability'};
    if (row.admission_iteration) paragraph(details, `Admitted after reorder ${row.admission_iteration}: the teams were #${row.winner_rank_at_admission} and #${row.loser_rank_at_admission}, ${row.rank_gap_at_admission} places apart. This comparison stays admitted in subsequent reorders.`);
    if (row.qualification && !row.admission_iteration) paragraph(details, `Qualifying route: ${routes[row.qualification] || row.qualification}. Raw-rank distance: ${row.raw_rank_gap} places.${row.proximity != null ? ` Selected window: ±${row.proximity}.` : ''}`);
    if (row.game_ids) for (const id of row.game_ids) {
      const game=current.policy_inputs.games.find(g=>g.id===id);
      if (game) paragraph(details, `${teamName(game.home_id)} ${game.home_points} — ${teamName(game.away_id)} ${game.away_points}.`);
    }
    if (row.resolution) paragraph(details, row.resolution);
    if (row.direct_record) paragraph(details, `Direct series: ${row.direct_record[0]}–${row.direct_record[1]} for ${teamName(row.winner_id)}. Common opponents are not considered for this pair.`);
    if (row.shared_results) paragraph(details, row.shared_results.map(r =>
      `Against ${teamName(r.opponent_id)}: ${teamName(row.winner_id)} ${r.winner_wins}/${r.winner_games} wins; ${teamName(row.loser_id)} ${r.loser_wins}/${r.loser_games} wins.`).join(' '));
    if (row.conflict_path?.length) {
      paragraph(details, `Blocking chain: ${row.conflict_path.slice(0, 9).map(teamName).join(' → ')}${row.conflict_path.length > 9 ? ' → …' : ''}. Adding the requested reverse ordering would close a cycle.`);
      const list = document.createElement('ul');
      const ids = current.policy_inputs.teams.map(t => t.id), p = current.policy_inputs.probabilities;
      for (const edge of row.conflict_requirements.slice(0, 8)) {
        const item = document.createElement('li');
        const probability = p[ids.indexOf(edge.winner_id)][ids.indexOf(edge.loser_id)];
        item.textContent = `${teamName(edge.winner_id)} → ${teamName(edge.loser_id)}: ${ruleNames[edge.type]}; ${percent(probability)} probability of higher merit.`;
        list.append(item);
      }
      details.append(list);
      if (row.conflict_requirements.length > 8) paragraph(details, `Showing the first 8 of ${row.conflict_requirements.length} requirements in this chain. The full chain is in the downloadable decision audit.`);
    }
    if (row.winner_rank != null) paragraph(details, `Result: ${teamName(row.winner_id)} #${row.winner_rank}; ${teamName(row.loser_id)} #${row.loser_rank}. Raw merit ranks: #${row.winner_raw_rank} and #${row.loser_raw_rank}.`);
    return details;
  }
  function renderAudit() {
    if (!policyResult || !el('explanations').open) return;
    const a = Number(el('team-a').value), b = el('team-b').value ? Number(el('team-b').value) : null;
    const summary = el('pair-summary'); summary.replaceChildren();
    const audit = policyResult.audit || [];
    if (policyError) paragraph(summary, 'These settings did not produce a verified order. The table shows the saved rankings for this reference.');
    for (const id of [a, b].filter((id, k, list) => id != null && list.indexOf(id) === k)) {
      const original = current.teams.find(t => t.id === id), shown = viewTeams.find(t => t.id === id);
      if (original) paragraph(summary, `${original.name}: ${wins(original)}–${losses(original)} overall record. Saved #${original.rank}; shown #${shown.rank}; raw merit #${original.raw_merit_rank}. Reference: ${reference.label(current.reference_rank)}.`);
    }
    const relevant = audit.filter(r => b != null && a !== b &&
      ((r.winner_id === a && r.loser_id === b) || (r.winner_id === b && r.loser_id === a)));
    if (b != null && a !== b) {
      const ids = current.policy_inputs.teams.map(t => t.id);
      paragraph(summary, `Probability that ${teamName(a)} has higher earned merit than ${teamName(b)}: ${percent(current.policy_inputs.probabilities[ids.indexOf(a)][ids.indexOf(b)])}. This is not the probability of winning a future game.`);
      const direct = current.policy_inputs.games.filter(g => (g.home_id === a && g.away_id === b) || (g.home_id === b && g.away_id === a));
      if (direct.length) paragraph(summary, `${direct.length} direct game${direct.length === 1 ? '' : 's'} played. The common-opponent ordering rule is excluded, even for a split series or a blocked direct rule. Games against shared opponents still contribute to merit.`);
      const ta = current.teams.find(t => t.id === a), tb = current.teams.find(t => t.id === b);
      if (policyResult.specification.equal_records_only && (wins(ta) !== wins(tb) || losses(ta) !== losses(tb))) {
        paragraph(summary, 'Different counted records: the selected equal-record rule excludes head-to-head and common-opponent ordering rules for this pair. Earned merit and merit protection still apply.');
      }
      window.CFBContributions.render(el('game-contributions'), current, a, b, viewTeams);
    } else {
      el('game-contributions').replaceChildren();
    }
    el('decisions').replaceChildren(...relevant.map(decisionNode));
    if (!relevant.length) paragraph(el('decisions'), b == null || a === b ? 'Choose a second team to inspect one matchup.'
      : 'Not directly constrained: no rule establishes an ordering for this pair. The global order also accounts for requirements involving other teams and retains the raw merit order where the objectives allow.');
    el('audit-download').disabled = Boolean(policyError);
  }
  function explainTeam(id, opponent = null) {
    if (!current?.teams.some(t => t.id === id && t.rank != null)) return;
    el('team-a').value = String(id); chooseOpponent();
    if (opponent !== id && current.teams.some(t => t.id === opponent && t.rank != null)) el('team-b').value = String(opponent);
    explorer.tab('rules', true);
    el('explanations').open = true; renderAudit();
    el('explanations').scrollIntoView({behavior: 'smooth', block: 'start'});
    el('team-a').focus({preventScroll: true});
  }
  function render() {
    if (!current) return;
    const query = el('search').value.trim().toLocaleLowerCase();
    const conference = el('conference').value;
    const pollRanks = new Map((activePoll?.ranks || []).map(r => [r.id, r.rank]));
    const rows = (viewTeams || current.teams).map(r => ({...r, poll_rank: pollRanks.get(r.id) ?? null,
      poll_gap: r.rank != null && pollRanks.has(r.id) ? pollRanks.get(r.id) - r.rank : null})).filter(r => (!query || r.name.toLocaleLowerCase().includes(query)) &&
      (!conference || r.conference === conference) &&
      (query || conference || el('limit').value === 'all' || (r.rank != null && r.rank <= 25) || (r.poll_rank != null && r.poll_rank <= 25)));
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
      cell(r.rank ?? '—', customPolicy && r.rank != null ? `Saved ${officialRanks.get(r.id)}` : null);
      const teamCell = cell(r.name, r.conference || 'Independent', true);
      const explore = document.createElement('button'); explore.type='button';explore.className='cfb-explain';explore.textContent='Explore posterior';
      explore.setAttribute('aria-label',`Explore ${r.name} posterior`);explore.addEventListener('click',()=>explorer.team(r.id));teamCell.append(explore);
      if (policyResult && r.rank != null) {
        const button = document.createElement('button'); button.type = 'button';
        button.className = 'cfb-explain'; button.textContent = 'Explain rank';
        button.setAttribute('aria-label', `Explain ${r.name} ranking`);
        button.addEventListener('click', () => explainTeam(r.id)); teamCell.append(button);
      }
      if (el('poll').value) {
        cell(!activePoll ? 'N/A' : r.poll_rank ?? 'NR');
        cell(r.poll_gap == null ? 'N/A' : r.poll_gap > 0 ? `+${r.poll_gap}` : String(r.poll_gap),
          r.poll_gap == null ? null : r.poll_gap === 0 ? 'Same rank' : r.poll_gap > 0 ? 'Higher here' : 'Lower here');
      }
      cell(`${wins(r)}–${losses(r)}`);
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
      td.colSpan = el('poll').value ? 10 : 8; td.textContent = 'No matching teams. Try another search or conference.'; tr.append(td); fragment.append(tr);
    }
    el('rows').replaceChildren(fragment);
    el('count').textContent = `${rows.length} of ${current.teams.length} teams shown.${query || conference ? ' Search and conference filters include all ranks.' : activePoll && el('limit').value !== 'all' ? ' Includes teams in either Top 25.' : ''}`;
  }
  async function select(id, writeURL = true, preserveRules = false) {
    const row = index.snapshots.find(r => r.id === id);
    if (!row) return;
    const sequence = ++loadNumber;
    const rank = reference.choice(el('reference').value);
    const readerSettings = preserveRules && isV5() && !el('policy').hidden ? settings() : null;
    policyGeneration++; clearTimeout(policyFrame); window.CFBPolicy?.cancel();
    pollLoadNumber++; activePoll = null;
    el('status').hidden = false; el('status').textContent = 'Loading saved update…';
    el('results').hidden = true; el('csv').hidden = true;
    root.setAttribute('aria-busy', 'true');
    populateUpdates(row.season, id);
    try {
      const result = await read(row, rank);
      const older = index.snapshots.find(r => r.season === row.season && r.week === row.week - 1 && r.data_cutoff < row.data_cutoff);
      let prior = null;
      if (older) { try { prior = await read(older, rank); } catch (_) { /* Rankings remain usable without movement. */ } }
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
      el('timing').textContent = `${current.scored_games} FBS games counted; ${current.games} Division I games in the model through ${date(current.data_cutoff)}. ${current.kind==='reconstruction'?'Reconstructed using only results through this week.':'Unplayed games are not included.'}`;
      el('caption').textContent = `${row.season} Margin of Merit, week ${row.week}, ${reference.label(rank)} reference, through ${date(current.data_cutoff)}`;
      const chosenConference = el('conference').value;
      el('conference').replaceChildren(option('', 'All conferences'), ...[...new Set(current.teams.map(r => r.conference).filter(Boolean))].sort().map(c => option(c, c)));
      if ([...el('conference').options].some(o => o.value === chosenConference)) el('conference').value = chosenConference;
      const address = new URL(location.href);
      address.searchParams.set('snapshot', id);
      address.searchParams.set('reference', rank);
      address.searchParams.set('season', row.season); address.searchParams.set('week', row.week); address.hash = '';
      el('permalink').href = address.href;
      const descriptor = reference.descriptor(row, rank);
      el('csv').href = url(descriptor.csv); el('csv').hidden = false;
      el('csv').textContent = `${rank === reference.defaultRank ? 'Official' : reference.label(rank) + '-reference'} CSV ↓`;
      el('json').href = url(descriptor.json);
      if (writeURL) {
        // A pending merit load must not change the product tab the reader opened.
        if (location.hash === '#projections') address.hash = '#projections';
        history.replaceState(null, '', address);
      }
      notice(); render(); el('results').hidden = false; explorer.show(current,index); renderArchive();
      loadPolls();
      if (readerSettings) {
        for (const [key, field] of Object.entries(thresholdControls)) el(key).value = readerSettings[field] * 100;
        el('proximity').value = readerSettings.proximity; el('equal').checked = readerSettings.equal_records_only;
        applyPolicy();
      }
      el('status').textContent = `Loaded ${row.season} week ${row.week}.`;
      el('status').hidden = true;
    } catch (_) {
      if (sequence === loadNumber) el('status').textContent = `This week’s ${reference.label(rank)}-reference results could not be loaded. Choose another week or reload the page.`;
    } finally { if (sequence === loadNumber) root.removeAttribute('aria-busy'); }
  }
  async function browseSeason(season, week = null, writeURL = true) {
    populateUpdates(season, null, week);
    if (el('update').value) return select(el('update').value, writeURL);
    // A season or linked week awaiting fitting must not retain another week's results.
    loadNumber++; pollLoadNumber++; policyGeneration++; clearTimeout(policyFrame); window.CFBPolicy?.cancel(); current = null; previous = null; activePoll = null;
    root.removeAttribute('aria-busy');
    el('results').hidden = true; el('csv').hidden = true; el('notice').hidden = true;
    el('label').textContent = `${season} season`;
    document.getElementById('cfb-title').textContent = week == null ? 'Weekly rankings awaiting fits' : `Week ${week} rankings unavailable`;
    el('timing').textContent = 'Completed weekly fits will appear here as they become available.';
    el('status').hidden = false;
    el('status').textContent = week == null
      ? `The ${season} rankings are awaiting refits under the current model and rules.`
      : `${season} week ${week} is awaiting a refit under the current model and rules. Choose an available week below.`;
    if (writeURL) {
      const address = new URL(location.href);
      address.searchParams.delete('snapshot'); address.searchParams.set('season', season);
      if (week == null) address.searchParams.delete('week'); else address.searchParams.set('week', week);
      history.replaceState(null, '', address);
    }
  }
  el('season').addEventListener('change', () => browseSeason(el('season').value));
  el('week').addEventListener('change', () => browseSeason(el('season').value, Number(el('week').value)));
  el('reference').addEventListener('change', () => el('update').value
    ? select(el('update').value, true, true) : browseSeason(el('season').value, Number(el('week').value)));
  el('poll').addEventListener('change', loadPolls);
  el('poll-edition').addEventListener('change', renderPollEdition);
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
  for (const key of [...Object.keys(thresholdControls), 'proximity', 'equal']) el(key).addEventListener('input', () => {
    ruleSentences(); policyGeneration++; window.CFBPolicy?.cancel(); clearTimeout(policyFrame); policyFrame = setTimeout(applyPolicy, 180);
  });
  el('reset').addEventListener('click', () => { setOfficialPolicy(); render(); });
  el('team-a').addEventListener('change', () => { chooseOpponent(); renderAudit(); });
  el('team-b').addEventListener('change', renderAudit);
  el('open-rules').addEventListener('click', () => explorer.tab('rules', true));
  el('open-comparison').addEventListener('click', () => explainTeam(Number(el('team-a').value), Number(el('team-b').value)));
  el('compare-games').addEventListener('click', () => explainTeam(Number(el('stat-team').value), Number(el('stat-other').value)));
  el('open-rankings').addEventListener('click', () => explorer.tab('rankings', true));
  el('explanations').addEventListener('toggle', renderAudit);
  el('audit-download').addEventListener('click', () => {
    if (!policyResult || policyError) return;
    const blob = new Blob([JSON.stringify({snapshot: el('update').value, official: !customPolicy && current.reference_rank === reference.defaultRank,
      reference_rank: current.reference_rank,
      specification: policyResult.specification, order: policyResult.order, optimization: policyResult.optimization,
      teams: current.teams.map(t => ({id: t.id, name: t.name, wins: wins(t), losses: losses(t), wins_fbs: t.wins_fbs, losses_fbs: t.losses_fbs,
        saved_rank: t.rank, raw_merit_rank: t.raw_merit_rank})), audit: policyResult.audit}, null, 2) + '\n'], {type: 'application/json'});
    const address = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = address; link.download = `margin-of-merit-${el('update').value}-reference-${current.reference_rank}-${customPolicy ? 'reader' : 'saved'}-audit.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(address), 1000);
  });
  for (const key of ['search', 'conference', 'limit']) el(key).addEventListener(key === 'search' ? 'input' : 'change', render);
  function sortBy(key, nextDirection) {
    direction = nextDirection;
    sortKey = key;
    root.querySelectorAll('[data-cfb-sort]').forEach(button => {
      const th = button.closest('th');
      th.removeAttribute('aria-sort');
      const oldArrow = button.querySelector('[aria-hidden]'); if (oldArrow) oldArrow.remove();
      if (button.dataset.cfbSort !== key) return;
      th.setAttribute('aria-sort', direction === 1 ? 'ascending' : 'descending');
      const arrow = document.createElement('span'); arrow.setAttribute('aria-hidden', 'true');
      arrow.textContent = direction === 1 ? ' ↑' : ' ↓'; button.append(arrow);
    });
    render();
  }
  root.querySelectorAll('[data-cfb-sort]').forEach(button => button.addEventListener('click', () => {
    const key = button.dataset.cfbSort;
    sortBy(key, sortKey === key ? -direction : ['rank', 'name', 'poll_rank'].includes(key) ? 1 : -1);
  }));
  async function start() {
    try {
      index = await fetchJSON(root.dataset.index, 'no-store');
      if (index.schema !== 'margin-of-merit-index-v1' || !Array.isArray(index.snapshots)) throw new Error('Invalid archive');
      index.snapshots = index.snapshots.filter(r => r.week_complete !== false && r.methodology === reference.methodology);
      if (!index.snapshots.some(r => r.id === index.latest)) index.latest = index.snapshots[0]?.id || null;
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
  // A direct projections link does not download the merit archive until needed.
  if (location.hash === '#projections') document.addEventListener('cfb:merit-activate', start, {once:true});
  else start();
})();
