/* Margin of Merit v4. Pure replay of saved probabilities and game results.
 * No network, HMC, or mutable snapshot state. Kept in parity with ranking_policy.py. */
((global) => {
  'use strict';
  const defaults = Object.freeze({version: 'margin-of-merit-order-v4', merit_protection: .9,
    head_to_head: .9, common_opponents: .7, equal_records_only: true, undefeated_p4_protection: true});
  const textCompare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  const sum = list => list.reduce((a, b) => a + b, 0);
  function run(input, settings = defaults) {
    const spec = {...defaults, ...settings};
    if (input?.schema !== 'margin-of-merit-policy-input-v4' || spec.version !== defaults.version || input.season < 2024) {
      throw new Error('This saved update does not include the information needed to adjust its ranking rules.');
    }
    for (const key of ['merit_protection', 'head_to_head', 'common_opponents']) {
      if (!Number.isFinite(spec[key]) || spec[key] < .5 || spec[key] > .99) throw new Error('Thresholds must be between 50% and 99%.');
    }
    for (const key of ['equal_records_only', 'undefeated_p4_protection']) {
      if (typeof spec[key] !== 'boolean') throw new Error('Invalid policy toggle.');
    }
    const {teams, means, probabilities: p, games} = input, n = teams.length;
    const ids = teams.map(t => t.id), names = teams.map(t => t.name);
    const index = new Map(ids.map((id, i) => [id, i]));
    if (!n || index.size !== n || new Set(names).size !== n || means.length !== n || p.length !== n ||
        !means.every(Number.isFinite) || p.some(row => row.length !== n || row.some(x => !Number.isFinite(x) || x < 0 || x > 1))) {
      throw new Error('Invalid saved comparison dimensions.');
    }
    for (let i = 0; i < n; i++) {
      if (p[i][i] !== .5) throw new Error('Invalid half-tie probabilities.');
      for (let j = i + 1; j < n; j++) if (Math.abs(p[i][j] + p[j][i] - 1) > 1e-12) throw new Error('Invalid pair probabilities.');
    }
    const wins = Array(n).fill(0), losses = Array(n).fill(0), vs = Array.from({length: n}, () => new Map()), seen = new Set();
    for (const g of games) {
      const h = index.get(g.home_id), a = index.get(g.away_id);
      if (seen.has(g.id) || g.season !== input.season || g.eligible !== true || g.completed !== true ||
          g.season_type !== 'regular' || h == null || a == null || h === a ||
          ![g.home_points, g.away_points].every(x => Number.isInteger(x) && x >= 0) || g.home_points === g.away_points) {
        throw new Error('Invalid saved game.');
      }
      seen.add(g.id);
      const won = Number(g.home_points > g.away_points);
      wins[h] += won; losses[h] += 1 - won; wins[a] += 1 - won; losses[a] += won;
      if (!vs[h].has(a)) vs[h].set(a, []);
      if (!vs[a].has(h)) vs[a].set(h, []);
      vs[h].get(a).push(won); vs[a].get(h).push(1 - won);
    }
    const nameOrder = (i, j) => textCompare(names[i], names[j]) || ids[i] - ids[j];
    const raw = ids.map((_, i) => i).filter(i => wins[i] + losses[i] > 0).sort((i, j) => means[j] - means[i] || nameOrder(i, j));
    const ranks = new Map(raw.map((i, k) => [i, k + 1])), graph = new Map(raw.map(i => [i, new Map()]));
    const audit = [], exceptions = [];
    function path(start, end) {
      const parents = new Map([[start, null]]), queue = [start];
      for (let k = 0; k < queue.length; k++) {
        let i = queue[k];
        if (i === end) {
          const chain = [];
          while (i != null) { chain.push(i); i = parents.get(i); }
          return chain.reverse();
        }
        for (const j of graph.get(i).keys()) if (!parents.has(j)) { parents.set(j, i); queue.push(j); }
      }
      return null;
    }
    const decision = (w, l, type, meta) => ({type, winner_id: ids[w], loser_id: ids[l],
      winner_raw_rank: ranks.get(w), loser_raw_rank: ranks.get(l), p_loser_higher_merit: p[l][w], ...meta});
    function require(w, l, type, hard = false, meta = {}) {
      const row = decision(w, l, type, meta);
      if (graph.get(w).has(l)) row.status = 'already_satisfied';
      else {
        const chain = path(l, w);
        if (chain) {
          Object.assign(row, {status: 'blocked_by_conflict', conflict_path: chain.map(i => ids[i]),
            conflict_requirements: chain.slice(0, -1).map((a, k) => ({winner_id: ids[a], loser_id: ids[chain[k+1]], type: graph.get(a).get(chain[k+1])}))});
          audit.push(row);
          if (hard) {
            const error = new Error(`These settings create contradictory required orderings: ${chain.map(i => names[i]).join(' → ')} → ${names[l]}.`);
            error.decision = row; error.audit = audit; throw error;
          }
          return;
        }
        graph.get(w).set(l, type); row.status = 'accepted';
      }
      audit.push(row);
    }
    if (spec.undefeated_p4_protection && raw.some(i => wins[i] >= 8 && !losses[i] &&
        (typeof teams[i].conference !== 'string' || !teams[i].conference.trim()))) throw new Error('Missing season conference for an undefeated team.');
    const p4 = new Set(['ACC', 'Big Ten', 'Big 12', 'SEC']);
    const protectedTeams = raw.filter(i => spec.undefeated_p4_protection && p4.has(teams[i].conference) && wins[i] >= 8 && losses[i] === 0);
    const p4Pairs = new Set();
    for (const w of protectedTeams) for (const l of raw) if (losses[l] >= 2) {
      p4Pairs.add(`${w},${l}`); require(w, l, 'undefeated_p4', true);
      if (p[l][w] > spec.merit_protection) {
        exceptions.push({protected_id: ids[w], other_id: ids[l], p_other_higher_merit: p[l][w]});
        audit.push(decision(l, w, 'merit_protection', {status: 'overridden_by_p4', threshold: spec.merit_protection}));
      }
    }
    const strong = [];
    for (let a = 0; a < raw.length; a++) for (let b = a+1; b < raw.length; b++) {
      const i = raw[a], j = raw[b];
      if (p4Pairs.has(`${i},${j}`) || p4Pairs.has(`${j},${i}`)) continue;
      if (p[i][j] > spec.merit_protection) strong.push([i, j]);
      else if (p[j][i] > spec.merit_protection) strong.push([j, i]);
    }
    strong.sort((a, b) => p[b[0]][b[1]] - p[a[0]][a[1]] || ranks.get(a[0]) - ranks.get(b[0]) || ranks.get(a[1]) - ranks.get(b[1]));
    for (const [w, l] of strong) require(w, l, 'merit_protection', true, {threshold: spec.merit_protection});
    const pending = {head_to_head: [], common_opponents: []}, alphabetic = [...raw].sort(nameOrder);
    for (let a = 0; a < alphabetic.length; a++) for (let b = a+1; b < alphabetic.length; b++) {
      const i = alphabetic[a], j = alphabetic[b];
      if (spec.equal_records_only && (wins[i] !== wins[j] || losses[i] !== losses[j])) continue;
      let w, l, type; const meta = {}, direct = vs[i].get(j) || [];
      if (direct.length) {
        const wi = sum(direct), wj = direct.length - wi;
        if (wi === wj) continue;
        [w, l] = wi > wj ? [i, j] : [j, i]; type = 'head_to_head'; meta.direct_record = [Math.max(wi, wj), Math.min(wi, wj)];
      } else {
        const shared = [...vs[i].keys()].filter(o => o !== i && o !== j && vs[j].has(o)).sort(nameOrder);
        const delta = shared.map(o => sum(vs[i].get(o)) * vs[j].get(o).length - sum(vs[j].get(o)) * vs[i].get(o).length);
        if (delta.some(d => d > 0) && delta.every(d => d >= 0)) [w, l] = [i, j];
        else if (delta.some(d => d < 0) && delta.every(d => d <= 0)) [w, l] = [j, i];
        if (w != null) {
          type = 'common_opponents'; meta.shared_results = shared.map(o => ({opponent_id: ids[o],
            winner_wins: sum(vs[w].get(o)), winner_games: vs[w].get(o).length,
            loser_wins: sum(vs[l].get(o)), loser_games: vs[l].get(o).length}));
        }
      }
      if (w == null) continue;
      meta.threshold = spec[type];
      if (p[l][w] > spec[type]) audit.push(decision(w, l, type, {...meta, status: 'blocked_by_threshold'}));
      else pending[type].push([w, l, meta]);
    }
    for (const [type, rows] of Object.entries(pending)) {
      rows.sort((a, b) => p[a[1]][a[0]] - p[b[1]][b[0]] || textCompare(names[a[0]], names[b[0]]) ||
        textCompare(names[a[1]], names[b[1]]) || ids[a[0]] - ids[b[0]] || ids[a[1]] - ids[b[1]]);
      for (const [w, l, meta] of rows) require(w, l, type, false, meta);
    }
    const degree = new Map(raw.map(i => [i, 0])), order = [];
    for (const edges of graph.values()) for (const j of edges.keys()) degree.set(j, degree.get(j) + 1);
    const ready = raw.filter(i => degree.get(i) === 0);
    while (ready.length) {
      ready.sort((i, j) => ranks.get(i) - ranks.get(j));
      const i = ready.shift(); order.push(i);
      for (const j of graph.get(i).keys()) {
        degree.set(j, degree.get(j) - 1); if (degree.get(j) === 0) ready.push(j);
      }
    }
    if (order.length !== raw.length) throw new Error('Cycle in accepted requirements.');
    const positions = new Map(order.map((i, k) => [ids[i], k + 1]));
    for (const row of audit) {
      row.winner_rank = positions.get(row.winner_id); row.loser_rank = positions.get(row.loser_id);
      row.final_order_respected = row.winner_rank < row.loser_rank;
      if (['accepted', 'already_satisfied'].includes(row.status) && !row.final_order_respected) throw new Error('Policy audit failed.');
    }
    return {specification: spec, order: order.map(i => ids[i]), raw_order: raw.map(i => ids[i]),
      unranked: ids.filter(id => !positions.has(id)), confidence_lock_count: strong.length,
      protected_team_ids: protectedTeams.map(i => ids[i]), protection_exceptions: exceptions, audit};
  }
  const api = Object.freeze({run, defaults});
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.CFBPolicy = api;
})(globalThis);
