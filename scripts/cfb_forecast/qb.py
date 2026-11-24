"""Saved-data adapter for the unchanged supplied QBTerm and Gaussian QB model."""
import csv
import importlib
from pathlib import Path
import sys

from . import qb_data
from .refresh import read, write
from sync_data import digest


def term_class():
    # The handoff imports qb_model as a sibling top-level module.
    from .reference import qb_model
    old = sys.modules.get('qb_model'); sys.modules['qb_model'] = qb_model
    try: return importlib.import_module('.reference.qb_term', __package__).QBTerm
    finally:
        if old is None: sys.modules.pop('qb_model',None)
        else: sys.modules['qb_model'] = old


def from_frames(db, fbs, names, season, week, hp):
    """Only replace QBTerm's filesystem constructor; all calculations are supplied methods."""
    import pandas as pd
    from .reference.qb_model import career_before, prepare, solve
    q = term_class().__new__(term_class())
    q.db=db[db.n>0]; q.season=season; q.week=week
    q.cb=career_before(q.db); q.cbl=dict(zip(zip(q.cb.passer_id,q.cb.season),q.cb.career_before))
    q.hp=hp; q.r=solve(prepare(q.db,fbs,cutoff=(season,week),cb=q.cb),hp)
    q.S=q.db[(q.db.season==season)&(q.db.season_type=='regular')&(q.db.week<week)].sort_values(['week','game_id'])
    q.names=pd.Series({int(k):v for k,v in names.items()},dtype=str)
    return q


def load(inputs, games, observed, *, directory=qb_data.DIRECTORY, cache=None, historical=False):
    import numpy as np
    import pandas as pd
    from .reference import qb_model
    season=inputs['season']; week=inputs['forecast_week']
    frames=[]; fbs={}; names={}; observations={}
    for year in range(2021,season+1):
        saved=read(Path(directory)/f'{year}.json')
        if saved is None:
            if year==season and not inputs['games']: continue
            raise ValueError(f'Missing QB dropbacks for {year}; previous forecasts preserved')
        frame=pd.DataFrame(saved['rows'],columns=saved['columns']); qb_data.validate(frame,year)
        if year==season:
            # Do not admit incomplete, rescheduled or later-week games solely
            # because a play-by-play file contains them.
            ids={g['id'] for g in inputs['games']}
            frame=frame[frame.game_id.isin(ids)]
        frames.append(frame); fbs[year]=set(saved['fbs']); names.update(saved['names'])
        observations[str(year)]=saved['observed_at']
    db=pd.concat(frames,ignore_index=True)
    # Hyperparameters are estimated on earlier seasons, exactly as qb_value_fit.py.
    # Daily current-season data updates the conditional Gaussian posterior, not this prior.
    old=db[db.season<season]
    hp_key=digest({'data':old.to_dict('list'),'fbs':{y:sorted(v) for y,v in fbs.items() if y<season},
                  'source':Path(qb_model.__file__).read_text()})
    hp_file=Path(cache)/f'hyper-{season}-{hp_key}.json' if cache else None
    hp=read(hp_file) if hp_file else None
    if hp is None:
        d=qb_model.prepare(db,fbs,cutoff=(season,1))
        hp=qb_model.reml(d,qb_model.pooled_sigma(d))
        if not hp['converged']: raise ValueError('QB REML did not converge; previous forecasts preserved')
        if hp_file: write(hp_file,hp)
    q=from_frames(db,fbs,names,season,week,hp)
    # Align by canonical schedule names; the supplied QB effects are keyed by name.
    current=read(Path(directory)/f'{season}.json',{})
    known=set(db.loc[db.season==season,'pos_team']) | set(current.get('fbs',[]))
    aliases={'Hawaii':"Hawai'i",'San Jose State':'San José State','App State':'Appalachian State',
             'UConn':'Connecticut','UMass':'Massachusetts','Miami (FL)':'Miami'}
    def name(t):
        n=t['name']
        if n in known: return n
        alt=aliases.get(n)
        if alt in known: return alt
        inverse=next((k for k,v in aliases.items() if v==n and k in known),None)
        return inverse or n
    team_names={str(t['id']):name(t) for t in inputs['teams']}
    # Match spelling using game IDs, avoiding silent zero effects for aliases.
    game_names=db[db.season==season].drop_duplicates('game_id').set_index('game_id')
    mapped={}
    for g in inputs['games']:
        if g['id'] not in game_names.index: continue
        row=game_names.loc[g['id']]
        for side in ('home','away'):
            key=str(g[side+'_id']); value=str(row[side])
            if key in mapped and mapped[key]!=value: raise ValueError('Inconsistent QB team names for a saved game')
            mapped[key]=value
    team_names.update(mapped)
    train=pd.DataFrame([{'game_id':g['id'],'week':g['week'],
        'home_team':team_names[str(g['home_id'])],'away_team':team_names[str(g['away_id'])]} for g in inputs['games']],
        columns=['game_id','week','home_team','away_team'])
    x=q.x_training(train,'start')
    if not np.isfinite(x).all(): raise ValueError('Invalid training QB covariate')
    override={}; status_file=Path(directory)/'status'/f'{season}.csv'
    if status_file.exists() and not historical:
        with status_file.open() as stream:
            for row in csv.DictReader(stream):
                if not row.get('passer_id'): continue
                t=row['team']; pid=int(row['passer_id'])
                if t not in team_names.values() or t in override or pid<=0: raise ValueError('Invalid or duplicate QB status team')
                override[t]={'id':pid,'note':row.get('note','')}
    teams={}
    for key,t in team_names.items():
        st=q._team_state(t,week); ov=override.get(t)
        now,pid=q.x_for(t,ov['id'] if ov else None)
        options=[]
        mix=q.S[q.S.pos_team==t].groupby('passer_id').n.sum()
        pids=set(map(int,mix.index)) | ({ov['id']} if ov else set())
        for p in sorted(pids):
            value,_=q.x_for(t,p)
            options.append({'id':str(p),'name':str(q.names.get(p,p)), 'dropbacks':int(mix.get(p,0)),
                'value':float(q.value(p)), 'x':float(value)})
        teams[key]={'starter':str(pid) if pid is not None else None,'name':str(q.names.get(pid,pid)) if pid is not None else None,
            'x':float(now),'source':'status override' if ov else 'last game’s first passer' if st else 'no current-season dropbacks',
            'note':ov['note'] if ov else '', 'options':options,
            'dropbacks_per_game':float(st['nbar']) if st else None,'reference_value':float(st['v_ref']) if st else None}
    available=set(q.S.game_id)
    missing=sorted(set(train.game_id)-available)
    if len(train) and len(missing)==len(train): raise ValueError('QB feed has no games matching the power fit')
    state=read(Path(directory)/'refresh.json',{})
    importance=q.importance(list(team_names.values()),1.).astype(object)
    importance=importance.where(pd.notna(importance),None).to_dict('records')
    by_name={v:k for k,v in team_names.items()}
    for r in importance: r['team_id']=by_name[r['team']]
    return {'training':x.tolist(), 'training_key':digest({'x':x.tolist(),'hp':hp_key}), 'teams':teams,
        'importance':importance,
        'meta':{'observed_at':observations.get(str(season)), 'checked_at':state.get('checked_at'),
            'warnings':state.get('errors',[]), 'missing_training_game_ids':missing,
            'hyperparameter_training_through':season-1,'hyperparameters':hp,
            'starter_rule':'Last game’s first passer unless explicitly overridden; no injury feed.'}}
