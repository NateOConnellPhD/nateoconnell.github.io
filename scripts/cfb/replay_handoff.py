"""Compare the current ordering with a supplied release, without fitting.

Reads private handoff arrays in place. Prints a concise result; writes no files,
fetches no data, and never publishes the supplied posterior as a production fit.
"""
import argparse
import csv
import json
from pathlib import Path
import time

from ranking_policy import prepare_policy, order_policy
from exact_order import objective


def replay(folder, season):
    import numpy as np
    def rows(name):
        with (folder / f'{season}_{name}.csv').open(newline='') as source:
            return list(csv.DictReader(source))
    with np.load(folder / f'{season}_merit_draws.npz', allow_pickle=False) as saved:
        names, draws = saved['teams'].tolist(), saved['merit']
    n = len(names)
    if draws.ndim != 2 or draws.shape[1] != n or not np.isfinite(draws).all():
        raise ValueError('Invalid handoff merit dimensions')
    probabilities = np.zeros((n,n))
    for i in range(n):
        for j in range(i+1,n):
            probabilities[i,j] = np.mean(draws[:,i] > draws[:,j])
            probabilities[j,i] = np.mean(draws[:,j] > draws[:,i])
    roster, games = {}, []
    for row in rows('FBS_scored_games'):
        for side in ('home', 'away'):
            team = dict(id=int(row[side+'_id']), name=row[side+'_team'],
                        conference=row[side+'_conference'], classification=row[side+'_division'])
            if team['name'] in roster and roster[team['name']] != team:
                raise ValueError('Inconsistent handoff roster')
            roster[team['name']] = team
        games.append(dict(id=int(row['game_id']), season=int(row['season']), season_type=row['season_type'],
            eligible=True, completed=row['completed']=='True', home_id=int(row['home_id']), away_id=int(row['away_id']),
            home_points=int(row['home_points']), away_points=int(row['away_points'])))
    state = prepare_policy([roster[name] for name in names], games, draws.mean(axis=0), probabilities,
                           season=season, opponents=[t for t in roster.values() if t['classification']=='fcs'])
    started = time.monotonic()
    result = order_policy(state)
    by_id = {t['id']: t['name'] for t in roster.values()}
    actual = [by_id[i] for i in result['order']]
    expected = [r['team'] for r in sorted(rows('RANKING'), key=lambda r:int(r['rank']))]
    differences = [dict(rank=i+1, expected=e, actual=a) for i,(e,a) in enumerate(zip(expected,actual)) if e!=a]
    if len(expected) != len(actual):
        raise ValueError('Release roster sizes disagree')
    raw_indices = {by_id[ident]: i for i,ident in enumerate(result['raw_order'])}
    requirements = [dict(before=r['winner_raw_rank']-1, after=r['loser_raw_rank']-1, priority=r['priority'])
                    for r in result['audit'] if r['eligible']]
    expected_objective = objective([raw_indices[name] for name in expected], requirements)
    actual_objective = objective([raw_indices[name] for name in actual], requirements)
    summary = dict(teams=n, draws=len(draws), seconds=round(time.monotonic()-started,3),
        all_ranks_match=not differences, different_positions=len(differences),
        same_objective=actual_objective==expected_objective,
        release_objective=expected_objective, production_objective=actual_objective,
        optimization={k:v for k,v in result['optimization'].items() if k!='blocks'},
        dynamic_admissions=[dict(winner=by_id[r['winner_id']], loser=by_id[r['loser_id']],
                                 iteration=r['iteration']) for r in result['dynamic_trace']])
    print(json.dumps(summary), flush=True)
    if actual_objective != expected_objective:
        raise ValueError('Release and production objectives differ; inspect before accepting')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--season', type=int, default=2026)
    args = parser.parse_args()
    replay(args.folder, args.season)
