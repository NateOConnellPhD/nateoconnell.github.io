"""FCS-aware v5 ordering of frozen FBS merit. No sampling or network calls.

The exact objective is H2H, common opponents, merit protection, raw inversions,
then stable IDs. No ordering rule depends on conference membership.
"""
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from itertools import combinations
import math
import time

from exact_order import exact_order, UnsolvedOrder
from sync_data import digest


@dataclass(frozen=True)
class Specification:
    version: str = 'margin-of-merit-order-2026-11-21-no-p4'
    merit_protection: float = .90
    head_to_head: float = .95
    common_opponents: float = .70
    proximity: int = 2
    equal_records_only: bool = True

    def __post_init__(self):
        if self.version != 'margin-of-merit-order-2026-11-21-no-p4':
            raise ValueError('Unrecognized ranking policy')
        for value in (self.merit_protection, self.head_to_head, self.common_opponents):
            if type(value) not in (float, int) or not math.isfinite(value) or not .5 <= value <= .99:
                raise ValueError('Thresholds must lie between 50% and 99%')
        if type(self.proximity) is not int or not 0 <= self.proximity <= 200:
            raise ValueError('Proximity must be an integer from 0 to 200')
        if type(self.equal_records_only) is not bool:
            raise ValueError('Policy toggles must be boolean')


CANONICAL = Specification()
PRIORITY = {'head_to_head': 1, 'common_opponents': 2, 'merit_protection': 3}
PolicyConflict = UnsolvedOrder


def prepare_policy(teams, games, means, probabilities, *, season, specification=CANONICAL, opponents=()):
    """Teams are FBS; opponents lists FCS teams present in scored games.

    Strict greater-than probabilities can sum to less than one when draws tie.
    The common-opponent pool is FBS-only.
    Overall records include FCS games. All ranks and proximity use FBS only.
    """
    if type(season) is not int or season < 2002:
        raise ValueError('Use a season from 2002 onward')
    ids = [t['id'] for t in teams]
    names = [t['name'] for t in teams]
    n = len(ids)
    all_teams = list(teams) + list(opponents)
    all_ids = [t['id'] for t in all_teams]
    if (not n or len(set(all_ids)) != len(all_ids) or any(type(i) is not int or i < 1 for i in all_ids)
            or any(not isinstance(t.get('name'), str) or not t['name'] for t in all_teams)
            or any(t.get('classification', 'fbs') != 'fbs' for t in teams)
            or any(t.get('classification') != 'fcs' for t in opponents)
            or len(means) != n or len(probabilities) != n):
        raise ValueError('Invalid FBS/FCS roster or posterior dimensions')
    means = [float(x) for x in means]
    p = [[float(x) for x in row] for row in probabilities]
    if (not all(math.isfinite(x) for x in means) or any(len(row) != n for row in p)
            or not all(math.isfinite(x) and 0 <= x <= 1 for row in p for x in row)
            or any(p[i][i] != 0 for i in range(n))
            or any(p[i][j] + p[j][i] > 1 + 1e-12 for i, j in combinations(range(n), 2))):
        raise ValueError('Expected strict greater-than posterior probabilities')
    index = {ident: i for i, ident in enumerate(ids)}
    wins, losses, wins_fbs, losses_fbs = ([0] * n for _ in range(4))
    vs = [defaultdict(list) for _ in ids]
    seen, known = set(), set(all_ids)
    scored = []
    for game in sorted(games, key=lambda g: g['id']):
        if (game['id'] in seen or game['season'] != season or game['eligible'] is not True
                or game['completed'] is not True or game['season_type'] != 'regular'):
            raise ValueError('Duplicate or ineligible policy game')
        seen.add(game['id'])
        h, a = game['home_id'], game['away_id']
        hp, ap = game['home_points'], game['away_points']
        if (h not in known or a not in known or h == a or
                any(type(x) is not int or x < 0 for x in (hp, ap)) or hp == ap):
            raise ValueError('Invalid matchup, roster membership or tied final score')
        if h not in index and a not in index:
            continue
        scored.append(game)
        for ident, opponent, won in ((h, a, int(hp > ap)), (a, h, int(ap > hp))):
            if ident not in index:
                continue
            i = index[ident]
            wins[i] += won; losses[i] += 1 - won
            vs[i][opponent].append(won)
            if opponent in index:
                wins_fbs[i] += won; losses_fbs[i] += 1 - won
    raw = sorted((i for i in range(n) if wins[i] + losses[i]), key=lambda i: (-means[i], ids[i]))
    ranks = {i: k+1 for k, i in enumerate(raw)}
    payload = {'schema': 'margin-of-merit-policy-input-v5', 'season': season,
        'teams': [{k: t.get(k) for k in ('id', 'name', 'conference')} for t in teams],
        'opponents': [dict(id=t['id'], name=t['name'], classification='fcs') for t in sorted(opponents, key=lambda t: t['id'])],
        'means': means, 'probabilities': p,
        'games': [{k: g[k] for k in ('id', 'season', 'season_type', 'eligible', 'completed',
                  'home_id', 'away_id', 'home_points', 'away_points')} for g in scored]}
    return dict(ids=ids, names=names, teams=teams, p=p, raw=raw, raw_rank=ranks,
        wins=wins, losses=losses, wins_fbs=wins_fbs, losses_fbs=losses_fbs, vs=vs,
        specification=asdict(specification), payload=payload)


def order_policy(state):
    ids, p, raw, ranks = (state[k] for k in ('ids', 'p', 'raw', 'raw_rank'))
    wins, losses, vs, spec = (state[k] for k in ('wins', 'losses', 'vs', 'specification'))
    audit, requirements = [], []
    fbs_ids = set(ids)

    def decision(w, l, kind, **meta):
        row = dict(type=kind, priority=PRIORITY[kind], winner_id=ids[w], loser_id=ids[l],
            winner_record=[wins[w], losses[w]], loser_record=[wins[l], losses[l]],
            winner_raw_rank=ranks[w], loser_raw_rank=ranks[l], raw_rank_gap=abs(ranks[w]-ranks[l]),
            p_loser_higher_merit=p[l][w], **meta)
        audit.append(row)
        if row['eligible']:
            requirements.append(dict(before=ranks[w]-1, after=ranks[l]-1, priority=PRIORITY[kind]))
        return row

    for i, j in combinations(raw, 2):
        # Both directions count independently at q=.5 (a genuine exact tie).
        for w, l in ((i, j), (j, i)):
            if p[w][l] >= spec['merit_protection']:
                decision(w, l, 'merit_protection', eligible=True, qualification='posterior_merit',
                         threshold=spec['merit_protection'])
        if spec['equal_records_only'] and (wins[i], losses[i]) != (wins[j], losses[j]):
            continue
        w = l = None
        direct = vs[i].get(ids[j], ())
        meta = {}
        if direct:
            wi, wj = sum(direct), len(direct)-sum(direct)
            if wi == wj:
                continue
            w, l = (i, j) if wi > wj else (j, i)
            kind = 'head_to_head'
            meta['direct_record'] = [max(wi, wj), min(wi, wj)]
            meta['game_ids'] = [g['id'] for g in state['payload']['games']
                                if {g['home_id'], g['away_id']} == {ids[i], ids[j]}]
        else:
            shared = sorted(set(vs[i]) & set(vs[j]) & fbs_ids)
            delta = [sum(vs[i][o])*len(vs[j][o])-sum(vs[j][o])*len(vs[i][o]) for o in shared]
            if delta and min(delta) >= 0 and max(delta) > 0: w, l = i, j
            elif delta and max(delta) <= 0 and min(delta) < 0: w, l = j, i
            if w is not None:
                kind = 'common_opponents'
                meta['shared_results'] = [dict(opponent_id=o, winner_wins=sum(vs[w][o]),
                    winner_games=len(vs[w][o]), loser_wins=sum(vs[l][o]), loser_games=len(vs[l][o])) for o in shared]
                meta['game_ids'] = [g['id'] for g in state['payload']['games'] if
                    (g['home_id'] in (ids[i], ids[j]) and g['away_id'] in shared) or
                    (g['away_id'] in (ids[i], ids[j]) and g['home_id'] in shared)]
        if w is None: continue
        by_probability = p[l][w] < spec[kind]
        by_position = abs(ranks[w]-ranks[l]) <= spec['proximity']
        qualification = 'both' if by_probability and by_position else 'probability' if by_probability else 'proximity' if by_position else 'neither'
        decision(w, l, kind, eligible=by_probability or by_position, qualification=qualification,
                 threshold=spec[kind], proximity=spec['proximity'], **meta)
    # Admission is monotone. Recheck proximity in each solved order, never in
    # frozen raw ranks alone; at least one pending edge disappears per pass.
    dynamic_trace = []
    deadline = time.monotonic() + 120
    iteration = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UnsolvedOrder('Dynamic ranking exceeded its exact-solver time budget')
        local_order, certificate = exact_order([ids[i] for i in raw], requirements, timeout_seconds=remaining)
        current = {ids[raw[i]]: k+1 for k, i in enumerate(local_order)}
        iteration += 1
        added = []
        for row in audit:
            if row['eligible']: continue
            w, l = row['winner_id'], row['loser_id']
            gap = abs(current[w] - current[l])
            if gap > spec['proximity']: continue
            row.update(eligible=True, qualification=f'proximity_iteration_{iteration}',
                       admission_iteration=iteration, winner_rank_at_admission=current[w],
                       loser_rank_at_admission=current[l], rank_gap_at_admission=gap)
            requirements.append(dict(before=row['winner_raw_rank']-1,
                                     after=row['loser_raw_rank']-1, priority=row['priority']))
            added.append(dict(iteration=iteration, type=row['type'], winner_id=w, loser_id=l,
                winner_rank=current[w], loser_rank=current[l], rank_gap=gap,
                raw_rank_gap=row['raw_rank_gap'], p_loser_higher_merit=row['p_loser_higher_merit']))
        dynamic_trace.extend(added)
        if not added: break
    order = [raw[i] for i in local_order]
    positions = {ids[i]: k+1 for k, i in enumerate(order)}
    audit.sort(key=lambda r: (r['priority'], r['winner_id'], r['loser_id']))
    graph = {ident: {} for ident in positions}
    for row in audit:
        row.update(winner_rank=positions[row['winner_id']], loser_rank=positions[row['loser_id']])
        row['final_order_respected'] = row['winner_rank'] < row['loser_rank']
        row['status'] = 'not_eligible' if not row['eligible'] else 'accepted' if row['final_order_respected'] else 'overridden_by_global_objective'
        if row['eligible'] and row['final_order_respected']:
            graph[row['winner_id']].setdefault(row['loser_id'], row['type'])
    # A path of retained requirements explains a cycle, but is not itself the
    # optimality proof. The exact objective certificate is that proof.
    for row in audit:
        if row['status'] != 'overridden_by_global_objective': continue
        start, end = row['loser_id'], row['winner_id']
        for ceiling in range(1, 4):
            parents, queue = {start: None}, deque([start])
            while queue and end not in parents:
                a = queue.popleft()
                for b in sorted(graph[a]):
                    if b not in parents and PRIORITY[graph[a][b]] <= ceiling:
                        parents[b] = a; queue.append(b)
            if end in parents: break
        chain = []
        if end in parents:
            a = end
            while a is not None: chain.append(a); a = parents[a]
            chain.reverse()
        row['conflict_path'] = chain
        row['conflict_requirements'] = [dict(winner_id=a, loser_id=b, type=graph[a][b]) for a, b in zip(chain, chain[1:])]
        row['resolution'] = 'Global lexicographic optimum: direct results, common opponents, merit protection, raw inversions, stable IDs.'
    return dict(specification=spec, policy_sha256=digest(spec), order=[ids[i] for i in order],
        raw_order=[ids[i] for i in raw], unranked=sorted(i for i in ids if i not in positions),
        confidence_lock_count=sum(r['type'] == 'merit_protection' for r in audit),
        audit=audit,
        policy_inputs=state['payload'], optimization=certificate, dynamic_trace=dynamic_trace,
        completion='Exact lexicographic global optimum, then minimum raw-order inversions and stable IDs.',
        rank_interpretation='Policy order; uncertainty summaries describe raw earned merit separately.')


def replay(payload, specification=CANONICAL):
    if payload.get('schema') != 'margin-of-merit-policy-input-v5':
        raise ValueError('Missing FCS-aware v5 comparison inputs')
    return order_policy(prepare_policy(payload['teams'], payload['games'], payload['means'],
        payload['probabilities'], season=payload['season'], specification=specification, opponents=payload['opponents']))


def rank_merit(teams, games, merit_draws, *, season, specification=CANONICAL):
    """Joint FBS/FCS LOO draws -> FBS-only v5 order and raw-rank uncertainty."""
    import numpy as np

    draws = np.asarray(merit_draws, dtype=float)
    if draws.ndim != 2 or draws.shape[1] != len(teams) or draws.shape[0] < 2 or not np.isfinite(draws).all():
        raise ValueError('Expected finite paired merit draws with columns in saved roster order')
    fbs = [i for i,t in enumerate(teams) if t.get('classification', 'fbs') == 'fbs']
    opponents = [t for t in teams if t.get('classification') == 'fcs']
    teams = [teams[i] for i in fbs]
    draws = draws[:, fbs]
    n = len(teams)
    p = np.zeros((n, n))
    for i, j in combinations(range(n), 2):
        p[i, j] = np.mean(draws[:, i] > draws[:, j])
        p[j, i] = np.mean(draws[:, j] > draws[:, i])
    state = prepare_policy(teams, games, draws.mean(axis=0), p, season=season, specification=specification, opponents=opponents)
    result = order_policy(state)
    positions = {ident: k + 1 for k, ident in enumerate(result['order'])}
    active = state['raw']
    raw_draws = draws[:, active]
    rows = []
    for i, team in enumerate(teams):
        row = {**team, 'wins': state['wins'][i], 'losses': state['losses'][i],
               'wins_fbs': state['wins_fbs'][i], 'losses_fbs': state['losses_fbs'][i],
               'wins_fcs': state['wins'][i]-state['wins_fbs'][i],
               'losses_fcs': state['losses'][i]-state['losses_fbs'][i],
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
