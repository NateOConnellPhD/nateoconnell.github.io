"""Check PSIS game credits against independent omitted-game NUTS refits.

Research validation only. Uses the approved isolated environment, writes only
under its task directory, and never publishes. Includes the maximum-k game,
first neutral game, and first non-neutral game from the fixed 2024 fixture.
"""
import argparse
import json
from pathlib import Path
import time

# Sets task-only numerical cache paths before imports.
from compare_2024 import TASK
from refit_2024 import FIXTURE_SHA256, describe, read_reference
from model import CANONICAL, fit
import arviz as az
import numpy as np
from loo_scoring import flatten, game_values, log_likelihood, loo_weights


def mcse(values, shape):
    return float(np.asarray(az.mcse({'value': values.reshape(shape)}, method='mean')['value']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handoff', type=Path)
    parser.add_argument('--seed', type=int, default=20261120)
    args = parser.parse_args()
    teams, data = read_reference(args.handoff / '2024_observed_FBS_games_used.csv')
    output = TASK / f'exact-loo-{args.seed}'
    if output.exists():
        raise ValueError('Exact-LOO results already exist; inspect before rerunning')
    folder = TASK / f'canonical-{args.seed}-1000-1000'
    report = json.loads((folder / 'report.json').read_text())
    if report['model_sha256'] != CANONICAL.fingerprint or report['fixture_sha256'] != FIXTURE_SHA256 or not report['diagnostics']['sampling_checks_passed']:
        raise ValueError('Canonical fit provenance or diagnostics failed')
    with np.load(folder / 'posterior.npz', allow_pickle=False) as saved:
        if list(saved['teams']) != teams:
            raise ValueError('Canonical roster mismatch')
        sample = {k: saved[k] for k in ('theta','home_adv','sigma','nu')}
    flat, shape = flatten(sample), sample['nu'].shape
    ll = log_likelihood(flat, data)
    weights, k = loo_weights(ll)
    wrong_weights = np.exp(az.psislw(ll.T, reff=1.)[0])  # Forensic comparison ONLY.
    selected = sorted({int(np.argmax(k)), data['venue'].index(0), data['venue'].index(1)})
    output.mkdir()
    results = []
    for game in selected:
        start = time.monotonic()
        omitted = {name: values[:game] + values[game+1:] for name, values in data.items()}
        sampler = fit(len(teams), **omitted, specification=CANONICAL, seed=args.seed+game+100)
        samples, diagnostics, parameters = describe(sampler)
        if not diagnostics['sampling_checks_passed']:
            raise ValueError(f'Exact refit failed diagnostics for game {game}: {diagnostics}')
        exact = game_values(flatten(samples), data, game)
        original = game_values(flat, data, game)
        row = {'game': game, 'home': teams[data['home'][game]], 'away': teams[data['away'][game]],
               'margin': data['margin'][game], 'venue': data['venue'][game], 'pareto_k': float(k[game]),
               'seed': args.seed+game+100, 'seconds': round(time.monotonic()-start,2),
               'diagnostics': diagnostics, 'quantities': {}}
        for name, values in original.items():
            offset = (int(data['margin'][game] < 0) if name == 'home_cdf' else
                      int(data['margin'][game] > 0) if name == 'away_cdf' else 0)
            mean = float(weights[game] @ values)
            se_psis = mcse(len(values)*weights[game]*(values-mean), shape)
            se_exact = mcse(exact[name], samples['nu'].shape)
            combined = float(np.hypot(se_psis,se_exact))
            row['quantities'][name] = {'psis': mean-offset, 'exact': float(exact[name].mean())-offset,
                'likelihood_weighted': float(wrong_weights[game] @ values)-offset,
                'psis_mcse_approx': se_psis, 'exact_mcse': se_exact,
                'difference_over_combined_mcse': (mean-float(exact[name].mean()))/combined}
        results.append(row)
        (output / f'game-{game}.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
        print(json.dumps(row,allow_nan=False),flush=True)
    (output / 'summary.json').write_text(json.dumps({'model_sha256': CANONICAL.fingerprint,
        'fixture_sha256': FIXTURE_SHA256, 'games': results,
        'limitation': 'Three diagnostic spot checks, not an exact refit of every game. PSIS MCSE uses a ratio-estimator approximation.'},indent=2)+'\n')


if __name__ == '__main__':
    main()
