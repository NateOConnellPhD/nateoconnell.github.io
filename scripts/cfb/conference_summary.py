"""Conference comparisons from joint full-data draws, never independent marginals."""
import math

from posterior_summary import summarize, validate_summaries

SCHEMA = 'margin-of-merit-conferences-v1'
METRICS = ('roster', 'baseline')


def membership(teams):
    groups, independents = {}, []
    for team in teams:
        name = team.get('conference')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Conference comparisons require season membership')
        if 'independent' in name.lower():
            independents.append(team['id'])
        else:
            groups.setdefault(name.strip(), []).append(team['id'])
    return {name: sorted(ids) for name, ids in groups.items()}, sorted(independents)


def build(flat, inputs):
    import numpy as np
    teams = inputs['teams']
    theta = np.asarray(flat['theta'])
    effects = np.asarray(flat['conference_effect'])
    structure = inputs['strength_structure']
    if (theta.ndim != 2 or theta.shape[1] != len(teams) or theta.shape[0] < 2
            or not np.isfinite(theta).all() or effects.shape != (theta.shape[0], len(structure['conference_labels']))
            or not np.isfinite(effects).all() or structure['team_ids'] != [t['id'] for t in teams]):
        raise ValueError('Conference summaries require aligned joint posterior draws')
    fbs = [t for t in teams if t['classification'] == 'fbs']
    groups, independents = membership(fbs)
    if not groups:
        raise ValueError('No FBS conferences available')
    positions = {t['id']: i for i, t in enumerate(teams)}
    if len(positions) != len(teams):
        raise ValueError('Duplicate team in conference roster')
    center = theta[:, [positions[t['id']] for t in fbs]].mean(axis=1)
    counts = {t['id']: 0 for t in teams}
    for game in inputs['games']:
        counts[game['home_id']] += 1
        counts[game['away_id']] += 1
    draws, rows = {key: [] for key in METRICS}, []
    for name, ids in sorted(groups.items()):
        indices = [positions[i] for i in ids]
        clusters = {structure['conference'][i] for i in indices}
        if len(clusters) != 1:
            raise ValueError('Conference membership disagrees with fitted hierarchy')
        draws['roster'].append(theta[:, indices].mean(axis=1) - center)
        draws['baseline'].append(effects[:, clusters.pop()] - center)
        rows.append({'name': name, 'team_ids': ids, 'teams': len(ids),
                     'teams_with_games': sum(counts[i] > 0 for i in ids), 'metrics': {}})
    comparisons = {}
    for key in METRICS:
        values = np.stack(draws[key], axis=1)
        strengths = [summarize(values[:, i]) for i in range(len(rows))]
        means = np.array([s['mean'] for s in strengths])
        best = values == values.max(axis=1, keepdims=True)
        comparisons[key] = {}
        for i, row in enumerate(rows):
            higher = (values > values[:, i, None]).sum(axis=1)
            equal = (values == values[:, i, None]).sum(axis=1)
            row['metrics'][key] = {'strength': strengths[i],
                'rank': summarize(1 + higher + (equal - 1) / 2, discrete=True),
                'point_rank': 1 + int((means > means[i]).sum()),
                'p_best': float((best[:, i] / best.sum(axis=1)).mean())}
            pairs = comparisons[key][row['name']] = {}
            for j, other in enumerate(rows):
                if i == j: continue
                difference = values[:, i] - values[:, j]
                pairs[other['name']] = {'difference': summarize(difference),
                    'p_greater': float((difference > 0).mean()), 'p_equal': float((difference == 0).mean())}
    output = {'schema': SCHEMA, 'draws': theta.shape[0], 'conferences': rows,
              'independent_team_ids': independents, 'comparisons': comparisons}
    validate(output, fbs)
    return output


def validate(value, teams):
    groups, independents = membership(teams)
    rows = value['conferences']
    if (value.get('schema') != SCHEMA or type(value.get('draws')) is not int or value['draws'] < 2
            or len(rows) != len(groups) or {r['name'] for r in rows} != set(groups)
            or value['independent_team_ids'] != independents or set(value['comparisons']) != set(METRICS)):
        raise ValueError('Invalid conference summary roster or schema')
    summaries = []
    for row in rows:
        if (row['team_ids'] != groups[row['name']] or row['teams'] != len(row['team_ids'])
                or not 0 <= row['teams_with_games'] <= row['teams'] or set(row['metrics']) != set(METRICS)):
            raise ValueError('Invalid conference membership or coverage')
    for key in METRICS:
        if set(value['comparisons'][key]) != set(groups):
            raise ValueError('Missing conference comparisons')
        best = []
        for row in rows:
            metric = row['metrics'][key]
            summaries.extend((metric['strength'], metric['rank']))
            best.append(metric['p_best'])
            expected = 1 + sum(r['metrics'][key]['strength']['mean'] > metric['strength']['mean'] for r in rows)
            if (metric['point_rank'] != expected or not 0 <= metric['p_best'] <= 1
                    or not 1 <= metric['rank']['mean'] <= len(rows)):
                raise ValueError('Invalid conference rank or probability')
            pairs = value['comparisons'][key][row['name']]
            if set(pairs) != set(groups) - {row['name']}:
                raise ValueError('Missing conference pair')
            for other, pair in pairs.items():
                reverse = value['comparisons'][key][other][row['name']]
                summaries.append(pair['difference'])
                if (not 0 <= pair['p_greater'] <= 1 or not 0 <= pair['p_equal'] <= 1
                        or not math.isclose(pair['p_equal'], reverse['p_equal'], abs_tol=1e-12)
                        or not math.isclose(pair['p_greater'] + reverse['p_greater'] + pair['p_equal'], 1., abs_tol=1e-12)
                        or not math.isclose(pair['difference']['mean'], -reverse['difference']['mean'], abs_tol=1e-10)):
                    raise ValueError('Inconsistent conference pair probability or difference')
        if not math.isclose(sum(best), 1., abs_tol=1e-10):
            raise ValueError('Conference strongest probabilities must sum to one')
    validate_summaries(summaries)
    if any(s['n'] != value['draws'] for s in summaries):
        raise ValueError('Conference summaries must share the same posterior draws')
