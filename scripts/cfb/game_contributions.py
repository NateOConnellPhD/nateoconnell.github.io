"""Export additive game credits from checked caches, without sampling or APIs.

The scorer's audit contains weighted marginal means, whereas its published
merit draws use quantile transport. Reconstruct those transported marginals so
game means add to the displayed merit, rather than distributing a residual.
Fit/scoring identities stay unchanged: this is a publication-only summary.
"""
import hashlib
import json
import math

SCHEMA = 'margin-of-merit-game-contributions-v1'


def exact_reader(task, score_report, fit_report):
    """Locate the same checked exact marginals used by fit_saved_season.run."""
    from reference_config import REFERENCE_RANKS, exact_quantities_for
    from sync_data import digest
    import numpy as np
    source = score_report['identity']

    def read(game, game_id):
        identity = {'fit_key': source['fit_key'], 'game_id': game_id,
                    'runner_source': source['exact_runner_source'],
                    'sampling_source': source['exact_sampling_source'],
                    'reference_source': source['reference_source'], 'reference_ranks': list(REFERENCE_RANKS),
                    'scorer_source': source['scorer_source'], 'seed': fit_report['identity']['seed'] + game + 100}
        folder = task / 'exact' / digest(identity)
        report = json.loads((folder / 'report.json').read_text())
        path = folder / 'quantities.npz'
        if (report['identity'] != identity or not report['diagnostics']['sampling_checks_passed']
                or hashlib.sha256(path.read_bytes()).hexdigest() != report['array_sha256']):
            raise ValueError('Game contribution exact-LOO cache integrity check failed')
        with np.load(path, allow_pickle=False) as saved:
            return exact_quantities_for(dict(saved), source['reference_rank'])
    return read


def build(flat, inputs, score_report, read_exact):
    import numpy as np
    from loo_scoring import game_values, reference_strength, log_likelihood, loo_weights, transport
    rank = score_report['identity']['reference_rank']
    reference = reference_strength(flat, rank, inputs['fbs_indices'])
    draws = len(reference)
    audit = {row['game']: row for row in score_report['game_audit']}
    selected = inputs['scored_game_indices']
    if len(audit) != len(score_report['game_audit']) or set(audit) != set(selected):
        raise ValueError('Game contribution audit does not cover the scored games')
    rows = []
    for i in selected:
        game, saved = inputs['games'][i], audit[i]
        if saved['game_id'] != game['id']:
            raise ValueError('Game contribution audit ID mismatch')
        data = {key: [values[i]] for key, values in inputs['data'].items()}
        raw = game_values(flat, data, 0, rank, reference, reference_indices=inputs['fbs_indices'])
        exact = None
        if saved['method'] == 'exact_loo':
            exact = read_exact(i, game['id'])
        elif saved['method'] == 'psis_loo':
            weights, k = loo_weights(log_likelihood(flat, data), score_report['diagnostics']['relative_efficiency'])
            if not np.isfinite(k[0]) or k[0] > score_report['diagnostics']['threshold']:
                raise ValueError('Game contribution requires checked exact LOO quantities')
        else:
            raise ValueError('Unknown game contribution scoring method')
        row = {key: game[key] for key in ('id', 'week', 'start_date', 'home_id', 'away_id',
                                         'home_points', 'away_points', 'neutral_site')}
        for side in ('home', 'away'):
            name = side + '_cdf'
            lost = game[side + '_points'] < game[('away' if side == 'home' else 'home') + '_points']
            if exact is not None:
                values = np.asarray(exact[name])
                if values.ndim != 1 or len(values) < 4 or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
                    raise ValueError('Invalid exact game contribution marginal')
                weighted = float(values.mean()) - lost
                # The rank permutation affects joint coupling, not a game's
                # mean or quantiles. Use exactly the scorer's target quantiles.
                credit = np.quantile(values, (np.arange(draws) + .5) / draws) - lost
            else:
                weighted = float(np.dot(raw[name], weights[0])) - lost
                credit = transport(raw[name], weights[0]) - lost
            if not math.isclose(weighted, saved[side + '_credit'], rel_tol=0, abs_tol=1e-10):
                raise ValueError('Reconstructed contribution disagrees with checked game audit')
            lo, median, hi = np.quantile(credit, [.05, .5, .95])
            row[side + '_credit'] = dict(mean=float(credit.mean()), median=float(median), q05=float(lo), q95=float(hi))
        rows.append(row)
    return {'schema': SCHEMA, 'reference_rank': rank, 'games': rows,
            'interpretation': 'Per-game transported LOO credit. Means sum to total merit; medians and interval endpoints do not. '
                              'Intervals use the same marginal-quantile approximation as the saved merit draws.'}


def validate(result):
    block = result['game_contributions']
    if block.get('schema') != SCHEMA or block.get('reference_rank') != result['reference_rank']:
        raise ValueError('Invalid game contribution schema or reference')
    expected = {g['id']: g for g in result['policy_inputs']['games']}
    games = block['games']
    if len(games) != len(expected) or {g['id'] for g in games} != set(expected):
        raise ValueError('Game contributions do not cover the ranked schedule')
    sums = {t['id']: [] for t in result['teams']}
    for game in games:
        if any(game[key] != expected[game['id']][key] for key in ('home_id', 'away_id', 'home_points', 'away_points')):
            raise ValueError('Game contribution result mismatch')
        if (type(game['week']) is not int or game['week'] < 0 or type(game['neutral_site']) is not bool
                or not isinstance(game['start_date'], str) or game['home_points'] == game['away_points']):
            raise ValueError('Invalid game contribution metadata')
        for side in ('home', 'away'):
            credit = game[side + '_credit']
            won = game[side + '_points'] > game[('away' if side == 'home' else 'home') + '_points']
            low, high = (0, 1) if won else (-1, 0)
            if (not all(math.isfinite(credit[k]) and low <= credit[k] <= high for k in ('mean', 'median', 'q05', 'q95'))
                    or not credit['q05'] <= credit['median'] <= credit['q95']):
                raise ValueError('Invalid game contribution summary')
            if game[side + '_id'] in sums:
                sums[game[side + '_id']].append(credit['mean'])
    for team in result['teams']:
        values = sums[team['id']]
        if (len(values) != team['wins'] + team['losses']
                or not math.isclose(math.fsum(values), team['merit_mean'], rel_tol=0, abs_tol=1e-9)):
            raise ValueError('Game contributions do not sum to published team merit')
