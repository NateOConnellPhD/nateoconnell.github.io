"""Margin of Merit v2: soft football preferences, explicit merit constraints.

The optimizer uses only the standard library. It consumes posterior summaries,
not predictive strength. Numerical summarization of paired merit draws is a
separate entry point below, using the model environment's existing NumPy.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass
import heapq
from itertools import combinations
import math

from sync_data import digest


@dataclass(frozen=True)
class Specification:
    version: str = 'margin-of-merit-order-v2'
    confidence_lock: float = 0.90
    h2h_bonus: float = 0.50
    common_bonus: float = 0.20
    crossing_friction: float = 0.04

    def __post_init__(self):
        if (not self.version or not .5 < self.confidence_lock < 1
                or not all(math.isfinite(x) and x >= 0 for x in
                           (self.h2h_bonus, self.common_bonus, self.crossing_friction))):
            raise ValueError('Invalid ranking-policy parameters')


CANONICAL = Specification()
POWER_FOUR = frozenset(('ACC', 'Big Ten', 'Big 12', 'SEC'))


def prepare_policy(teams, games, means, probabilities, *, season, specification=CANONICAL):
    """Probability entries are strict P(M_i > M_j); ties have separate mass.

    Inputs use the saved roster order and stable CFBD IDs. All games must already
    have passed season/cutoff/FBS eligibility checks in season_inputs.load_inputs.
    The modern P4 exception is never silently projected into pre-2024 seasons.
    """
    if type(season) is not int or season < 2024:
        raise ValueError('Pre-2024 conference protection needs an explicit historical policy')
    ids = [t['id'] for t in teams]
    n = len(ids)
    if (not n or any(type(i) is not int or i < 1 for i in ids) or len(set(ids)) != n
            or len(means) != n or len(probabilities) != n):
        raise ValueError('Invalid roster or posterior dimensions')
    means = [float(x) for x in means]
    p = [[float(x) for x in row] for row in probabilities]
    if (not all(math.isfinite(x) for x in means) or any(len(row) != n for row in p)
            or not all(math.isfinite(x) and 0 <= x <= 1 for row in p for x in row)):
        raise ValueError('Invalid posterior summaries')
    if any(p[i][i] != 0 for i in range(n)) or any(p[i][j] + p[j][i] > 1 + 1e-12 for i, j in combinations(range(n), 2)):
        raise ValueError('Expected strict pair probabilities with nonnegative tie mass')
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
    raw = sorted(active, key=lambda i: (-means[i], ids[i]))
    raw_rank = {i: k + 1 for k, i in enumerate(raw)}
    cost = [[0.] * n for _ in ids]
    for high, i in enumerate(raw):
        for j in raw[high + 1:]:
            cost[j][i] = max(0., 2 * p[i][j] - 1) + specification.crossing_friction
    locks = {(i, j): 'merit' for i in active for j in active
             if i != j and p[i][j] > specification.confidence_lock}
    if any(wins[i] >= 8 and losses[i] == 0 and
           (not isinstance(teams[i].get('conference'), str) or not teams[i]['conference'].strip()) for i in active):
        raise ValueError('Missing season conference for an undefeated team; protection cannot be determined')
    protected = [i for i in raw if teams[i].get('conference') in POWER_FOUR
                 and wins[i] >= 8 and losses[i] == 0]
    exceptions = []
    for i in protected:
        for j in active:
            if losses[j] >= 2:
                # This direct pair is the disclosed exception; unrelated locks remain.
                if (j, i) in locks:
                    exceptions.append({'protected_id': ids[i], 'other_id': ids[j],
                                       'p_other_higher_merit': p[j][i]})
                    del locks[j, i]
                locks[i, j] = 'undefeated_p4'
    evidence = []
    for i, j in combinations(sorted(active, key=lambda k: ids[k]), 2):
        if (wins[i], losses[i]) != (wins[j], losses[j]):
            continue
        if max(p[i][j], p[j][i]) > specification.confidence_lock:
            continue
        wi, wj = sum(vs[i].get(j, ())), sum(vs[j].get(i, ()))
        winner = loser = kind = None
        if wi != wj:
            winner, loser = (i, j) if wi > wj else (j, i)
            kind, bonus = 'head_to_head', specification.h2h_bonus
        else:
            shared = sorted((set(vs[i]) & set(vs[j])) - {i, j})
            # Integer cross-products compare win fractions exactly, including rematches.
            delta = [sum(vs[i][o]) * len(vs[j][o]) - sum(vs[j][o]) * len(vs[i][o]) for o in shared]
            if delta and min(delta) >= 0 and max(delta) > 0:
                winner, loser = i, j
            elif delta and max(delta) <= 0 and min(delta) < 0:
                winner, loser = j, i
            if winner is not None:
                kind, bonus = 'common_opponents', specification.common_bonus
        if winner is not None:
            cost[loser][winner] += bonus
            evidence.append({'winner_id': ids[winner], 'loser_id': ids[loser], 'type': kind,
                             'bonus': bonus, 'p_winner_higher_merit': p[winner][loser],
                             'winner_raw_rank': raw_rank[winner], 'loser_raw_rank': raw_rank[loser]})
    for i, j in locks:
        cost[j][i] = math.inf
    return {'ids': ids, 'raw': raw, 'raw_rank': raw_rank, 'cost': cost,
            'locks': locks, 'protected': protected, 'exceptions': exceptions,
            'evidence': evidence, 'wins': wins, 'losses': losses,
            'specification': asdict(specification)}


def feasible_baseline(state):
    """Stable topological repair; fail on conflicting hard constraints."""
    degree = {i: 0 for i in state['raw']}
    successors = {i: [] for i in degree}
    for i, j in state['locks']:
        degree[j] += 1
        successors[i].append(j)
    ready = [(state['raw_rank'][i], i) for i in degree if not degree[i]]
    heapq.heapify(ready)
    order = []
    while ready:
        _, i = heapq.heappop(ready)
        order.append(i)
        for j in sorted(successors[i]):
            degree[j] -= 1
            if not degree[j]:
                heapq.heappush(ready, (state['raw_rank'][j], j))
    if len(order) != len(degree):
        raise ValueError('Merit/P4 confidence constraints conflict; no ranking can be published')
    return order


def objective(cost, order):
    return math.fsum(cost[i][j] for k, i in enumerate(order) for j in order[k + 1:])


def optimize(state, *, max_steps=250):
    """Best insertion descent to an insertion-local, not global, optimum."""
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError('Invalid optimizer step limit')
    cost, ids = state['cost'], state['ids']
    order = feasible_baseline(state)
    initial = list(order)
    current = objective(cost, order)
    history = []
    for iteration in range(max_steps):
        best_delta, best = 0., None
        for start, i in enumerate(order):
            for direction in (-1, 1):
                delta = 0.
                for end in range(start + direction, -1 if direction == -1 else len(order), direction):
                    j = order[end]
                    change = cost[i][j] - cost[j][i] if direction == -1 else cost[j][i] - cost[i][j]
                    delta += change
                    if not math.isfinite(delta):
                        break
                    if delta < best_delta - 1e-9:
                        best_delta, best = delta, (start, end)
        if best is None:
            break
        start, end = best
        crossed = order[end:start] if end < start else order[start + 1:end + 1]
        team = order.pop(start)
        order.insert(end, team)
        history.append({'step': iteration + 1, 'team_id': ids[team],
                        'from': start + 1, 'to': end + 1,
                        'crossed_team_ids': [ids[j] for j in crossed],
                        'objective_change': best_delta})
        current += best_delta
    else:
        raise ValueError('Insertion optimizer did not converge; no ranking can be published')
    final = objective(cost, order)
    positions = {i: k + 1 for k, i in enumerate(order)}
    if (not math.isfinite(final) or abs(final - current) > 1e-6
            or any(positions[i] >= positions[j] for i, j in state['locks'])):
        raise ValueError('Final policy audit failed')
    evidence = []
    by_id = {ident: i for i, ident in enumerate(ids)}
    for row in state['evidence']:
        wr, lr = positions[by_id[row['winner_id']]], positions[by_id[row['loser_id']]]
        evidence.append({**row, 'winner_rank': wr, 'loser_rank': lr, 'honored': wr < lr})
    return {'specification': state['specification'], 'policy_sha256': digest(state['specification']),
            'order': [ids[i] for i in order], 'raw_order': [ids[i] for i in state['raw']],
            'unranked': [ids[i] for i in range(len(ids)) if i not in positions],
            'initial_feasible_order': [ids[i] for i in initial],
            'confidence_lock_count': sum(v == 'merit' for v in state['locks'].values()),
            'protected_team_ids': [ids[i] for i in state['protected']],
            'protection_exceptions': state['exceptions'], 'moves': history,
            'evidence': evidence, 'objective': final,
            'optimizer': 'deterministic best-insertion descent; insertion-local optimum only',
            'rank_interpretation': 'Official order; uncertainty summaries describe raw merit separately.'}


def rank_merit(teams, games, merit_draws, *, season, specification=CANONICAL):
    """Bridge from checked LOO merit draws to official ranks and raw uncertainty.

    Exact ties receive midpoint raw ranks and fractional top-K membership. No-game
    teams receive null ranks/probabilities instead of arbitrary prior-only ranks.
    """
    import numpy as np

    draws = np.asarray(merit_draws, dtype=float)
    if draws.ndim != 2 or draws.shape[1] != len(teams) or draws.shape[0] < 2 or not np.isfinite(draws).all():
        raise ValueError('Expected finite paired merit draws with columns in saved roster order')
    n = len(teams)
    p = np.zeros((n, n))
    for i, j in combinations(range(n), 2):
        p[i, j] = np.mean(draws[:, i] > draws[:, j])
        p[j, i] = np.mean(draws[:, j] > draws[:, i])
    state = prepare_policy(teams, games, draws.mean(axis=0), p, season=season, specification=specification)
    result = optimize(state)
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
    result['publication_ready'] = False  # Policy alone cannot certify the fit, data, or LOO diagnostics.
    return result
