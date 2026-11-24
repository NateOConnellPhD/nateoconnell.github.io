"""Daily public injury/roster observations and explicitly inferred QB replacements.

No depth-chart claims, news-text inference, team overrides, or model changes.
Only current ESPN observations are refreshed; historical fits never use them.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'scripts/cfb'))
from cfb_forecast.refresh import read, write, season_for
from sync_data import digest, NoRedirect

BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football'
DIRECTORY = ROOT/'_cfb_data/forecast_inputs/qb'
RULE = ('Incumbent unless reported out; replacements inferred from recent QB participation. '
        'Questionable or doubtful does not automatically replace the incumbent.')
OUT = {'out', 'out for season', 'injured reserve', 'suspended'}
UNCERTAIN = {'questionable', 'doubtful', 'day-to-day'}


def clean_name(value):
    """Names are display metadata; an athlete ID is never a substitute."""
    if not isinstance(value, str): return None
    value = ' '.join(value.split())
    if value.lower() in {'unknown','unknown player','unavailable','name unavailable',
                         'n/a','na','nan','none','null','tbd','qb'}: return None
    if not any(c.isalpha() for c in value): return None
    if re.fullmatch(r'(?:player|passer|qb)\s*\d+', value, re.I): return None
    try: float(value)
    except ValueError: return value
    return None


def athlete_name(athlete):
    return (clean_name(athlete.get('displayName')) or clean_name(athlete.get('fullName'))
            or clean_name(' '.join(str(athlete.get(k) or '') for k in ('firstName','lastName'))))


def name_catalog(season, state, directory=DIRECTORY):
    """Join names by athlete ID without copying current status into old forecasts."""
    names = {}
    def merge(values):
        for pid, value in values.items():
            name = clean_name(value)
            if str(pid).isdigit() and name: names[str(pid)] = name
    for year in range(2021, season+1):
        merge(read(Path(directory)/f'{year}.json',{}).get('names',{}))
    if state.get('season') == season:
        for rows in state.get('injuries',{}).values():
            merge({p:r.get('name') for p,r in rows.items()})
        for team in state.get('teams',{}).values():
            merge({p:r.get('name') for p,r in team.get('players',{}).items()})
    return names


def fetch(url):
    if urlsplit(url).netloc != 'site.api.espn.com' or not url.startswith(BASE+'/'):
        raise ValueError('Unexpected availability source')
    request = urllib.request.Request(url, headers={'User-Agent':'nateoconnell.com daily forecast refresh'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        body = response.read(4*1024*1024+1)
    if len(body)>4*1024*1024: raise ValueError('Availability response exceeds 4 MB')
    return json.loads(body)


def player_id(athlete):
    direct = str(athlete.get('id', ''))
    if direct.isdigit() and int(direct)>0: return direct
    for link in athlete.get('links', []):
        match = re.search(r'/id/(\d+)', link.get('href', ''))
        if match: return match[1]
    match = re.search(r'/(\d+)\.png', athlete.get('headshot', {}).get('href', ''))
    return match[1] if match else None


def injury_rows(payload):
    if not isinstance(payload,dict): raise ValueError('Malformed injury response')
    if not isinstance(payload.get('injuries'), list): raise ValueError('Injury feed has no injuries list')
    result = {}
    for team in payload['injuries']:
        tid = str(team.get('id', ''))
        if not tid.isdigit() or not isinstance(team.get('injuries'), list): raise ValueError('Malformed injury team')
        rows = {}
        for row in team['injuries']:
            athlete = row.get('athlete', {})
            position = athlete.get('position', {}).get('abbreviation')
            if position and position != 'QB': continue
            pid = player_id(athlete)
            if not pid: raise ValueError('Cannot identify injured quarterback for team '+tid)
            status = str(row.get('status') or '').strip().lower()
            status = {'o':'out','ir':'injured reserve','day to day':'day-to-day'}.get(status,status)
            if not status: raise ValueError('Injury status missing for player '+pid)
            item = {'id':pid,'name':athlete_name(athlete),'status':status,
                    'reported_at':row.get('date'),'return_date':row.get('details',{}).get('returnDate')}
            if pid in rows and rows[pid]!=item: raise ValueError('Conflicting injury records for '+pid)
            rows[pid] = item
        result[tid] = rows
    return result


def roster_rows(payload, team, season):
    if not isinstance(payload,dict): raise ValueError('Malformed roster response')
    if str(payload.get('team',{}).get('id',team)) != str(team): raise ValueError('Roster team mismatch')
    year = payload.get('season',{}).get('year')
    if year is not None and int(year)!=season: raise ValueError('Roster season mismatch')
    groups = payload.get('athletes')
    if not isinstance(groups,list): raise ValueError('Roster has no athlete groups')
    players = {}
    for group in groups:
        for p in group.get('items',[]):
            if p.get('position',{}).get('abbreviation')!='QB': continue
            pid = player_id(p)
            name = athlete_name(p)
            if not pid or not name: raise ValueError('Unidentified roster QB')
            players[pid] = {'id':pid,'name':name}
    if not players: raise ValueError('Roster has no quarterbacks')
    return players


def refresh(season, team_ids, *, directory=DIRECTORY, now=None, fetcher=fetch, pause=time.sleep):
    now = now or dt.datetime.now(dt.timezone.utc)
    if season != season_for(now): return None  # Do not attach today's statuses to an archived year.
    stamp = now.isoformat(); path = Path(directory)/'availability.json'
    state = read(path, {})
    if state.get('season')!=season: state = {'season':season,'teams':{},'injuries':{}}
    ids = list(dict.fromkeys(str(t) for t in team_ids))
    if any(not t.isdigit() for t in ids) or len(ids)>400: raise ValueError('Invalid roster team list')
    if state.get('checked_at','')[:10]==stamp[:10] and not state.get('errors') and set(ids)<=set(state['teams']):
        return state
    errors = []
    try:
        injuries = injury_rows(fetcher(BASE+'/injuries'))
        # Empty in-season league responses must not silently clear known injuries.
        if not injuries and state.get('injuries'): raise ValueError('Empty injury feed; retaining previous reports')
        state.update(injuries=injuries,injuries_observed_at=stamp)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        errors.append('Injuries: '+str(error))
    failures = 0; deadline = time.monotonic()+300
    for tid in ids:
        if failures>=3 or time.monotonic()>deadline:
            errors.append('Remaining rosters deferred after repeated failures or five-minute refresh limit')
            break
        old = state['teams'].get(tid,{})
        if old.get('checked_at','')[:10]==stamp[:10] and not old.get('error'): continue
        pause(.3)
        try:
            roster = roster_rows(fetcher(BASE+f'/teams/{tid}/roster?limit=500'),tid,season)
            state['teams'][tid] = {'players':roster,'observed_at':stamp,'checked_at':stamp}
            failures = 0
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            state['teams'][tid] = {**old,'checked_at':stamp,'error':str(error)}
            errors.append(f'Roster {tid}: {error}')
            failures += 1
    state.update(schema='qb-availability-v1',checked_at=stamp,errors=errors,starter_rule=RULE)
    write(path,state)
    return state


def identity(season, directory=DIRECTORY):
    state = read(Path(directory)/'availability.json',{})
    if state.get('season')!=season: return None
    # New observations without changed content do not produce new forecasts/fits.
    return digest({'season':season,'injuries':state.get('injuries',{}),
        'rosters':{t:v.get('players',{}) for t,v in state.get('teams',{}).items()},
        'errors':state.get('errors',[])})


def resolve(incumbent, recent, roster, injuries):
    """recent is latest appearance first, then dropbacks; no generic WR trick-pass backup."""
    incumbent = str(incumbent) if incumbent is not None else None
    report = injuries.get(incumbent,{})
    status = report.get('status','not listed')
    if status not in OUT:
        return {'starter':incumbent,'uncertain':incumbent is None or status in UNCERTAIN,'replaced':False,
                'note':f'Incumbent status: {status}. Not listed does not confirm health.'}
    available = [str(p) for p in recent if str(p)!=incumbent and str(p) in roster
                 and injuries.get(str(p),{}).get('status') not in OUT]
    if not available:
        return {'starter':None,'uncertain':True,'replaced':True,
                'note':'Incumbent reported '+status+'; no replacement supported by recent QB participation.'}
    replacement = available[0]
    return {'starter':replacement,'uncertain':injuries.get(replacement,{}).get('status') in UNCERTAIN,
            'replaced':True,'note':'Incumbent reported '+status+'. Replacement inferred from most recent QB participation, not a confirmed depth chart.'}


def apply(q, teams, team_names, season, directory=DIRECTORY):
    """Apply live observations only AFTER the historical covariates have been calculated."""
    state = read(Path(directory)/'availability.json',{})
    names = name_catalog(season,state,directory)
    for pid, name in names.items(): q.names.loc[int(pid)] = name
    for info in teams.values():
        for option in info['options']:
            option['name'] = names.get(option['id']) or clean_name(option.get('name'))
        info['name'] = names.get(info['starter']) or clean_name(info.get('name'))
    if state.get('season')!=season: return {'warnings':['No current availability observation'], 'starter_rule':RULE}
    for tid, info in teams.items():
        record = state.get('teams',{}).get(tid,{})
        roster = record.get('players',{})
        injuries = state.get('injuries',{}).get(tid,{})
        prev = q.S[q.S.pos_team==team_names[tid]]
        # Later appearance first; among passers in that game prefer the largest role.
        recent = prev.sort_values(['week','game_id','n'],ascending=False).passer_id.drop_duplicates().tolist()
        decision = resolve(info['starter'],recent,roster,injuries)
        options = {p['id']:p for p in info['options']}
        for pid,player in roster.items():
            p = int(pid)
            if pid not in options:
                options[pid] = {'id':pid,'name':names.get(pid),'dropbacks':0,
                               'value':float(q.value(p)),'x':float(q.x_for(team_names[tid],p)[0])}
        for pid,option in options.items():
            option.update(name=names.get(pid) or clean_name(option.get('name')),
                          status=injuries.get(pid,{}).get('status','not listed'),is_qb=pid in roster if roster else None)
        selected = decision['starter']
        if decision['replaced'] and selected is None:
            # No evidence for which unplayed QB would start. Leave the usual-mix
            # baseline explicit instead of silently continuing with a known-out QB.
            value = 0.
        else: value = float(options[selected]['x']) if selected in options else info['x']
        source = ('Inferred replacement · ESPN injuries and recent QB participation' if selected else 'Replacement unresolved · ESPN injuries') if decision['replaced'] else 'Incumbent · recent first passer, checked against ESPN injuries'
        stale = any(e.startswith('Injuries:') for e in state.get('errors',[])) or record.get('error') or not state.get('injuries_observed_at')
        note = decision['note']
        if not selected: note += ' Forecast uses the usual passer mix until a starter can be inferred.'
        if stale: note += ' A source check failed; retained observations may be stale.'
        info.update(starter=selected,name=options.get(selected,{}).get('name'),x=value,
                    options=list(options.values()),source=source,note=note,uncertain=decision['uncertain'],
                    checked_at=state.get('injuries_observed_at'),sources=[BASE+'/injuries',BASE+f'/teams/{tid}/roster?limit=500'])
    return {'availability_checked_at':state.get('checked_at'),
            'availability_observed_at':state.get('injuries_observed_at'),
            'warnings':state.get('errors',[]),'starter_rule':RULE}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--season',default='current');a=p.parse_args()
    now=dt.datetime.now(dt.timezone.utc);year=season_for(now) if a.season=='current' else int(a.season)
    if year!=season_for(now): return
    normalized=read(ROOT/f'_cfb_data/seasons/{year}/normalized.json',{})
    teams=normalized.get('teams') or read(ROOT/f'_cfb_data/seasons/{year}/teams.json',{}).get('payload',[])
    if not teams: raise ValueError('No saved teams for daily availability refresh')
    next_teams=set()
    for game in normalized.get('games',[]):
        kickoff=dt.datetime.fromisoformat(game['start_date'].replace('Z','+00:00'))
        if not game['completed'] and now<kickoff<=now+dt.timedelta(days=8):
            next_teams.update([str(game['home_id']),str(game['away_id'])])
    teams=sorted(teams,key=lambda t:(str(t['id']) not in next_teams,t.get('classification')!='fbs',int(t['id'])))
    state=refresh(year,[t['id'] for t in teams],now=now)
    public=ROOT/'assets/data/cfb/projections/qb-status.json'
    current=read(public,{})
    current.update(availability_checked_at=state['checked_at'],availability_observed_at=state.get('injuries_observed_at'),
                   availability_warnings=state['errors'],starter_rule=RULE,
                   names=name_catalog(year,state))
    write(public,current)
    print(json.dumps({'availability_checked_at':state['checked_at'],'rosters':len(state['teams']),
                      'warnings':state['errors']}))


if __name__=='__main__': main()
