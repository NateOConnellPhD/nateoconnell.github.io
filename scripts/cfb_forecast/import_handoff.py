"""One-time export of the supplied 2026 fit; does not execute handoff code or pickle.

usage: python -B scripts/cfb_forecast/import_handoff.py HANDOFF_DIRECTORY
Writes only allowlisted public data and the reviewed preseason prior. No fitting.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

from publish import ROOT, PUBLIC, export, source


def run(folder, public=PUBLIC, priors=source.PRIORS):
    import numpy as np
    folder = Path(folder); year = 2026; out = folder / 'outputs' / str(year)
    meta = json.loads((out / '2026_forecast_run.json').read_text())
    if meta['variant'] != 'V2Le75' or meta['season'] != year or meta['draws'] != 4000:
        raise ValueError('Unexpected handoff model')
    if meta['divergences'] or meta['max_rhat_theta'] > 1.01: raise ValueError('Handoff theta diagnostics failed')
    with np.load(out / '2026_forecast_draws.npz', allow_pickle=False) as saved: z = dict(saved)
    rows = list(csv.DictReader((out / '2026_power_ratings.csv').open()))
    # Stable IDs from the reviewed season roster, names used only at this import boundary.
    from season_inputs import load_inputs
    inputs = load_inputs(year)
    roster = {t['name']: t for t in inputs['teams']}
    if any(str(t) not in roster for t in z['teams']): raise ValueError('Handoff team missing from saved season roster')
    teams = [{'id': str(roster[str(t)]['id']), 'name': str(t), 'division': str(d), 'conference': str(c)}
             for t, d, c in zip(z['teams'], z['division'], z['conference'])]
    if any(t['division'] != roster[t['name']]['classification'] for t in teams): raise ValueError('Handoff membership differs')
    ids = {t['name']: t['id'] for t in teams}
    home_ids = ['national' if str(t) == '__national__' else ids[str(t)] for t in z['home_names']]
    prior = {ids[r['team']]: float(r['preseason_prior']) for r in rows if r['preseason_prior']}
    records = {ids[r['team']]: [int(r['W']), int(r['L'])] for r in rows}
    raw = json.loads((ROOT / f'_cfb_data/seasons/{year}/games.json').read_text())
    from sync_data import instant
    games = source.schedule_rows(raw['payload'], inputs['teams'], instant(raw['retrieved_at']))
    # The fit predates this schedule observation; do not call it a new fit or mix in new results.
    schedule = {int(r['game_id']): r for r in csv.DictReader((folder / 'data/cfbd/cfb_schedules_2026.csv').open())}
    evidence = {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in
                ('2026_forecast_run.json', '2026_forecast_draws.npz', '2026_power_ratings.csv')}
    prior_doc = {'schema': 'cfb-forecast-prior-v1', 'season': year, 'previous_season': year - 1,
        'training_seasons': meta['preseason_regression']['train_seasons'], 'sd': meta['prior_sd_used'],
        'coefficients': meta['preseason_regression']['beta'], 'mean_by_id': prior,
        'caveat': 'The 2026 talent composite was supplied as a mid-November snapshot, not a frozen preseason measurement.',
        'source_hashes': evidence}
    fit_meta = {'season': year, 'through_date': instant(meta['last_completed_kickoff_utc']).isoformat(),
        'observed_at': raw['retrieved_at'], 'week': max(int(g['week']) for g in schedule.values() if g['completed'] == 'TRUE'),
        'games_used': meta['games_used'], 'input_key': 'supplied-' + evidence['2026_forecast_draws.npz'],
        'source': 'supplied research fit', 'source_hashes': evidence,
        'diagnostics': {'max_rhat_theta': meta['max_rhat_theta'], 'divergences': meta['divergences'],
                        'scope': 'Supplied report checks theta R-hat and divergences; full chain diagnostics were not retained.'},
        'home_years': [2023, 2024, 2025], 'prior_sd': meta['prior_sd_used'],
        'prior_sd_posterior': meta['s_prev_posterior'], 'prior_training_seasons': prior_doc['training_seasons'],
        'prior_caveat': prior_doc['caveat'], 'efficiency_scale': meta['efficiency_scale_pts_per_logit']}
    if z['theta'].shape[0] != meta['draws']: raise ValueError('Draw count disagrees with run report')
    public_data, draws = export.build(z, teams, home_ids, games, fit_meta, prior, records)
    row = export.write(public_data, draws, public)
    priors.mkdir(parents=True, exist_ok=True)
    (priors / f'{year}.json').write_text(json.dumps(prior_doc, indent=2, allow_nan=False) + '\n')
    # Aggregate backtest summaries only; do not copy dashboard metadata/code or raw game records.
    track = {}
    for name in ('headline', 'phase_final'):
        track[name] = json.loads((folder / f'dashboard_2026/{name}.json').read_text())['rows']
    (public / 'backtest.json').write_text(json.dumps({'schema': export.SCHEMA, **track}, allow_nan=False) + '\n')
    print(json.dumps({'snapshot': row, 'teams': len(teams), 'games': len(games), 'fit_run': False}))


if __name__ == '__main__': run(Path(sys.argv[1]))
