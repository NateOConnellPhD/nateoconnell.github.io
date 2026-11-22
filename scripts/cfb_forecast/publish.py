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
from cfb_forecast import inputs as source, model as forecast, export
from sync_data import digest

TASK = ROOT / '.codex-tmp/cfb-refit'
PUBLIC = ROOT / 'assets/data/cfb/projections'


def source_identity():
    files = [Path(__file__).parent / p for p in ('inputs.py', 'model.py', 'export.py', 'publish.py')] + [ROOT / 'scripts/cfb' / p for p in (
        'historical_home.py', 'home_history_inputs.py', 'season_inputs.py', 'sync_data.py',
        'game_status_corrections.json', 'venue_corrections.json', 'full_fit_retry.py', 'requirements.txt')]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def request(season):
    inputs, prior, expectancy, games, observed, training_key = source.load(season)
    # Observation timestamps alone do not trigger fitting or publication.
    key = digest({'training_key': training_key, 'games': games, 'source': source_identity()})
    return inputs, prior, expectancy, games, observed, training_key, key


def prepare(season):
    *_, key = request(season)
    index = json.loads((PUBLIC / 'index.json').read_text()) if (PUBLIC / 'index.json').exists() else {}
    latest = next((r for r in index.get('snapshots', []) if r['id'] == index.get('latest')), {})
    needed = latest.get('input_key') != key
    if output := os.environ.get('GITHUB_OUTPUT'):
        with open(output, 'a') as stream: stream.write(f"needs_update={'true' if needed else 'false'}\n")
    print(json.dumps({'season': season, 'needs_update': needed, 'input_key': key, 'api_requests': 0}))


def complete(season):
    inputs, prior, expectancy, games, observed, training_key, key = request(season)
    # The complete command is idempotent too, including manual reruns.
    if (PUBLIC / 'index.json').exists():
        index = json.loads((PUBLIC / 'index.json').read_text())
        if any(r['id'] == index['latest'] and r['input_key'] == key for r in index['snapshots']): return
    from full_fit_retry import checked_full_fit
    from historical_home import load_or_estimate
    target, efficiency_scale, efficiency_games = forecast.efficiency_target(inputs['data']['margin'], expectancy)
    home = load_or_estimate(inputs, TASK / 'home')
    previous, fbs = source.previous_games(season)
    gap_key = digest({'games': previous, 'fbs': sorted(fbs), 'source': source_identity()['scripts/cfb_forecast/model.py']})
    gap_path = TASK / 'forecast-gap' / f'{gap_key}.json'
    if gap_path.exists():
        gap = json.loads(gap_path.read_text())['mean']
    else:
        gap = forecast.previous_division_gap(previous, fbs)
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(json.dumps({'mean': gap}, allow_nan=False) + '\n')
    identity = {'forecast': 'preseason-learned-scale-efficiency75', 'training_key': training_key,
                'source': {k: v for k, v in source_identity().items() if not k.endswith(('/export.py', '/publish.py'))},
                'home': digest(home), 'gap_key': gap_key,
                'packages': {p: version(p) for p in ('numpy', 'scipy', 'jax', 'jaxlib', 'numpyro', 'arviz')},
                'seed': 2026, 'chains': 4}
    samples, report, fit_key, reused = checked_full_fit(identity, TASK / 'forecast-fits',
        {'season': season, 'week': max(g['week'] for g in inputs['games'])},
        lambda **settings: forecast.fit(inputs, prior, home, gap, target, **settings),
        forecast.diagnose, lambda _: {})
    arrays, rescale = forecast.prediction_arrays(samples, inputs, target)
    teams = [{'id': str(t['id']), 'name': t['name'], 'division': t['classification'], 'conference': t['conference']}
             for t in inputs['teams']]
    home_ids = ['national'] + [str(t) for t in home['fbs_ids']]
    records = {t['id']: [0, 0] for t in teams}
    for g in inputs['games']:
        win = g['home_points'] > g['away_points']
        records[str(g['home_id'])][0 if win else 1] += 1
        records[str(g['away_id'])][1 if win else 0] += 1
    meta = {'season': season, 'through_date': max(g['start_date'] for g in inputs['games']),
        'observed_at': observed, 'week': max(g['week'] for g in inputs['games']),
        'input_key': key, 'fit_key': fit_key, 'games_used': len(inputs['games']),
        'source': 'saved-feed fit', 'diagnostics': report['diagnostics'], 'home_years': home['years'],
        'prior_sd': prior['sd'], 'prior_sd_posterior': float(samples['s_prev'].mean()),
        'prior_training_seasons': prior['training_seasons'], 'prior_caveat': prior['caveat'],
        'efficiency_games': efficiency_games, 'efficiency_scale': efficiency_scale, 'noise_rescale': rescale}
    public, draws = export.build(arrays, teams, home_ids, games, meta, prior['mean_by_id'], records)
    row = export.write(public, draws, PUBLIC)
    print(json.dumps({'published': row, 'fit_reused': reused, 'api_requests': 0}))
    # Only this isolated forecasting job's cache: keep the current passing fit.
    import shutil
    for p in (TASK / 'forecast-fits').iterdir():
        if p.is_dir() and p.name != fit_key: shutil.rmtree(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'complete'])
    parser.add_argument('--season', default='current')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    season = now.year - int(now.month < 8) if args.season == 'current' else int(args.season)
    (prepare if args.command == 'prepare' else complete)(season)


if __name__ == '__main__': main()
