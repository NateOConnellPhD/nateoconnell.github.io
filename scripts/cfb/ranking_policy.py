"""Margin of Merit v4: literal thresholds and mutually exclusive game evidence.

No fitting or optimization costs. The numerical bridge summarizes saved LOO
merit draws; the stdlib policy is also mirrored in assets/js/cfb-policy.js.
"""
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import heapq
from itertools import combinations
import math

from sync_data import digest


@dataclass(frozen=True)
class Specification:
    version: str = 'margin-of-merit-order-v4'
    merit_protection: float = .90
    head_to_head: float = .90
    common_opponents: float = .70
    equal_records_only: bool = True
    undefeated_p4_protection: bool = True

    def __post_init__(self):
        if self.version != 'margin-of-merit-order-v4':
            raise ValueError('Unrecognized ranking policy')
        for value in (self.merit_protection, self.head_to_head, self.common_opponents):
            if type(value) not in (float, int) or not math.isfinite(value) or not .5 <= value <= .99:
                raise ValueError('Thresholds must lie between 50% and 99%')
        if any(type(v) is not bool for v in (self.equal_records_only, self.undefeated_p4_protection)):
            raise ValueError('Policy toggles must be boolean')


CANONICAL = Specification()
POWER_FOUR = frozenset(('ACC', 'Big Ten', 'Big 12', 'SEC'))


class PolicyConflict(ValueError):
    def __init__(self, decision, audit):
        self.decision, self.audit = decision, audit
        super().__init__('Contradictory hard requirements: ' + str(decision['conflict_path']))


def prepare_policy(teams, games, means, probabilities, *, season, specification=CANONICAL):
    """p includes half of exact ties. Roster conferences must be season-specific.

    Input games have already passed the season/cutoff/FBS checks. Teams without
    eligible games stay unranked. The same declared rules apply in every season;
    no era-specific conference substitutions are introduced here.
    """
    if type(season) is not int or season < 2002:
        raise ValueError('Use a season from 2002 onward')
    ids = [t['id'] for t in teams]
    names = [t['name'] for t in teams]
    n = len(ids)
    if (not n or any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != n
            or any(not isinstance(s, str) or not s for s in names) or len(set(names)) != n
            or len(means) != n or len(probabilities) != n):
        raise ValueError('Invalid roster or posterior dimensions')
    means = [float(x) for x in means]
    p = [[float(x) for x in row] for row in probabilities]
    if (not all(math.isfinite(x) for x in means) or any(len(row) != n for row in p)
            or not all(math.isfinite(x) and 0 <= x <= 1 for row in p for x in row)
            or any(p[i][i] != .5 for i in range(n))
            or any(abs(p[i][j] + p[j][i] - 1) > 1e-12 for i, j in combinations(range(n), 2))):
        raise ValueError('Expected finite half-tie pair probabilities summing to one')
    index = {ident: i for i, ident in enumerate(ids)}
    wins, losses = [0] * n, [0] * n
    vs = [defaultdict(list) for _ in ids]
    seen = set()
    for game in games:
        if (game['id'] in seen or game['season'] != season or game['eligible'] is not True
                or game['completed'] is not True or game['season_type'] != 'regular'):
            raise ValueError('Duplicate or ineligible policy game')
        seen.add(game['id'])
        if game['home_id'] not in index or game['away_id'] not in index:
            raise ValueError('Game team is absent from the saved season roster')
        h, a = index[game['home_id']], index[game['away_id']]
        hp, ap = game['home_points'], game['away_points']
        if h == a or any(type(x) is not int or x < 0 for x in (hp, ap)) or hp == ap:
            raise ValueError('Invalid matchup or tied final score')
        won = int(hp > ap)
        wins[h] += won; losses[h] += 1 - won
        wins[a] += 1 - won; losses[a] += won
        vs[h][a].append(won); vs[a][h].append(1 - won)
    active = [i for i in range(n) if wins[i] + losses[i] > 0]
    raw = sorted(active, key=lambda i: (-means[i], names[i], ids[i]))
    raw_rank = {i: k + 1 for k, i in enumerate(raw)}
    if specification.undefeated_p4_protection and any(wins[i] >= 8 and losses[i] == 0 and
            (not isinstance(teams[i].get('conference'), str) or not teams[i]['conference'].strip()) for i in active):
        raise ValueError('Missing season conference for an undefeated team')
    # Compact reproducible browser inputs; no posterior arrays or API credentials.
    payload = {'schema': 'margin-of-merit-policy-input-v4', 'season': season,
               'teams': [{k: t.get(k) for k in ('id', 'name', 'conference')} for t in teams],
               'means': means, 'probabilities': p,
               'games': [{k: g[k] for k in ('id', 'season', 'season_type', 'eligible', 'completed',
                                           'home_id', 'away_id', 'home_points', 'away_points')} for g in games]}
    return dict(ids=ids, names=names, teams=teams, p=p, raw=raw, raw_rank=raw_rank,
                wins=wins, losses=losses, vs=vs, specification=asdict(specification), payload=payload)


def order_policy(state):
    ids, names, p, raw, ranks = (state[k] for k in ('ids', 'names', 'p', 'raw', 'raw_rank'))
    wins, losses, vs, spec = (state[k] for k in ('wins', 'losses', 'vs', 'specification'))
    graph = {i: {} for i in raw}
    audit, exceptions = [], []

    def path(start, end):
        parents, queue = {start: None}, deque([start])
        while queue:
            i = queue.popleft()
            if i == end:
                chain = []
                while i is not None:
                    chain.append(i); i = parents[i]
                return chain[::-1]
            for j in graph[i]:
                if j not in parents:
                    parents[j] = i; queue.append(j)
        return None

    def decision(w, l, kind, **meta):
        return dict(type=kind, winner_id=ids[w], loser_id=ids[l],
                    winner_raw_rank=ranks[w], loser_raw_rank=ranks[l],
                    p_loser_higher_merit=p[l][w], **meta)

    def require(w, l, kind, hard=False, **meta):
        row = decision(w, l, kind, **meta)
        if l in graph[w]:
            row['status'] = 'already_satisfied'
        else:
            chain = path(l, w)
            if chain:
                row.update(status='blocked_by_conflict', conflict_path=[ids[i] for i in chain],
                           conflict_requirements=[dict(winner_id=ids[a], loser_id=ids[b], type=graph[a][b])
                                                  for a, b in zip(chain, chain[1:])])
                audit.append(row)
                if hard:
                    raise PolicyConflict(row, audit)
                return
            graph[w][l] = kind
            row['status'] = 'accepted'
        audit.append(row)

    protected = [i for i in raw if spec['undefeated_p4_protection'] and
                 state['teams'][i].get('conference') in POWER_FOUR and wins[i] >= 8 and losses[i] == 0]
    p4_pairs = {(i, j) for i in protected for j in raw if losses[j] >= 2}
    for w, l in sorted(p4_pairs, key=lambda pair: (ranks[pair[0]], ranks[pair[1]])):
        require(w, l, 'undefeated_p4', hard=True)
        if p[l][w] > spec['merit_protection']:
            exceptions.append(dict(protected_id=ids[w], other_id=ids[l], p_other_higher_merit=p[l][w]))
            audit.append(decision(l, w, 'merit_protection', status='overridden_by_p4',
                                  threshold=spec['merit_protection']))
    strong = []
    for i, j in combinations(raw, 2):
        if (i, j) in p4_pairs or (j, i) in p4_pairs:
            continue
        if p[i][j] > spec['merit_protection']:
            strong.append((i, j))
        elif p[j][i] > spec['merit_protection']:
            strong.append((j, i))
    for w, l in sorted(strong, key=lambda pair: (-p[pair[0]][pair[1]], ranks[pair[0]], ranks[pair[1]])):
        require(w, l, 'merit_protection', hard=True, threshold=spec['merit_protection'])
    pending = {'head_to_head': [], 'common_opponents': []}
    for i, j in combinations(sorted(raw, key=lambda k: (names[k], ids[k])), 2):
        if spec['equal_records_only'] and (wins[i], losses[i]) != (wins[j], losses[j]):
            continue
        w = l = None
        meta = {}
        direct = vs[i].get(j, ())
        if direct:
            wi, wj = sum(direct), len(direct) - sum(direct)
            if wi == wj:
                continue  # A split direct series never falls back to common opponents.
            w, l = (i, j) if wi > wj else (j, i)
            kind = 'head_to_head'
            meta['direct_record'] = [max(wi, wj), min(wi, wj)]
        else:
            shared = sorted((set(vs[i]) & set(vs[j])) - {i, j}, key=lambda k: (names[k], ids[k]))
            delta = [sum(vs[i][o]) * len(vs[j][o]) - sum(vs[j][o]) * len(vs[i][o]) for o in shared]
            if delta and min(delta) >= 0 and max(delta) > 0:
                w, l = i, j
            elif delta and max(delta) <= 0 and min(delta) < 0:
                w, l = j, i
            if w is not None:
                kind = 'common_opponents'
                meta['shared_results'] = [dict(opponent_id=ids[o], winner_wins=sum(vs[w][o]),
                                              winner_games=len(vs[w][o]), loser_wins=sum(vs[l][o]),
                                              loser_games=len(vs[l][o])) for o in shared]
        if w is None:
            continue
        meta['threshold'] = spec[kind]
        if p[l][w] > spec[kind]:
            audit.append(decision(w, l, kind, status='blocked_by_threshold', **meta))
        else:
            pending[kind].append((w, l, meta))
    for kind, rows in pending.items():
        rows.sort(key=lambda row: (p[row[1]][row[0]], names[row[0]], names[row[1]],
                                   ids[row[0]], ids[row[1]]))
        for w, l, meta in rows:
            require(w, l, kind, **meta)
    degree = {i: 0 for i in raw}
    for edges in graph.values():
        for j in edges:
            degree[j] += 1
    ready = [(ranks[i], i) for i in raw if degree[i] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _, i = heapq.heappop(ready)
        order.append(i)
        for j in graph[i]:
            degree[j] -= 1
            if degree[j] == 0:
                heapq.heappush(ready, (ranks[j], j))
    if len(order) != len(raw):
        raise ValueError('Cycle in accepted requirements')
    positions = {ids[i]: k + 1 for k, i in enumerate(order)}
    for row in audit:
        wr, lr = positions[row['winner_id']], positions[row['loser_id']]
        row.update(winner_rank=wr, loser_rank=lr, final_order_respected=wr < lr)
        if row['status'] in ('accepted', 'already_satisfied') and wr >= lr:
            raise ValueError('Final policy audit failed')
    return dict(specification=spec, policy_sha256=digest(spec), order=[ids[i] for i in order],
                raw_order=[ids[i] for i in raw], unranked=[i for i in ids if i not in positions],
                confidence_lock_count=len(strong), protected_team_ids=[ids[i] for i in protected],
                protection_exceptions=exceptions, audit=audit, policy_inputs=state['payload'],
                completion='Stable topological order, selecting the highest available raw-merit team.',
                rank_interpretation='Official order; uncertainty summaries describe raw merit separately.')


def replay(payload, specification=CANONICAL):
    if payload.get('schema') != 'margin-of-merit-policy-input-v4':
        raise ValueError('Missing v4 comparison inputs')
    return order_policy(prepare_policy(payload['teams'], payload['games'], payload['means'],
                        payload['probabilities'], season=payload['season'], specification=specification))


def rank_merit(teams, games, merit_draws, *, season, specification=CANONICAL):
    """Saved joint LOO draws -> v4 policy and unchanged raw-rank uncertainty."""
    import numpy as np

    draws = np.asarray(merit_draws, dtype=float)
    if draws.ndim != 2 or draws.shape[1] != len(teams) or draws.shape[0] < 2 or not np.isfinite(draws).all():
        raise ValueError('Expected finite paired merit draws with columns in saved roster order')
    n = len(teams)
    p = np.full((n, n), .5)
    for i, j in combinations(range(n), 2):
        p[i, j] = np.mean(draws[:, i] > draws[:, j]) + .5 * np.mean(draws[:, i] == draws[:, j])
        p[j, i] = 1 - p[i, j]
    state = prepare_policy(teams, games, draws.mean(axis=0), p, season=season, specification=specification)
    result = order_policy(state)
    positions = {ident: k + 1 for k, ident in enumerate(result['order'])}
    active = state['raw']
    raw_draws = draws[:, active]
    rows = []
    for i, team in enumerate(teams):
        row = {**team, 'wins_fbs': state['wins'][i], 'losses_fbs': state['losses'][i],
               'rank': positions.get(team['id']), 'raw_merit_rank': state['raw_rank'].get(i),
               'merit_mean': float(draws[:, i].mean()),
               'merit_lo90': float(np.quantile(draws[:, i], .05)),
               'merit_hi90': float(np.quantile(draws[:, i], .95))}
        if i in active:
            higher = np.sum(raw_draws > draws[:, i, None], axis=1)
            equal = np.sum(raw_draws == draws[:, i, None], axis=1)
            ranks = 1 + higher + (equal - 1) / 2
            row.update(raw_rank_mean=float(ranks.mean()), raw_rank_lo90=float(np.quantile(ranks, .05)),
                       raw_rank_hi90=float(np.quantile(ranks, .95)), status='ranked')
            row.update({f'p_raw_merit_top{k}': float(np.clip((k - higher) / equal, 0, 1).mean()) for k in (8, 10, 25)})
        else:
            row.update({key: None for key in ('raw_rank_mean', 'raw_rank_lo90', 'raw_rank_hi90',
                                              'p_raw_merit_top8', 'p_raw_merit_top10', 'p_raw_merit_top25')})
            row['status'] = 'no_eligible_games'
        rows.append(row)
    for k in (8, 10, 25):
        if not math.isclose(sum(r[f'p_raw_merit_top{k}'] or 0 for r in rows), min(k, len(active)), abs_tol=1e-8):
            raise ValueError('Raw top-K probability accounting failed')
    result['teams'] = sorted(rows, key=lambda r: (r['rank'] is None, r['rank'] or 0, r['id']))
    result['uncertainty'] = 'Raw merit from paired marginal-quantile LOO transport; joint dependence is approximate.'
    result['publication_ready'] = False
    return result
