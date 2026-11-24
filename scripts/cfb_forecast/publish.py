"""Independent forecast publication from saved feeds, with no API calls or merit writes."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/cfb'))
from cfb_forecast import inputs as source, model as forecast, export, qb, qb_data
from cfb_forecast.config import CONFIG
from sync_data import digest

TASK = ROOT / '.codex-tmp/cfb-refit'
PUBLIC = ROOT / 'assets/data/cfb/projections'


def source_identity():
    files = [Path(__file__).parent / p for p in ('inputs.py', 'model.py', 'export.py', 'publish.py', 'config.py', 'priors.py', 'home.py', 'qb.py', 'qb_data.py', 'qb_extract.py')] + [ROOT / 'scripts/cfb' / p for p in (
        'historical_home.py', 'home_history_inputs.py', 'season_inputs.py', 'sync_data.py',
        'game_status_corrections.json', 'venue_corrections.json', 'full_fit_retry.py', 'requirements.txt')]
    files += sorted(p for p in (Path(__file__).parent / 'reference').glob('*') if p.suffix in ('.py','.json'))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def request(season, week=None):
    inputs, prior, expectancy, games, observed, training_key = source.load(season, forecast_week=week)
    # Observation timestamps alone do not trigger fitting or publication.
    key = digest({'training_key': training_key, 'prior': prior, 'games': games,
                  'qb': qb_data.identity(season, historical=week is not None), 'source': source_identity()})
    return inputs, prior, expectancy, games, observed, training_key, key


def prepare(season, week=None):
    *_, key = request(season, week)
    index = json.loads((PUBLIC / 'index.json').read_text()) if (PUBLIC / 'index.json').exists() else {}
    needed = not any(r.get('input_key') == key for r in index.get('snapshots', []))
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream: stream.write(f"needs_update={'true' if needed else 'false'}\n")
    print(json.dumps({'season': season, 'needs_update': needed, 'input_key': key, 'api_requests': 0}))


def fit_window(inputs, prior, expectancy, training_key):
    """Shared fitting path for a live refresh or a historical forecast window."""
    from full_fit_retry import checked_full_fit
    from cfb_forecast.home import load_or_estimate
    home = load_or_estimate(inputs, TASK / 'home')
    if not inputs['games']:
        return forecast.prior_arrays(inputs, prior, home), home, {
            'fit_key': 'prior-' + digest(prior), 'fit_reused': True, 'prior_only': True,
            'diagnostics': {'scope': 'Preseason Gaussian approximation; no current-season sampler.', 'sampling_checks_passed': True},
            'noise_rescale': 1., 'efficiency_games': 0, 'efficiency_scale': None}
    target, scale, count = forecast.efficiency_target(inputs['data']['margin'], expectancy)
    identity = {'forecast': CONFIG.identity(), 'training_key': training_key,
        'source': {k:v for k,v in source_identity().items() if not k.endswith(('/export.py','/publish.py'))},
        'home': digest(home), 'gap': prior['fcs_gap'],
        'packages': {p:version(p) for p in ('numpy','scipy','jax','jaxlib','numpyro','arviz')}, 'seed':CONFIG.seed, 'chains':4}
    samples, report, fit_key, reused = checked_full_fit(identity, TASK / 'forecast-fits',
        {'season':inputs['season'], 'week':inputs.get('last_training_week',max(g['week'] for g in inputs['games']))},
        lambda **settings: forecast.fit(inputs, prior, home, prior['fcs_gap'], target, **settings), forecast.diagnose, lambda _: {},
        attempt_settings=forecast.SAMPLING_ATTEMPTS)
    arrays, rescale = forecast.prediction_arrays(samples, inputs, target)
    return arrays, home, {'fit_key':fit_key, 'fit_reused':reused, 'prior_only':False,
        'diagnostics':report['diagnostics'], 'noise_rescale':rescale, 'efficiency_games':count,'efficiency_scale':scale,
        'prior_sd_posterior':float(samples['s_prev'].mean()), 'drift_sd_posterior':float(samples['q'].mean()) if 'q' in samples else 0.}


def make_snapshot(inputs, prior, expectancy, games, observed, key, arrays, home, fit_meta, week=None):
    season = inputs['season']
    teams = [{'id': str(t['id']), 'name': t['name'], 'division': t['classification'], 'conference': t['conference']}
             for t in inputs['teams']]
    home_ids = ['national'] + [str(t) for t in home['fbs_ids']]
    records = {t['id']: [0, 0] for t in teams}
    for g in inputs['games']:
        win = g['home_points'] > g['away_points']
        records[str(g['home_id'])][0 if win else 1] += 1
        records[str(g['away_id'])][1 if win else 0] += 1
    meta = {**fit_meta, 'model': CONFIG.model, 'season': season, 'through_date': max((g['start_date'] for g in inputs['games']), default=observed),
        'observed_at': observed, 'week': max((g['week'] for g in inputs['games']), default=0),
        'input_key': key, 'games_used': len(inputs['games']),
        'source': 'saved-feed fit' if inputs['games'] else 'preseason prior', 'home_years': home['years'],
        'prior_sd': prior['sd'],
        'prior_training_seasons': prior['training_seasons'], 'prior_caveat': prior['caveat'],
        'input_observations': prior.get('input_observations', {}),
        'forecast_week': inputs.get('forecast_week', week), 'historical_reconstruction': week is not None}
    if 'qb' in inputs:
        quarterbacks=inputs['qb']; qt=quarterbacks['teams']
        meta.update(model='forecast-v7-qb', quarterbacks=quarterbacks['meta'])
        games=[{**g,'qb_x_home':qt[g['home']]['x'],'qb_x_away':qt[g['away']]['x'],
            'home_qb':qt[g['home']]['name'],'away_qb':qt[g['away']]['name']} for g in games]
    public, draws = export.build(arrays, teams, home_ids, games, meta, prior['mean_by_id'], records)
    if 'qb' in inputs:
        import numpy as np
        lam=float(np.asarray(arrays['lam']).mean())
        public['quarterbacks']=qt
        public['qb_importance']=[{**r,'importance_pts':lam*r['importance_pts']} for r in quarterbacks['importance']]
        public['meta']['qb_lambda']=lam
        draws['quarterbacks']={key:{'x':v['x'],'starter':v['starter'],
            'options':{p['id']:p['x'] for p in v['options']}} for key,v in qt.items()}
        for r in public['ratings']:
            r.update(qb_now=qt[r['id']]['name'],qb_adjustment=lam*qt[r['id']]['x'])
            r['rating_qb_now']=r['mean']+r['qb_adjustment']
    export.add_details(public, arrays, inputs, prior, home_ids, expectancy)
    return public, draws


def complete(season, week=None):
    inputs, prior, expectancy, games, observed, training_key, key = request(season, week)
    if (PUBLIC / 'index.json').exists():
        index = json.loads((PUBLIC / 'index.json').read_text())
        if any(r['input_key'] == key for r in index['snapshots']): return
    quarterbacks=qb.load(inputs,games,observed,cache=TASK/'qb',historical=week is not None)
    inputs.update(qbx=quarterbacks['training'],qb=quarterbacks)
    training_key=digest({'base':training_key,'qb':quarterbacks['training_key']})
    arrays, home, fit_meta = fit_window(inputs, prior, expectancy, training_key)
    if 'lam' not in arrays and fit_meta.get('prior_only'):
        import numpy as np
        arrays['lam']=np.random.default_rng(CONFIG.seed+1).normal(1.,.5,len(arrays['theta']))
    public, draws = make_snapshot(inputs, prior, expectancy, games, observed, key, arrays, home, fit_meta, week)
    row = export.write(public, draws, PUBLIC)
    print(json.dumps({'published': row, 'fit_reused': fit_meta['fit_reused'], 'api_requests': 0}))
    # Only this isolated forecasting job's cache: keep the current passing fit.
    import shutil
    if (TASK / 'forecast-fits').exists():
        for p in (TASK / 'forecast-fits').iterdir():
            if p.is_dir() and p.name != fit_meta['fit_key']: shutil.rmtree(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'complete', 'build-prior'])
    parser.add_argument('--season', default='current')
    parser.add_argument('--week', type=int, help='Historical forecast week; 99 for CFP')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    from cfb_forecast.refresh import season_for
    season = season_for(now) if args.season == 'current' else int(args.season)
    if args.command == 'build-prior':
        from cfb_forecast.annual import build_live
        build_live(season)
        return
    (prepare if args.command == 'prepare' else complete)(season, args.week)


if __name__ == '__main__': main()
