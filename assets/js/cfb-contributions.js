/* One selected pair, using only the game summaries in the loaded snapshot. */
(function (scope) {
  'use strict';
  const schema = 'margin-of-merit-game-contributions-v1';
  const sum = rows => rows.reduce((total, row) => total + row.credit.mean, 0);
  const signed = value => Math.abs(value) < .0005 ? '0.000' : `${value > 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`;
  const tone = value => Math.abs(value) < .0005 ? '' : value > 0 ? 'cfb-credit-positive' : 'cfb-credit-negative';

  function compare(snapshot, a, b) {
    const block = snapshot.game_contributions;
    if (!block) return null;
    if (block.schema !== schema || block.reference_rank !== snapshot.reference_rank) throw new Error('Invalid contribution reference');
    const teams = [a, b].map(id => snapshot.teams.find(t => t.id === id));
    if (a === b || teams.some(t => !t || t.rank == null)) throw new Error('Choose two ranked teams');
    const names = new Map([...snapshot.teams, ...(snapshot.policy_inputs.opponents || [])].map(t => [t.id, t.name]));
    const fbs = new Set(snapshot.teams.map(t => t.id));
    const seen = new Set(), expected = new Map(snapshot.policy_inputs.games.map(g => [g.id, g]));
    for (const g of block.games) {
      const saved = expected.get(g.id);
      if (seen.has(g.id) || !saved || ['home_id', 'away_id', 'home_points', 'away_points'].some(k => g[k] !== saved[k])) throw new Error('Invalid contribution schedule');
      seen.add(g.id);
    }
    if (seen.size !== expected.size) throw new Error('Incomplete contribution schedule');
    const schedules = [a, b].map(id => block.games.filter(g => g.home_id === id || g.away_id === id).map(g => {
      const side = g.home_id === id ? 'home' : 'away', other = side === 'home' ? 'away' : 'home';
      const credit = g[`${side}_credit`], won = g[`${side}_points`] > g[`${other}_points`];
      if (!credit || ['mean', 'median', 'q05', 'q95'].some(k => !Number.isFinite(credit[k]) || credit[k] < (won ? 0 : -1) || credit[k] > (won ? 1 : 0)) || credit.q05 > credit.median || credit.median > credit.q95) throw new Error('Invalid game credit');
      const opponent = g[`${other}_id`];
      return {game: g.id, team: id, opponent, opponentName: names.get(opponent) || String(opponent),
        fcs: !fbs.has(opponent), week: g.week, date: g.start_date,
        venue: g.neutral_site ? 'Neutral' : side === 'home' ? 'Home' : 'Away',
        result: `${won ? 'W' : 'L'} ${g[`${side}_points`]}–${g[`${other}_points`]}`, credit};
    }));
    for (let i = 0; i < 2; i++) {
      if (schedules[i].length !== teams[i].wins + teams[i].losses || Math.abs(sum(schedules[i]) - teams[i].merit_mean) > 1e-9) throw new Error('Game credits do not reconcile with merit');
    }
    const opponentsB = new Set(schedules[1].map(g => g.opponent));
    const common = new Set(schedules[0].map(g => g.opponent).filter(id => id !== b && id !== a && opponentsB.has(id)));
    const groups = [
      {key: 'direct', label: 'Head-to-head games', match: g => g.opponent === a || g.opponent === b},
      {key: 'common', label: 'Common opponents', match: g => common.has(g.opponent)},
      {key: 'other', label: 'Remaining schedule', match: g => g.opponent !== a && g.opponent !== b && !common.has(g.opponent)}
    ].map(group => {
      const games = schedules.map(rows => rows.filter(group.match));
      const means = games.map(sum);
      return {...group, games, means, gap: means[0] - means[1]};
    });
    return {teams, groups, gap: teams[0].merit_mean - teams[1].merit_mean, common};
  }

  function render(container, snapshot, a, b, shownTeams) {
    container.replaceChildren();
    const doc = container.ownerDocument;
    const node = (tag, text, cls) => { const n = doc.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
    const p = text => container.append(node('p', text, 'small-note'));
    let result;
    try { result = compare(snapshot, a, b); }
    catch (_) { p('This saved update’s game credits could not be reconciled with its merit totals. The game breakdown is unavailable.'); return; }
    if (!result) { p('This saved week does not yet include game-by-game credit. Its breakdown will appear when that week is regenerated; the merit estimates above remain available.'); return; }
    const [ta, tb] = result.teams, gap = result.gap;
    container.append(node('h3', 'Where the merit gap comes from'));
    const higher = gap >= 0 ? ta : tb, lower = gap >= 0 ? tb : ta;
    container.append(node('p', Math.abs(gap) < 1e-9 ? 'These teams have equal mean merit.'
      : `${higher.name} has ${Math.abs(gap).toFixed(3)} more merit than ${lower.name}.`, 'cfb-credit-headline'));
    const driver = result.groups.filter(g => g.gap * gap > 0).sort((x, y) => Math.abs(y.gap) - Math.abs(x.gap))[0];
    if (driver) p(`The largest component favoring ${higher.name} is ${driver.label.toLowerCase()}: ${Math.abs(driver.gap).toFixed(3)} merit. The table includes the components that offset it.`);
    const shown = [ta, tb].map(t => (shownTeams || snapshot.teams).find(row => row.id === t.id)?.rank);
    if (gap * (shown[1] - shown[0]) < 0) p('The team with less mean merit is ranked higher under the selected ordering rules. Those rules reorder teams; they do not award extra game credit. See the rule decisions below.');
    p(`Every difference below is ${ta.name} minus ${tb.name}. Positive favors ${ta.name}; negative favors ${tb.name}. The three groups do not overlap and add to the overall gap.`);

    function table(parent, label, headings) {
      const scroll = node('div', null, 'cfb-table-scroll'); scroll.tabIndex = 0;
      scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', label);
      const table = node('table', null, 'cfb-summary-table cfb-credit-table');
      const caption = node('caption', label); table.append(caption);
      const head = node('thead'), tr = node('tr');
      headings.forEach(label => { const th = node('th', label); th.scope = 'col'; tr.append(th); });
      head.append(tr); table.append(head); const body = node('tbody'); table.append(body);
      scroll.append(table); parent.append(scroll); return body;
    }
    const body = table(container, 'Additive mean merit by part of the schedule', ['Component', ta.name, tb.name, 'Difference']);
    for (const g of [...result.groups, {key: 'total', label: 'Overall merit', means: [ta.merit_mean, tb.merit_mean], gap}]) {
      const tr = node('tr', null, g.key === 'total' ? 'cfb-credit-total' : '');
      const label = node('th', g.label); label.scope = 'row'; tr.append(label);
      g.means.forEach(value => tr.append(node('td', signed(value))));
      tr.append(node('td', signed(g.gap), tone(g.gap))); body.append(tr);
    }
    p('A win earns between 0 and +1 credit; a loss contributes between −1 and 0. The model evaluates the margin against the selected reference, accounting for opponent strength and venue, with the game itself left out of the strength fit. These factors determine one game credit, not separate bonuses.');
    p('The values are posterior means: averages over the model’s uncertainty. Game means add to total merit. Medians and 90% interval endpoints do not add; uncertainty across games is related. Displayed values are rounded to three decimals.');
    for (const group of result.groups) {
      const details = node('details'); details.open = group.key === 'direct' && group.games[0].length > 0;
      details.append(node('summary', `${group.label} · ${ta.name}: ${group.games[0].length} games · ${tb.name}: ${group.games[1].length} games · difference ${signed(group.gap)}`));
      const rows = group.games.flat().sort((x, y) => group.key === 'common'
        ? x.opponentName.localeCompare(y.opponentName) || (x.team === a ? 0 : 1) - (y.team === a ? 0 : 1) || x.week - y.week || x.game - y.game
        : x.week - y.week || x.game - y.game || (x.team === a ? 0 : 1) - (y.team === a ? 0 : 1));
      if (!rows.length) details.append(node('p', group.key === 'direct' ? 'These teams have not played each other through this week.' : 'No games in this group through this week.'));
      else {
        if (group.key === 'common') {
          details.append(node('p', 'Games are grouped by shared opponent, including repeat meetings and FCS opponents. This accounts for earned merit even when the separate common-opponent ordering rule does not apply; that rule uses shared FBS opponents only.'));
          const subtotals = table(details, 'Credit against each common opponent (all meetings)', ['Opponent', ta.name, tb.name, 'Difference']);
          for (const id of [...result.common].sort((x, y) => rows.find(g => g.opponent === x).opponentName.localeCompare(rows.find(g => g.opponent === y).opponentName))) {
            const opponent = rows.find(g => g.opponent === id);
            const means = group.games.map(games => sum(games.filter(g => g.opponent === id)));
            const tr = node('tr'); tr.append(node('td', `${opponent.opponentName}${opponent.fcs ? ' (FCS)' : ''}`));
            means.forEach(value => tr.append(node('td', signed(value))));
            tr.append(node('td', signed(means[0] - means[1]), tone(means[0] - means[1]))); subtotals.append(tr);
          }
        }
        if (group.key === 'direct') details.append(node('p', 'Each meeting appears once for each team’s credit. The credits need not cancel: each team faced a different opponent strength. They already count in merit; the head-to-head ordering rule adds no bonus.'));
        const games = table(details, `${group.label}: every contributing game`, ['Team', 'Week / date', 'Opponent', 'Venue', 'Result', 'Mean credit', 'Median', '90% interval']);
        for (const g of rows) {
          const tr = node('tr');
          const date = new Date(g.date).toLocaleDateString(undefined, {month: 'short', day: 'numeric', timeZone: 'America/New_York'});
          const values = [g.team === a ? ta.name : tb.name, `Week ${g.week} · ${date}`, `${g.opponentName}${g.fcs ? ' (FCS)' : ''}`, g.venue, g.result, signed(g.credit.mean), signed(g.credit.median), `${signed(g.credit.q05)} to ${signed(g.credit.q95)}`];
          values.forEach((value, i) => tr.append(node('td', value, i === 5 ? tone(g.credit.mean) : ''))); games.append(tr);
        }
      }
      container.append(details);
    }
  }
  const api = {compare, render};
  if (typeof module === 'object' && module.exports) module.exports = api;
  else scope.CFBContributions = api;
})(typeof window === 'object' ? window : globalThis);
