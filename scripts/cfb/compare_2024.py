"""Compare the three reference fits without publishing or modifying the handoff."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import time

from refit_2024 import FIXTURE_SHA256, TASK, VARIANTS, read_reference

for key, leaf in (("XDG_CACHE_HOME", "cache"), ("MPLCONFIGDIR", "matplotlib"),
                  ("JAX_COMPILATION_CACHE_DIR", "jax-cache"), ("TMPDIR", "tmp")):
    os.environ[key] = str(TASK / leaf)
os.environ['MPLBACKEND'] = 'Agg'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import arviz as az
import numpy as np
from loo_scoring import aggregate_credits, flatten, log_likelihood, score
from reference_policy import ReferencePolicy


def summarize(teams, policy, scored, shape):
    merit, sos = scored['merit'], scored['sos']
    completed = policy.completed(scored['flat'])
    point, ranks = policy.ranks(merit, completed)
    mcse = np.asarray(az.mcse({'merit': merit.reshape(*shape, len(teams))}, method='mean')['merit'])
    rows = []
    for i, team in enumerate(teams):
        row = {'team': team, 'wins_fbs': int(policy.wins[i]), 'losses_fbs': int(policy.losses[i]),
               'rank': int(point[i]), 'merit': float(merit[:, i].mean()), 'merit_mcse': float(mcse[i]),
               'merit_lo90': float(np.quantile(merit[:, i], .05)), 'merit_hi90': float(np.quantile(merit[:, i], .95)),
               'rank_mean': float(ranks[:, i].mean()), 'rank_lo90': float(np.quantile(ranks[:, i], .05)),
               'rank_hi90': float(np.quantile(ranks[:, i], .95)),
               'sos': float(sos[:, i].mean()), 'sos_lo90': float(np.quantile(sos[:, i], .05)),
               'sos_hi90': float(np.quantile(sos[:, i], .95))}
        row.update({f'p_top{k}': float(np.mean(ranks[:, i] <= k)) for k in (8, 10, 25)})
        rows.append(row)
    for k in (8, 10, 25):
        if not np.isclose(sum(r[f'p_top{k}'] for r in rows), k):
            raise ValueError('Posterior top-K probabilities do not sum to K')
    for a, b in policy.edges:
        if not np.all(ranks[:, a] < ranks[:, b]):
            raise ValueError('An active equal-record precedence rule was violated')
    return sorted(rows, key=lambda r: r['rank'])


def differences(a, b):
    lookup = {r['team']: r for r in b}
    changes = []
    for row in a:
        prev = lookup[row['team']]
        se = float(np.hypot(row['merit_mcse'], prev['merit_mcse']))
        changes.append({'team': row['team'], 'rank_a': row['rank'], 'rank_b': prev['rank'],
                        'rank_change_a_minus_b': row['rank'] - prev['rank'],
                        'merit_change_a_minus_b': row['merit'] - prev['merit'], 'combined_mcse': se,
                        'merit_change_over_combined_mcse': (row['merit'] - prev['merit']) / se if se else None})
    return {'rank_changes': [r for r in changes if r['rank_change_a_minus_b']],
            'max_absolute_rank_change': max(abs(r['rank_change_a_minus_b']) for r in changes),
            'max_absolute_merit_change': max(abs(r['merit_change_a_minus_b']) for r in changes),
            'max_absolute_sos_change': max(abs(r['sos'] - lookup[r['team']]['sos']) for r in a),
            'max_absolute_merit_interval_width_change': max(abs((r['merit_hi90'] - r['merit_lo90']) -
                (lookup[r['team']]['merit_hi90'] - lookup[r['team']]['merit_lo90'])) for r in a),
            'max_absolute_rank_interval_width_change': max(abs((r['rank_hi90'] - r['rank_lo90']) -
                (lookup[r['team']]['rank_hi90'] - lookup[r['team']]['rank_lo90'])) for r in a),
            'top_k_membership_identical': {str(k): {r['team'] for r in a if r['rank'] <= k} ==
                 {r['team'] for r in b if r['rank'] <= k} for k in (8, 10, 25)},
            'max_probability_change': {str(k): max(abs(r[f'p_top{k}'] - lookup[r['team']][f'p_top{k}']) for r in a)
                                       for k in (8, 10, 25)}, 'team_changes': changes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('handoff', type=Path)
    parser.add_argument('--seed', type=int, default=20261120)
    args = parser.parse_args()
    output = TASK / f'comparison-{args.seed}'
    if output.exists():
        raise ValueError('Comparison output already exists; inspect it before rerunning')
    teams, data = read_reference(args.handoff / '2024_observed_FBS_games_used.csv')
    # The fixed, hash-verified archive explicitly protects Oregon at 12–0.
    # This reproduces that comparison case; it is not a historical P4 roster.
    policy = ReferencePolicy(teams, data, protected={teams.index('Oregon')})
    if (policy.wins[teams.index('Oregon')], policy.losses[teams.index('Oregon')]) != (12, 0):
        raise ValueError('Reference protection does not match the archived fixture')
    started = time.monotonic()
    rankings, reports, provenance = {}, {}, {}
    for name, specification in VARIANTS.items():
        folder = TASK / f'{name}-{args.seed}-1000-1000'
        report = json.loads((folder / 'report.json').read_text())
        if (report['model_sha256'] != specification.fingerprint or report['fixture_sha256'] != FIXTURE_SHA256
                or not report['diagnostics']['sampling_checks_passed']):
            raise ValueError('Fit provenance or sampling diagnostics failed: ' + name)
        with np.load(folder / 'posterior.npz', allow_pickle=False) as archive:
            if list(archive['teams']) != teams:
                raise ValueError('Fit team order differs from the fixture')
            samples = {k: archive[k] for k in ('theta', 'home_adv', 'sigma', 'nu')}
        scored = score(samples, data)
        rankings[name] = summarize(teams, policy, scored, samples['nu'].shape)
        reports[name] = {'sampling': report['diagnostics'], 'parameters': {k: report['parameters'][k] for k in ('home_adv','sigma','nu')},
                         'fit_seconds': report['seconds'], 'loo': scored['diagnostics'], 'game_audit': scored['audit']}
        provenance[name] = hashlib.sha256((folder / 'posterior.npz').read_bytes()).hexdigest()
        print(name, 'top 8:', ', '.join(r['team'] for r in rankings[name][:8]), flush=True)
    reference = args.handoff / 'continuous_margin_2024'
    with np.load(reference / 'continuous_HMC_2024.npz', allow_pickle=False) as archive:
        if list(archive['teams']) != teams:
            raise ValueError('Archive team order mismatch')
        c, d = archive['chains'].shape[:2]
        samples = {k: archive[k].reshape((c, d) + archive[k].shape[1:]) for k in ('theta', 'home_adv', 'sigma', 'nu')}
    scored = score(samples, data, reff=1.)  # Match archived PSIS setting for implementation parity.
    rankings['archive-draws-corrected-loo'] = summarize(teams, policy, scored, (c, d))
    # Forensic reproduction ONLY: multiplying by likelihood counts a game again
    # instead of removing it. Never expose this target as a model variant.
    flat = flatten(samples)
    wrong_weights = np.exp(az.psislw(log_likelihood(flat, data).T, reff=1.)[0])
    reproduced = aggregate_credits(flat, data, wrong_weights)
    rankings['archive-likelihood-weighted-reproduction'] = summarize(teams, policy, reproduced, (c, d))
    with (reference / '2024_continuous_margin_merit_134.csv').open() as f:
        saved = {r['team']: r for r in csv.DictReader(f)}
    parity = {'rank_mismatches': sum(r['rank'] != int(saved[r['team']]['rank_continuous']) for r in rankings['archive-likelihood-weighted-reproduction']),
              'max_merit_difference': max(abs(r['merit'] - float(saved[r['team']]['merit_continuous'])) for r in rankings['archive-likelihood-weighted-reproduction'])}
    if parity['rank_mismatches'] or parity['max_merit_difference'] > 1e-3:
        raise ValueError('Archived scoring reproduction failed: ' + json.dumps(parity))
    output.mkdir()
    for name, rows in rankings.items():
        with (output / f'{name}.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = {'status': 'research_comparison_not_published', 'fixture_sha256': FIXTURE_SHA256,
               'fit_sha256': provenance,
               'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ('loo_scoring.py','reference_policy.py','compare_2024.py')},
               'archive_parity': parity, 'fits': reports,
               'weight_direction_correction_same_draws': differences(rankings['archive-draws-corrected-loo'], rankings['archive-likelihood-weighted-reproduction']),
               'canonical_vs': {name: differences(rankings['canonical'], rows) for name, rows in rankings.items() if name != 'canonical'},
               'policy_audit': policy.audit, 'seconds': round(time.monotonic() - started, 2),
               'limitations': ['Joint LOO rank intervals use marginal-quantile transport, not an exact joint posterior.',
                               'Archived final-season cycle/protection policy held fixed to isolate the scale-prior comparison.',
                               'Monte Carlo standard errors are reported; smaller differences require care.']}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'output': str(output), 'archive_parity': parity, 'seconds': summary['seconds']}))


if __name__ == '__main__':
    main()
