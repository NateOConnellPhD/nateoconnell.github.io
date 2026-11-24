"""Replay the supplied QB product exactly, then optionally validate its data adapter.

No publishing or network. --values requires the approved parquet reader.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cfb'))
from cfb_forecast import export, qb


def check(folder, values=False):
    import numpy as np
    import pandas as pd
    from scipy.stats import t
    folder=Path(folder); ref=Path(__file__).parent/'reference'
    manifest=json.loads((ref/'provenance.json').read_text())['sha256']
    for name,sha in manifest.items():
        for p in (ref/name,folder/'code'/name):
            if hashlib.sha256(p.read_bytes()).hexdigest()!=sha: raise ValueError(f'Supplied source differs: {p}')
    def csv_rows(path):
        with (folder/path).open() as f: return list(csv.DictReader(f))
    ratings=csv_rows('product/2026_power_ratings.csv'); passers=csv_rows('product/2026_qbs.csv')
    games=csv_rows('product/2026_upcoming_forecasts.csv')
    with np.load(folder/'product/2026_forecast_draws.npz',allow_pickle=False) as s:
        arrays={k:s[k] for k in ('theta','home_values','sigma','nu','lam')}
        teams=[{'id':str(n),'name':str(n),'division':str(d),'conference':str(c)} for n,d,c in zip(s['teams'],s['division'],s['conference'])]
        home=['national']+list(map(str,s['home_names'][1:]))
        public,_=export.build(arrays,teams,home,[],{},{},{})
        by={r['name']:r for r in public['ratings']}
        errors=[]
        for r in ratings:
            a=by[r['team']]
            if a['position']!=int(r['rank']): raise ValueError('Usual-mix power order changed')
            for k,old in [('mean','rating'),('lo80','lo80'),('hi80','hi80'),('lo95','lo95'),('hi95','hi95'),('p_top1','P_rank1')]:
                errors.append(abs(a[k]-float(r[old])))
            p=next((p for p in passers if p['team']==r['team'] and p['incumbent']=='True'),None)
            adj=arrays['lam'].mean()*float(p['x']) if p else 0.
            errors.extend([abs(adj-float(r['qb_adj'])),abs(a['mean']+adj-float(r['rating_qb_now']))])
        # Next-week forecasts use theta directly in the supplied producer.
        next_week=[g for g in games if int(g['week'])==13]
        mapped=[{'id':int(g['game_id']),'home':g['home_team'],'away':g['away_team'],
            'neutral':g['neutral_site'].lower()=='true','qb_x_home':float(g['x_home']),'qb_x_away':float(g['x_away'])} for g in next_week]
        produced,_=export.build(arrays,teams,home,mapped,{},{},{})
        for a,r in zip(produced['games'],next_week):
            errors.extend([abs(a['home_margin']-float(r['spread'])),abs(a['p_home']-float(r['p_home']))])
    if max(errors)>1e-10: raise ValueError(f'QB export drift: {max(errors)}')
    result={'identical_source_files':len(manifest),'ratings':len(ratings),'next_week_games':len(next_week),
            'maximum_export_difference':max(errors),'qb_value_adapter_checked':False}
    if values:
        frames=[pd.read_parquet(folder/f'data/pbp/dropbacks_{y}.parquet') for y in range(2021,2027)]
        fbs={};names={}
        for y in range(2021,2027):
            rows=csv_rows(f'data/cfbd/cfb_schedules_{y}.csv')
            fbs[y]={r[side+'_team'] for r in rows for side in ('home','away') if r[side+'_division']=='fbs'}
            names.update({r['passer_id']:r['name'] for r in csv_rows(f'data/pbp/qb_names_{y}.csv')})
        hp=json.loads((folder/'runs/qb/hyper_2026.json').read_text())
        q=qb.from_frames(pd.concat(frames),fbs,names,2026,13,hp)
        err=[]
        for r in passers:
            pid=int(r['passer_id']); x,_=q.x_for(r['team'],pid)
            err.extend([abs(x-float(r['x'])),abs(q.value(pid)-float(r['value']))])
        if max(err)>1e-9: raise ValueError(f'QB value drift: {max(err)}')
        result.update(qb_value_adapter_checked=True,passers=len(passers),maximum_qb_difference=max(err))
    print(json.dumps(result));return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--values',action='store_true');a=p.parse_args()
    check(a.folder,a.values)
