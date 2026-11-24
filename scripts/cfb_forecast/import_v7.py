"""Import reviewed public numerical evidence from the private forecast handoff.

Does not run handoff scripts, publish its failed sampler, or copy private files.
The legacy cache is decoded with a two-type allowlist into plain numeric JSON.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import pickle
import sys
from publish import ROOT, source
from cfb_forecast import priors, evaluation


def rows(path):
    with Path(path).open() as f: return list(csv.DictReader(f))


def number(value):
    return None if value in ('', 'NA', None, 'nan') else float(value)


def run(folder):
    import numpy as np
    folder = Path(folder); used = []
    def read(name):
        p = folder / name; used.append(p); return rows(p)
    class NumericCache(pickle.Unpickler):
        def find_class(self, module, name):
            if module in ('numpy._core.multiarray', 'numpy.core.multiarray') and name == 'scalar': return np._core.multiarray.scalar
            if module == 'numpy' and name == 'dtype': return np.dtype
            raise ValueError(f'Unsupported legacy cache type: {module}.{name}')
    path = folder / 'runs/season_ratings_cache.pkl'; used.append(path)
    with path.open('rb') as f: ratings = NumericCache(f).load()
    schedules = {y: read(f'data/cfbd/cfb_schedules_{y}.csv') for y in range(2021, 2027)}
    roster, names = {}, {}
    for y, games in schedules.items():
        roster[str(y)] = {}; names[y] = {}
        for g in games:
            for side in ('home', 'away'):
                key = str(int(g[side+'_id'])); name = g[side+'_team']; names[y][name] = key
                if g[side+'_division'] == 'fbs': roster[str(y)][key] = {'name': name, 'conference': g[side+'_conference']}
    numeric_ratings = {}
    for y in range(2021, 2026):
        r = ratings[y]; keys = {name: names[y][name] for name in r['fbs']}
        numeric_ratings[str(y)] = {k: float(r[k]) for k in ('mu_fcs','tau_fbs','tau_fcs','sigma')}
        numeric_ratings[str(y)].update(fbs=sorted(keys.values()), **{k: {keys[t]: float(r[k][t]) for t in keys} for k in ('mean','var')})
    cov = {str(y): {key: {'talent': None, 'ap_points': 0., 'returning_ppa': None, 'recruiting_points': None,
        'new_coach': False, 'portal_points': 0.} for key in roster[str(y)]} for y in range(2022, 2027)}
    for file, field, value in (
        ('talent_composite_cfbd_2022_2026.csv','talent','talent'), ('ap_preseason_poll_2022_2026.csv','ap_points','ap_points'),
        ('returning_production_cfbd_2022_2026.csv','returning_ppa','percentPPA'),
        ('recruiting_class_cfbd_2022_2026.csv','recruiting_points','recruiting_points'),
        ('coaching_changes_2022_2026.csv','new_coach',None), ('transfer_portal_247_2022_2026.csv','portal_points','points')):
        for r in read('data/preseason/'+file):
            y = int(r['season']); key = str(int(float(r['team_id']))) if r.get('team_id') else names[y].get(r['team'])
            if key not in cov[str(y)]:
                if field == 'recruiting_points' or key in names[y].values(): continue  # known non-FBS row
                raise ValueError(f'Unmatched {y} preseason team: {r["team"]}')
            cov[str(y)][key][field] = True if value is None else number(r[value])
    fcs_ratings, early = {}, []
    for y in range(2021, 2026):
        games = [g for g in schedules[y] if g['completed'] == 'TRUE' and all(g[s+'_division'] in ('fbs','fcs') for s in ('home','away'))
                 and number(g['home_points']) is not None and number(g['away_points']) is not None]
        # The supplied research ridge rating uses all completed DI games.
        teams = sorted({g[s+'_team'] for g in games for s in ('home','away')}); ix = {t:i for i,t in enumerate(teams)}
        X = np.zeros((len(games),len(teams)+1)); margins = []
        for i,g in enumerate(games):
            X[i,ix[g['home_team']]]=1.; X[i,ix[g['away_team']]]=-1.; X[i,-1]=g['neutral_site']!='TRUE'
            margins.append(float(g['home_points'])-float(g['away_points']))
            if y>=2022 and g['season_type']=='regular' and int(g['week'])<=5 and g['home_division']==g['away_division']=='fbs':
                early.append({'season':y,'week':int(g['week']),'season_type':'regular','home':names[y][g['home_team']],
                    'away':names[y][g['away_team']],'neutral':g['neutral_site']=='TRUE','margin':margins[-1]})
        P=np.eye(len(teams)+1)*2.; P[-1,-1]=1e-6
        b=np.linalg.solve(X.T@X+P,X.T@np.array(margins))
        fcs={g[s+'_team'] for g in games for s in ('home','away') if g[s+'_division']=='fcs'}
        fcs_ratings[str(y)]={names[y][t]:float(b[ix[t]]) for t in sorted(fcs)}
    bundle={'schema':'cfb-forecast-evidence-v7','rosters':{k:v for k,v in roster.items() if int(k)>=2022},
        'ratings':numeric_ratings,'covariates':cov,'fcs_ratings':fcs_ratings,'early_games':early,
        'caveats':{'2026':'The supplied 2026 talent composite is a mid-November snapshot, not a frozen preseason measurement. Coaching changes were collected in February; later changes may be missing. Backtests reconstruct past windows with these supplied inputs.'},
        'source_hashes':{str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in used}}
    directory=ROOT/'_cfb_data/forecast_inputs'; directory.mkdir(parents=True,exist_ok=True)
    documents={y:priors.build(bundle,y) for y in range(2023,2027)}
    expected=json.loads((folder/'product/2026_forecast_run.json').read_text())['prior_info']
    d=documents[2026]
    checks={'coefficients':max(abs(d['coefficients'][k]-v) for k,v in expected['v7_regression']['beta'].items()),
            'level_shift':abs(d['level_shift']-expected['level_shift']), 'prior_sd':abs(d['sd']-expected['v2_regression']['s']),
            'fcs_slope':abs(d['fcs_slope']-expected['fcs_slope']), 'fcs_sd':abs(d['fcs_sd']-expected['fcs_spread'])}
    if max(checks.values())>1e-7: raise ValueError(f'Prior replay differs from frozen handoff: {checks}')
    (directory/'evidence.json').write_text(json.dumps(bundle,allow_nan=False,separators=(',',':'))+'\n')
    for y,d in documents.items(): (source.PRIORS/f'{y}.json').write_text(json.dumps(d,allow_nan=False,separators=(',',':'))+'\n')
    # Recalculate aggregate accuracy rather than copying the packet's conclusions.
    def scores(name, year=None):
        result=[]
        for r in read('results/'+name):
            result.append({'season':int(r.get('season') or year), 'game_id':int(r['game_id']), 'week':int(r['week']),
                'phase':r['phase'], 'tier':r['tier'], 'cluster':r['cl'], 'actual':float(r['y']),
                'model':float(r['V7LDe75']), 'opener':float(r['O']), 'close':float(r['L'])})
        return result
    development=scores('scoreboard_games.csv'); current=scores('score2026_games.csv',2026)
    back={'schema':'cfb-forecast-evaluation-v7','development':{by:evaluation.grouped(development,by) for by in ('week','phase','season','tier')},
        'holdout':{by:evaluation.grouped(current,by) for by in ('week','phase','season','tier')}, 'through_week':12,
        'caveat':bundle['caveats']['2026']}
    # Verify every published historical group and clustered SE against the handoff.
    for by in ('phase','season','tier'):
        expected_rows=read('results/scoreboard_'+by+'.csv')
        actual={str(r['group']):r for r in back['development'][by]}
        for e in expected_rows:
            a=actual[e[by]]
            for key,old in [('model_mae','MAE_V7LDe75'),('opener_mae','MAE_opener'),('close_mae','MAE_close'),('difference','V7LDe75_minus_opener'),('se','V7LDe75_minus_opener_se')]:
                if abs(a[key]-float(e[old]))>1e-8: raise ValueError('Backtest scoreboard replay differs')
    public=ROOT/'assets/data/cfb/projections'
    (public/'backtest.json').write_text(json.dumps(evaluation.public_report(back),allow_nan=False,separators=(',',':'))+'\n')
    # Numeric, auditable evaluation records; no embedded dashboard scripts or binaries.
    (directory/'evaluation.json').write_text(json.dumps({'development':development,'holdout':current},allow_nan=False,separators=(',',':'))+'\n')
    print(json.dumps({'prior_replay_absolute_errors':checks,'forecast_seasons':list(documents),'sampler_run':False}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder');run(p.parse_args().folder)
