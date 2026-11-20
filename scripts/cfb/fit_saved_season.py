"""Fit saved season inputs and produce a v2 candidate for review; never publish.

No API calls or downloads. Run in the approved pinned numerical environment.
Fits and LOO scores have separate cache identities so policy-only changes reuse
the existing posterior and merit draws. All disposable output stays in one task.
"""
import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import time

from model import CANONICAL as MODEL, fit
from ranking_policy import CANONICAL as POLICY
from season_inputs import load_inputs
from sync_data import ROOT, digest

TASK = ROOT / '.codex-tmp' / 'cfb-refit'


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hash(name):
    return file_hash(Path(__file__).with_name(name))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def checked_cache(folder, filename):
    report = json.loads((folder / 'report.json').read_text())
    if report['array_sha256'] != file_hash(folder / filename):
        raise ValueError('Cached array failed integrity check: ' + str(folder))
    return report


def run(season, *, through_week=None, as_of=None, seed=20261120, exact_loo=False):
    if season < 2024:
        raise ValueError('Historical protection policy must be selected before pre-2024 ranking runs')
    inputs = load_inputs(season, through_week=through_week, as_of=as_of)
    packages = {name: version(name) for name in ('numpy', 'scipy', 'jax', 'jaxlib', 'numpyro', 'arviz')}
    # Check dependency availability before creating output. Do not install anything.
    for key, leaf in (('XDG_CACHE_HOME', 'cache'), ('MPLCONFIGDIR', 'matplotlib'),
                      ('JAX_COMPILATION_CACHE_DIR', 'jax-cache'), ('TMPDIR', 'tmp')):
        os.environ[key] = str(TASK / leaf)
        (TASK / leaf).mkdir(parents=True, exist_ok=True)
    for key, value in (('JAX_PLATFORMS', 'cpu'), ('MPLBACKEND', 'Agg'),
                       ('OPENBLAS_NUM_THREADS', '1'), ('OMP_NUM_THREADS', '1')):
        os.environ[key] = value
    import numpy as np
    from loo_scoring import score, flatten, game_values
    from ranking_policy import rank_merit
    from refit_2024 import describe, predictive_summary

    started = time.monotonic()
    model_data = {'team_ids': [t['id'] for t in inputs['teams']], 'data': inputs['data']}
    fit_identity = {'model': asdict(MODEL), 'model_source': source_hash('model.py'),
                    'diagnostic_source': source_hash('refit_2024.py'),
                    'model_data_sha256': digest(model_data), 'packages': packages,
                    'seed': seed, 'warmup': 1000, 'draws': 1000, 'chains': 4}
    fit_key = digest(fit_identity)
    fitted = TASK / 'fits' / fit_key
    reused_fit = fitted.exists()
    if reused_fit:
        report = checked_cache(fitted, 'posterior.npz')
        if report['identity'] != fit_identity or not report['diagnostics']['sampling_checks_passed']:
            raise ValueError('Cached fit identity or diagnostics failed; review before rerunning')
        with np.load(fitted / 'posterior.npz', allow_pickle=False) as saved:
            samples = {k: saved[k] for k in ('theta', 'home_adv', 'sigma', 'nu', 'eta_sigma', 'eta_nu')}
    else:
        fitted.mkdir(parents=True)
        sampler = fit(len(inputs['teams']), **inputs['data'], specification=MODEL,
                      seed=seed, warmup=1000, draws=1000)
        samples, diagnostics, parameters = describe(sampler)
        np.savez_compressed(fitted / 'posterior.npz', **samples)
        report = {'identity': fit_identity, 'diagnostics': diagnostics, 'parameters': parameters,
                  'posterior_predictive': predictive_summary(samples, inputs['data'], seed + 1),
                  'array_sha256': file_hash(fitted / 'posterior.npz')}
        write_json(fitted / 'report.json', report)
        if not diagnostics['sampling_checks_passed']:
            raise ValueError('Sampling diagnostics failed; candidate rankings were not created')
    print(json.dumps({'fit_reused': reused_fit, 'diagnostics': report['diagnostics']}), flush=True)

    score_identity = {'fit_key': fit_key, 'posterior_sha256': report['array_sha256'],
                      'scorer_source': source_hash('loo_scoring.py'), 'reference_rank': 25,
                      'exact_loo': exact_loo, 'exact_runner_source': source_hash('fit_saved_season.py') if exact_loo else None,
                      'game_ids': [g['id'] for g in inputs['games']]}
    score_key = digest(score_identity)
    scored_folder = TASK / 'scores' / score_key
    reused_score = scored_folder.exists()
    if reused_score:
        score_report = checked_cache(scored_folder, 'merit.npz')
        if score_report['identity'] != score_identity:
            raise ValueError('Cached scorer identity failed')
        with np.load(scored_folder / 'merit.npz', allow_pickle=False) as saved:
            merit, sos = saved['merit'], saved['sos']
    else:
        def refit_game(game):
            ident = {'fit_key': fit_key, 'game_id': inputs['games'][game]['id'],
                     'runner_source': source_hash('fit_saved_season.py'),
                     'scorer_source': source_hash('loo_scoring.py'), 'seed': seed + game + 100}
            folder = TASK / 'exact' / digest(ident)
            if folder.exists():
                saved_report = checked_cache(folder, 'quantities.npz')
                if saved_report['identity'] != ident or not saved_report['diagnostics']['sampling_checks_passed']:
                    raise ValueError('Exact LOO cache validation failed')
                with np.load(folder / 'quantities.npz', allow_pickle=False) as saved:
                    return dict(saved)
            print(json.dumps({'exact_loo_game': ident['game_id']}), flush=True)
            omitted = {key: values[:game] + values[game+1:] for key, values in inputs['data'].items()}
            sampler = fit(len(inputs['teams']), **omitted, specification=MODEL,
                          seed=ident['seed'], warmup=1000, draws=1000)
            exact_samples, diagnostics, _ = describe(sampler)
            if not diagnostics['sampling_checks_passed']:
                raise ValueError('Exact LOO failed sampling diagnostics; last published ranking is preserved')
            quantities = game_values(flatten(exact_samples), inputs['data'], game)
            folder.mkdir(parents=True)
            np.savez_compressed(folder / 'quantities.npz', **quantities)
            write_json(folder / 'report.json', {'identity': ident, 'diagnostics': diagnostics,
                       'array_sha256': file_hash(folder / 'quantities.npz')})
            return quantities

        scored = score(samples, inputs['data'], exact_refitter=refit_game if exact_loo else None)
        merit, sos = scored['merit'], scored['sos']
        scored_folder.mkdir(parents=True)
        np.savez_compressed(scored_folder / 'merit.npz', merit=merit, sos=sos)
        score_report = {'identity': score_identity, 'diagnostics': scored['diagnostics'],
                        'game_audit': [{**row, 'game_id': inputs['games'][row['game']]['id']} for row in scored['audit']],
                        'array_sha256': file_hash(scored_folder / 'merit.npz')}
        write_json(scored_folder / 'report.json', score_report)
    result = rank_merit(inputs['teams'], inputs['games'], merit, season=season)
    index = {t['id']: i for i, t in enumerate(inputs['teams'])}
    for row in result['teams']:
        values = sos[:, index[row['id']]]
        row['sos_mean'] = float(values.mean()) if row['status'] == 'ranked' else None
        row['sos_lo90'] = float(np.quantile(values, .05)) if row['status'] == 'ranked' else None
        row['sos_hi90'] = float(np.quantile(values, .95)) if row['status'] == 'ranked' else None
    ranking_identity = {'score_key': score_key, 'merit_sha256': score_report['array_sha256'],
                        'policy': asdict(POLICY), 'policy_source': source_hash('ranking_policy.py'),
                        'input_preparation_source': source_hash('season_inputs.py'),
                        'runner_source': source_hash('fit_saved_season.py'),
                        'inputs': {k: v for k, v in inputs.items() if k not in ('data', 'games', 'teams')}}
    result.update(identity=ranking_identity, season=season, status='candidate_for_review',
                  sampling_diagnostics=report['diagnostics'], loo_diagnostics=score_report['diagnostics'],
                  data_cutoff=inputs['cutoff'], games=len(inputs['games']))
    output = TASK / 'rankings' / digest(ranking_identity)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / 'candidate.json', result)
    print(json.dumps({'candidate': str(output / 'candidate.json'), 'fit_reused': reused_fit,
                      'scores_reused': reused_score, 'seconds': round(time.monotonic() - started, 2),
                      'publication_ready': False}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--through-week', type=int)
    parser.add_argument('--as-of', help='ISO8601 timestamp with timezone; at or before saved data observation')
    parser.add_argument('--seed', type=int, default=20261120)
    parser.add_argument('--exact-loo', action='store_true', help='Refit and diagnose games with unreliable PSIS')
    run(**vars(parser.parse_args()))


if __name__ == '__main__':
    main()
