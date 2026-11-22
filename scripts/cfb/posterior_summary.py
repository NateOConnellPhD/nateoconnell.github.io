"""Compact empirical posterior distributions, calculated once during publication.

No fitted curves, synthetic draws, or independent reconstruction of joint draws.
Full-precision summaries use every saved draw. Histograms retain all tail mass.
"""
from collections import Counter
import hashlib
import json
import math
import statistics

SCHEMA = 'margin-of-merit-posterior-v1'


def summarize(values, *, discrete=False):
    values = sorted(float(v) for v in values)
    if len(values) < 2 or not all(math.isfinite(v) for v in values):
        raise ValueError('Expected at least two finite posterior draws')
    n = len(values)

    def quantile(p):
        position = (n - 1) * p
        low = int(position)
        return values[low] + (values[min(low + 1, n - 1)] - values[low]) * (position - low)

    if discrete or values[0] == values[-1]:
        counts = Counter(values)
        histogram = {'kind': 'mass', 'x': sorted(counts), 'counts': [counts[x] for x in sorted(counts)]}
    else:
        low, high = values[0], values[-1]
        bins = 40
        edges = [low + (high - low) * i / bins for i in range(bins + 1)]
        counts = [0] * bins
        for value in values:
            counts[min(bins - 1, int((value - low) / (high - low) * bins))] += 1
        histogram = {'kind': 'histogram', 'edges': edges, 'counts': counts}
    return {'n': n, 'mean': statistics.fmean(values), 'median': quantile(.5),
            'sd': statistics.stdev(values), 'q05': quantile(.05), 'q25': quantile(.25),
            'q75': quantile(.75), 'q95': quantile(.95), 'distribution': histogram}


def attach(result, inputs, task):
    """Read integrity-checked arrays from the existing fit; never rerun inference."""
    import numpy as np
    from loo_scoring import flatten

    def read(folder, filename):
        report = json.loads((folder / 'report.json').read_text())
        if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != report['array_sha256']:
            raise ValueError('Posterior summary cache integrity check failed')
        with np.load(folder / filename, allow_pickle=False) as saved:
            arrays = dict(saved)
        return report, arrays

    score_report, scores = read(task / 'scores' / result['identity']['score_key'], 'merit.npz')
    if score_report['identity'].get('reference_rank') != result.get('reference_rank'):
        raise ValueError('Posterior summaries use a different reference team')
    if score_report['array_sha256'] != result['identity']['merit_sha256']:
        raise ValueError('Posterior summaries do not belong to these rankings')
    fit_report, samples = read(task / 'fits' / score_report['identity']['fit_key'], 'posterior.npz')
    if fit_report['array_sha256'] != score_report['identity']['posterior_sha256']:
        raise ValueError('Posterior and merit cache identities disagree')
    if result.get('home_prior') != fit_report['identity'].get('home_prior'):
        raise ValueError('Posterior summaries do not belong to this historical home prior')
    flat = flatten(samples)
    merit, sos = scores['merit'], scores['sos']
    rows = {r['id']: r for r in result['teams']}
    active = [i for i, t in enumerate(inputs['teams']) if t['id'] in rows and rows[t['id']]['status'] == 'ranked']
    output = {}
    home_slots = {inputs['teams'][i]['id']: slot+1 for slot, i in enumerate(inputs['fbs_indices'])}
    for i, team in enumerate(inputs['teams']):
        if team['id'] not in rows: continue
        row = rows[team['id']]
        metrics = {'strength': summarize(flat['theta'][:, i])}
        if 'conference_effect' in flat:
            cluster = inputs['strength_structure']['conference'][i]
            metrics['conference_effect'] = summarize(flat['conference_effect'][:, cluster])
        if 'home_effect' in flat:
            offset = flat['home_effect'][:, home_slots[team['id']]]
            metrics.update(home_offset=summarize(offset), home_total=summarize(flat['home_adv'] + offset))
        if i in active:
            higher = np.sum(merit[:, active] > merit[:, i, None], axis=1)
            equal = np.sum(merit[:, active] == merit[:, i, None], axis=1)
            ranks = 1 + higher + (equal - 1) / 2
            metrics.update(merit=summarize(merit[:, i]), raw_rank=summarize(ranks, discrete=True),
                           sos=summarize(sos[:, i]))
            for key in ('merit', 'raw_rank', 'sos'):
                if not math.isclose(metrics[key]['mean'], row[key + '_mean'], abs_tol=1e-10):
                    raise ValueError('Posterior summary mean disagrees with ranking: ' + key)
                row[key + '_median'] = metrics[key]['median']
                row[key + '_sd'] = metrics[key]['sd']
        output[str(team['id'])] = metrics
    parameters = {name: summarize(flat[name]) for name in ('home_adv', 'sigma', 'nu')}
    if 'mu_fcs' in flat:
        parameters.update(mu_fcs=summarize(flat['mu_fcs']), tau_conf=summarize(flat['tau_conf']),
                          tau_fbs=summarize(flat['tau_division'][:, 0]), tau_fcs=summarize(flat['tau_division'][:, 1]))
    result['posterior'] = {'schema': SCHEMA, 'reference_rank': result['reference_rank'], 'teams': output, 'parameters': parameters,
        'interpretation': 'Merit, raw rank and schedule strength use the saved marginal-quantile LOO approximation. '
                          'Team strength and model parameters use the full-data posterior. '
                          'Raw rank uses midranks for exact ties. Ordering rules are not applied to draws.',
        'representation': 'Empirical mass or 40 equal-width bins spanning every saved draw; not a fitted density.'}
    from conference_summary import build
    result['posterior']['conferences'] = build(flat, inputs)
    from game_contributions import build as build_games, exact_reader
    result['game_contributions'] = build_games(flat, inputs, score_report, exact_reader(task, score_report, fit_report))
    validate(result)
    return result


def validate(result):
    posterior = result['posterior']
    if posterior.get('reference_rank') != result.get('reference_rank'):
        raise ValueError('Posterior reference rank disagrees with rankings')
    if posterior['schema'] != SCHEMA or set(posterior['teams']) != {str(t['id']) for t in result['teams']}:
        raise ValueError('Invalid posterior roster or schema')
    required_parameters = {'home_adv', 'sigma', 'nu'}
    hierarchical = 'strength_structure' in result.get('identity', {}).get('inputs', {})
    if hierarchical:
        required_parameters |= {'mu_fcs', 'tau_fbs', 'tau_fcs', 'tau_conf'}
    if not required_parameters <= posterior['parameters'].keys():
        raise ValueError('Missing model posterior parameters')
    for team in result['teams']:
        metrics = posterior['teams'][str(team['id'])]
        required = ('strength', 'merit', 'raw_rank', 'sos') if team['status'] == 'ranked' else ('strength',)
        if 'home_prior' in result:
            required += ('home_offset', 'home_total')
        if hierarchical:
            required += ('conference_effect',)
        if any(key not in metrics for key in required):
            raise ValueError('Missing team posterior metric')
        for key in ('merit', 'raw_rank', 'sos'):
            if key in metrics:
                for field, suffix in (('mean', '_mean'), ('median', '_median'), ('sd', '_sd'),
                                      ('q05', '_lo90'), ('q95', '_hi90')):
                    if not math.isclose(metrics[key][field], team[key + suffix], abs_tol=1e-10):
                        raise ValueError('Published posterior summary disagrees with team table')
    summaries = [s for metrics in posterior['teams'].values() for s in metrics.values()]
    summaries += list(posterior['parameters'].values())
    validate_summaries(summaries)
    if 'conferences' in posterior:
        from conference_summary import validate as validate_conferences
        validate_conferences(posterior['conferences'], result['teams'])
    if 'game_contributions' in result:
        from game_contributions import validate as validate_games
        validate_games(result)


def validate_summaries(summaries):
    for s in summaries:
        if type(s['n']) is not int or s['n'] < 2 or s['sd'] < 0:
            raise ValueError('Invalid posterior count or dispersion')
        if not all(math.isfinite(s[k]) for k in ('mean', 'median', 'sd', 'q05', 'q25', 'q75', 'q95')):
            raise ValueError('Nonfinite posterior summary')
        if not s['q05'] <= s['q25'] <= s['median'] <= s['q75'] <= s['q95']:
            raise ValueError('Nonmonotone posterior quantiles')
        h = s['distribution']
        counts = h['counts']
        x = h['edges'] if h['kind'] == 'histogram' else h['x']
        if (h['kind'] not in ('histogram', 'mass') or not counts or
                len(x) != len(counts) + int(h['kind'] == 'histogram') or
                any(type(c) is not int or c < 0 for c in counts) or sum(counts) != s['n'] or
                not all(math.isfinite(v) for v in x) or any(a >= b for a, b in zip(x, x[1:]))):
            raise ValueError('Invalid empirical posterior distribution')
