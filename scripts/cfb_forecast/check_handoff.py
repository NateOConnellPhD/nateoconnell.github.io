"""Compare exported ratings with the supplied handoff, without fitting or publishing."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from publish import ROOT, export, source, forecast


def check(folder):
    import numpy as np
    folder = Path(folder)
    reference = Path(__file__).parent / 'reference'
    manifest = json.loads((reference / 'provenance.json').read_text())['sha256']
    for name, sha in manifest.items():
        for path in (reference / name, folder / 'code' / name):
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError(f'Supplied source changed: {path}')
    with np.load(folder / 'product/2026_forecast_draws.npz', allow_pickle=False) as saved:
        arrays = {k: saved[k] for k in ('theta', 'home_values', 'sigma', 'nu')}
        teams = [dict(id=str(n), name=str(n), division=str(d), conference=str(c))
                 for n,d,c in zip(saved['teams'], saved['division'], saved['conference'])]
        public, _ = export.build(arrays, teams, ['national'] + list(map(str,saved['home_names'][1:])), [], {}, {}, {})
    with (folder / 'product/2026_power_ratings.csv').open() as f:
        expected = {r['team']: r for r in csv.DictReader(f)}
    errors = []
    for row in public['ratings']:
        old = expected[row['name']]
        if row['position'] != int(old['rank']): raise ValueError('Power order changed')
        for actual, original in [('mean','rating'), ('lo95','lo95'), ('hi95','hi95'),
                ('lo80','lo80'), ('hi80','hi80'), ('p_top1','P_rank1'),
                ('p_top4','P_top4'), ('p_top12','P_top12'), ('p_top25','P_top25')]:
            errors.append(abs(row[actual] - float(old[original])))
    if max(errors) > 1e-10: raise ValueError(f'Export changes supplied ratings: {max(errors)}')
    inputs, prior, expectancy, _, _, _ = source.load(2026)
    with (folder / 'data/2026_DI_completed_games_current.csv').open() as f:
        games = {int(r['game_id']):r for r in csv.DictReader(f) if r['season_type']=='regular'}
    if set(games) != {g['id'] for g in inputs['games']}: raise ValueError('Training game IDs differ')
    differences=[]
    for g in inputs['games']:
        r=games[g['id']]
        for key, old in [('week',int(r['week'])),('home_points',float(r['home_points'])),
                         ('away_points',float(r['away_points'])),('neutral_site',r['neutral_site'].lower()=='true')]:
            if g[key] != old: differences.append({'game':g['id'],'field':key,'saved_feed':g[key],'handoff':old})
    _, scale, count = forecast.efficiency_target(inputs['data']['margin'],expectancy)
    info=json.loads((folder / 'product/2026_forecast_run.json').read_text())
    if abs(scale-info['efficiency_scale_pts_per_logit'])>1e-10: raise ValueError('Fitting target scale differs')
    result={'source_files_identical':len(manifest), 'ratings_checked':len(expected),
        'maximum_export_difference':max(errors),'games':len(games),
        'expectancy_games':count,'efficiency_scale':scale,'current_feed_differences':differences,
        'sampler_run':False,'published':False}
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder')
    check(parser.parse_args().folder)
