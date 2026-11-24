"""Daily, bounded input collection. Statistical definitions stay in the handoff.

Live covariates are separate from the frozen research evidence and historical
priors. Failed feeds retain their last usable values and report their age.
"""
import argparse
import copy
import datetime as dt
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/cfb'))
from sync_data import DATA, NoRedirect, digest, encoded, instant, sync

DIRECTORY = ROOT / '_cfb_data/forecast_inputs'
FIELDS = ('talent', 'returning_ppa', 'recruiting_points', 'ap_points', 'portal_points', 'new_coach')


def prior_builder_key():
    folder=Path(__file__).parent
    files=('priors.py','annual.py','config.py','reference/forecast_model.py','reference/priors_v7.py')
    return digest({name:digest((folder/name).read_text()) for name in files})


def needs_prior(status, prior):
    return bool(status.get('covariates_ready')) and (prior.get('live_input_key') != status.get('covariate_key')
        or prior.get('builder_key') != prior_builder_key())


def season_for(now):
    # Start checking next season in July; unavailable inputs are never invented.
    return now.year - int(now.month < 7)


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else copy.deepcopy(default)


def write(path, value):
    body = encoded(value)
    if not path.exists() or path.read_bytes() != body:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def fetch_url(url, key=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('api.collegefootballdata.com', '247sports.com', 'collegepollarchive.com'):
        raise ValueError('Unsupported forecast data host')
    headers = {'User-Agent': 'nateoconnell.com forecast input refresh'}
    if key:
        if parsed.netloc != 'api.collegefootballdata.com': raise ValueError('Credential host mismatch')
        headers['Authorization'] = 'Bearer ' + key
    try:
        with urllib.request.build_opener(NoRedirect()).open(urllib.request.Request(url, headers=headers), timeout=30) as response:
            body = response.read(8 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as e:
        raise ValueError(f'{parsed.netloc} HTTP {e.code}') from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise ValueError(f'{parsed.netloc} unavailable') from None
    if len(body) > 8 * 1024 * 1024: raise ValueError('Input response exceeds 8 MB')
    return body.decode('utf-8')


def fetch_cfbd(endpoint, parameters, key):
    allowed = ('/talent', '/player/returning', '/recruiting/teams', '/rankings', '/coaches', '/coaches/tenures')
    if endpoint not in allowed: raise ValueError('Unsupported forecast endpoint')
    try:
        rows = json.loads(fetch_url('https://api.collegefootballdata.com' + endpoint + '?' + urllib.parse.urlencode(parameters), key))
    except json.JSONDecodeError: raise ValueError('CFBD returned invalid JSON') from None
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f'{endpoint}: no usable records yet')
    return rows


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('Invalid numeric covariate')
    return float(value)


def names_for(teams):
    names = {}
    for t in teams:
        for name in [t['school']] + (t.get('alternateNames') or []):
            if not name: continue
            key = name.casefold().strip()
            if key in names and names[key] != str(t['id']): raise ValueError('Ambiguous team alias')
            names[key] = str(t['id'])
    aliases = {'miami (fl)': 'Miami', 'miami (oh)': 'Miami (OH)', 'ole miss': 'Ole Miss',
               'mississippi': 'Ole Miss', 'uconn': 'UConn', 'nc state': 'NC State',
               'san jose state': 'San José State', 'hawaii': "Hawai'i", 'umass': 'Massachusetts', 'connecticut':'UConn'}
    for alias, name in aliases.items():
        if name.casefold() in names: names.setdefault(alias, names[name.casefold()])
    return names


def mapped(rows, names, season, field, minimum=100):
    result = {}
    for r in rows:
        if r.get('year', r.get('season', season)) != season: raise ValueError('Covariate belongs to another season')
        key = names.get(str(r.get('team', '')).casefold().strip())
        if key is None: continue  # Recruiting also includes non-FBS teams.
        if key in result: raise ValueError('Duplicate covariate team')
        if r.get(field) is not None: result[key] = number(r[field])
    if len(result) < minimum: raise ValueError(f'Incomplete {field} coverage ({len(result)} teams)')
    return result


def ap_points(rows, names, season):
    editions = [r for r in rows if r.get('season') == season and r.get('seasonType') == 'regular' and r.get('week') == 1]
    polls = [p for r in editions for p in r.get('polls', []) if p.get('poll') == 'AP Top 25']
    if len(polls) != 1: raise ValueError('Preseason AP poll is not available yet')
    points, voters = {}, 0
    for r in polls[0]['ranks']:
        key = names.get(str(r.get('school', '')).casefold().strip())
        if key is None or key in points: raise ValueError('Unknown or duplicate AP team')
        points[key] = number(r['points']); voters += number(r.get('firstPlaceVotes', 0))
    # This catches a provider returning only the top 25 and dropping ORV points.
    if voters <= 0 or sum(points.values()) != 325 * voters:
        raise ValueError('Preseason AP feed omits votes; retain complete supplied poll, including ORV')
    return points


class PollPage(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.span=1
        self.options=[]; self.option=None; self.headings=[]; self.heading=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'tr': self.row=[]
        if tag in ('td','th') and self.row is not None: self.cell=[]; self.span=int(attrs.get('colspan',1))
        if tag == 'option': self.option=[attrs.get('value',''),[]]
        if tag == 'h2': self.heading=[]

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
        if self.option is not None: self.option[1].append(data)
        if self.heading is not None: self.heading.append(data)

    def handle_endtag(self, tag):
        if tag in ('td','th') and self.cell is not None:
            self.row += [' '.join(''.join(self.cell).split())]*self.span; self.cell=None
        if tag == 'tr' and self.row is not None: self.rows.append(self.row); self.row=None
        if tag == 'option' and self.option is not None:
            self.options.append((self.option[0], ''.join(self.option[1]).strip())); self.option=None
        if tag == 'h2' and self.heading is not None: self.headings.append(''.join(self.heading).strip()); self.heading=None


def archive_ap(season, names, fetcher=fetch_url):
    """Use the handoff's original complete-poll source if CFBD omits ORV."""
    base='https://collegepollarchive.com/football/ap/seasons.cfm'
    page=PollPage(); page.feed(fetcher(base+f'?seasonid={season}'))
    expected=f'{season} Preseason AP Football Poll'
    if expected not in page.headings:
        options={value for value,label in page.options if 'preseason' in label.lower()}
        if len(options)!=1: raise ValueError('Complete preseason AP archive is not available yet')
        value=options.pop()
        if not value.isdigit(): raise ValueError('Unexpected preseason AP archive identifier')
        page=PollPage(); page.feed(fetcher(base+'?appollid='+value))
    if expected not in page.headings: raise ValueError('AP archive did not return the requested preseason poll')
    columns=None; points={}; voters=0
    for row in page.rows:
        if any(c.startswith('Team (FPV)') for c in row) and 'Pts' in row:
            columns=(next(i for i,c in enumerate(row) if c.startswith('Team (FPV)')),row.index('Pts')); continue
        if columns is None or len(row)<=max(columns): continue
        label=row[columns[0]]
        # Only a final integer in parentheses is a first-place vote count;
        # the (FL)/(OH) in team names is retained.
        match=re.fullmatch(r'(.+?)\s*\((\d+)\)',label)
        name=match[1].strip() if match else label
        key=names.get(name.casefold())
        if key is None: continue
        if key in points: raise ValueError('Duplicate team in preseason AP archive')
        value=row[columns[1]].replace(',','')
        if not value.isdigit(): raise ValueError('Invalid AP points')
        points[key]=float(value); voters+=int(match[2]) if match else 0
    if len(points)<25 or voters<=0 or sum(points.values())!=325*voters:
        raise ValueError('AP archive total fails full-ballot accounting')
    return points


def complete_ap(season, names, get, archive=archive_ap):
    try: return ap_points(get('/rankings',{'year':season,'seasonType':'regular','week':1}),names,season)
    except ValueError: return archive(season,names)


class PortalPage(HTMLParser):
    def __init__(self, season):
        super().__init__(); self.season = season; self.groups = {}; self.href = None; self.words = []; self.next = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.href = dict(attrs).get('href', ''); self.words = []

    def handle_data(self, data):
        if self.href is not None: self.words.append(data)

    def handle_endtag(self, tag):
        if tag != 'a' or self.href is None: return
        text = ' '.join(''.join(self.words).split())
        if re.search(r'/college/[^/]+/season/' + str(self.season) + r'-football/transferportal/?', self.href):
            if text: self.groups.setdefault(self.href, []).append(text)
        if text.lower() == 'load more': self.next = self.href
        self.href = None


def portal_points(season, names, fetcher=fetch_url):
    url = f'https://247sports.com/season/{season}-football/transferteamrankings/'
    rows, seen = {}, set()
    for page in range(1, 7):
        if url in seen: raise ValueError('Repeated portal pagination')
        seen.add(url); parser = PortalPage(season); parser.feed(fetcher(url))
        if not parser.groups: raise ValueError('247 portal points are not available or page format changed')
        added = 0
        for values in parser.groups.values():
            labels = [s for s in values if not re.fullmatch(r'[\d.,]+|\d+ Commits?', s)]
            points = [float(s) for s in values if re.fullmatch(r'\d+\.\d+', s)]
            if len(set(labels)) != 1 or len(set(points)) != 1: raise ValueError('Ambiguous 247 team points')
            key = names.get(labels[0].casefold())
            if key is None: continue
            if key in rows: raise ValueError('Duplicate team across 247 pages')
            rows[key] = points[0]; added += 1
        if not added: raise ValueError('Portal page contained no matched FBS teams')
        if not parser.next: break
        url = urllib.parse.urljoin(url, parser.next)
        parsed = urllib.parse.urlsplit(url)
        if parsed.netloc != '247sports.com' or parsed.path != f'/season/{season}-football/transferteamrankings/':
            raise ValueError('Unexpected portal pagination destination')
    else: raise ValueError('Portal pagination exceeded six pages')
    if len(rows) < 100: raise ValueError('Incomplete 247 portal table')
    return rows


def coach_at(tenures, date):
    active = []
    for t in tenures:
        start, end = t.get('effectiveStart'), t.get('effectiveEnd')
        if start is None: raise ValueError('Coach tenure lacks an effective start date')
        if instant(start) <= date and (end is None or date < instant(end)):
            active.append(t['coach']['id'])
    if len(set(active)) != 1: raise ValueError('Cannot establish head coach at season start')
    return active[0]


def coaching(season, teams, games, previous_games, get, directory, now):
    """Compare coaches at each season's start, not midseason replacements.

    Bulk records detect changed identities. Only ambiguous/missing records need
    tenure requests, cached by the bulk identity (records/wins are excluded).
    """
    bulk = {y: get('/coaches', {'year': y}) for y in (season-1, season)}
    result = {}
    for team in teams:
        key = str(team['id']); choices = {}
        for year, schedule in ((season-1, previous_games), (season, games)):
            matches = [c for c in bulk[year] if any(str(s.get('teamId')) == key and s.get('year') == year for s in c['seasons'])]
            if len(matches) == 1:
                choices[year] = matches[0]['id']; continue
            identity = digest([{'id':c['id'], 'hireDate':c.get('hireDate')} for c in matches])
            path = directory / 'coaches' / f'{year}-{key}.json'
            saved = read(path)
            if saved is None or saved['identity'] != identity:
                saved = {'identity':identity, 'tenures':get('/coaches/tenures', {'team':team['school'], 'year':year})}
                write(path, saved)
            kicks = [instant(g['startDate']) for g in schedule if team['id'] in (g.get('homeId'),g.get('awayId'))]
            if not kicks: raise ValueError(f'No season-start date for {team["school"]} in {year}')
            choices[year] = coach_at(saved['tenures'], min(now, min(kicks)))
        result[key] = choices[season] != choices[season-1]
    return result


def refresh(season, key, *, directory=DIRECTORY, data=DATA, now=None, cfbd=fetch_cfbd, portal=portal_points, syncer=sync, prior_directory=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not key or key.startswith('Bearer ') or any(c.isspace() for c in key): raise ValueError('CFBD_API_KEY is missing or invalid')
    status_path = directory / 'refresh-status.json'
    status = read(status_path, {})
    prior_path = (prior_directory or ROOT/'_cfb_data/forecast_priors')/'live'/f'{season}.json'
    if status.get('season') == season and status.get('checked_at', '')[:10] == now.date().isoformat() and status.get('games_ready'):
        status['needs_prior'] = needs_prior(status, read(prior_path,{}))
        return status  # workflow_run + daily schedule do not duplicate daily requests
    status = {'season':season, 'checked_at':now.isoformat(), 'games_ready':False, 'feeds':{}}
    base = read(directory/'evidence.json')
    try:
        syncer(season, key, destination=data, refresh_metadata=True, now=now)
        status['games_ready'] = True
    except ValueError as e:
        status['error'] = str(e); write(status_path, status); raise
    folder = data / str(season)
    teams = read(folder/'teams.json')['payload']; names = names_for(teams)
    roster = {str(t['id']):{'name':t['school'],'conference':t.get('conference')} for t in teams}
    # Complete past-season data are fetched once for the annual estimators.
    # Existing frozen numerical evidence does not need another API request.
    previous = season-1
    if str(previous) not in base['ratings'] and not (directory/'annual'/f'{previous}.json').exists():
        saved = [read(data/str(previous)/(name+'.json')) for name in ('games','games-fcs')]
        if any(s is None or instant(s['retrieved_at']) < dt.datetime(season,7,1,tzinfo=dt.timezone.utc) for s in saved):
            syncer(previous, key, destination=data, refresh_metadata=True, now=now)
    from home_history_inputs import ensure_history
    try:
        ensure_history(season,key,root=data,now=now)
        status['history_ready'] = True
    except ValueError as e:
        status['history_ready'] = False; status['history_reason'] = str(e)
    path = directory / 'live' / f'{season}.json'
    live = read(path, {'season':season, 'roster':roster,
        'covariates':base['covariates'].get(str(season),{}), 'sources':{}})
    values = {k:copy.deepcopy(live['covariates'].get(k, {})) for k in roster}
    for field in FIELDS:
        if field not in live['sources'] and all(field in v for v in values.values()):
            live['sources'][field] = {'origin':'supplied handoff', 'observed_at':None,
                'sha256':digest({k:v[field] for k,v in values.items()})}
    get = lambda ep, params: cfbd(ep, params, key)
    collectors = {
        'talent':lambda:mapped(get('/talent', {'year':season}), names, season, 'talent'),
        'returning_ppa':lambda:mapped(get('/player/returning', {'year':season}), names, season, 'percentPPA'),
        'recruiting_points':lambda:mapped(get('/recruiting/teams', {'year':season}), names, season, 'points'),
        'ap_points':lambda:complete_ap(season,names,get),
        'portal_points':lambda:portal(season, names),
        'new_coach':lambda:coaching(season, teams, read(folder/'games.json')['payload'],
            read(data/str(season-1)/'games.json', {'payload':[]})['payload'], get, directory, now),
    }
    defaults = {'talent':None, 'returning_ppa':None, 'recruiting_points':None, 'ap_points':0., 'portal_points':0.}
    for field, collect in collectors.items():
        try:
            fresh = collect()
            if field in ('talent','returning_ppa','recruiting_points'):
                missing = [k for k,v in values.items() if v.get(field) is not None and k not in fresh]
                if missing: raise ValueError(f'{len(missing)} previously available team values disappeared')
            for k in values: values[k][field] = fresh.get(k, defaults.get(field))
            live['sources'][field] = {'origin':'daily provider check', 'observed_at':now.isoformat(), 'sha256':digest(fresh)}
            status['feeds'][field] = {'status':'checked', 'teams':len(fresh)}
        except (ValueError, KeyError, TypeError) as e:
            status['feeds'][field] = {'status':'retained' if all(field in v for v in values.values()) else 'waiting', 'reason':str(e)}
    live.update(roster=roster, covariates=values)
    write(path, live)
    status['covariates_ready'] = all(all(f in v and (f != 'new_coach' or type(v[f]) is bool) for f in FIELDS) for v in values.values())
    status['covariate_key'] = digest({'roster':roster,'covariates':values})
    prior = read(prior_path, {})
    status['needs_prior'] = needs_prior(status, prior)
    write(status_path, status)
    print(json.dumps(status))
    return status


def outputs(status):
    if path := os.environ.get('GITHUB_OUTPUT'):
        with open(path, 'a') as stream:
            for key in ('needs_prior','games_ready','history_ready','covariates_ready'):
                stream.write(f'{key}={str(bool(status.get(key))).lower()}\n')
    for field, result in status.get('feeds',{}).items():
        if result['status'] != 'checked': print(f'::warning::Forecast {field}: {result["status"]}. {result["reason"]}')
    if path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(path,'a') as stream:
            stream.write(f'### Forecast inputs: {status["season"]}\n\nChecked {status["checked_at"]}.\n\n')
            for field,result in status.get('feeds',{}).items():
                stream.write(f'- {field}: {result["status"]}'+(' — '+result['reason'] if 'reason' in result else '')+'\n')
            if status.get('history_reason'): stream.write('\n'+status['history_reason']+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--season', default='current')
    args = parser.parse_args(); now = dt.datetime.now(dt.timezone.utc)
    year = season_for(now) if args.season == 'current' else int(args.season)
    outputs(refresh(year, os.environ.get('CFBD_API_KEY',''), now=now))


if __name__ == '__main__': main()
