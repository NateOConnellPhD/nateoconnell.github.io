"""Optional cached line comparisons; never model covariates or fit triggers."""
import datetime as dt
import json
import math
from pathlib import Path
from statistics import median
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / '_cfb_data/forecast_markets'


def consensus(payload):
    result = {}
    for game in payload:
        if not isinstance(game,dict) or type(game.get('id')) is not int or not isinstance(game.get('lines'),list):
            raise ValueError('Invalid sportsbook game record')
        ident = str(game['id']); providers = {}
        for line in game['lines']:
            if not isinstance(line,dict) or not isinstance(line.get('provider'),str): raise ValueError('Invalid sportsbook provider')
            name = line['provider']
            if name in providers: raise ValueError(f'Duplicate sportsbook for game {ident}')
            vals = {}
            for key, field in (('open', 'spreadOpen'), ('latest', 'spread')):
                val = line.get(field)
                if val is not None:
                    if isinstance(val, bool) or not isinstance(val, (int,float)) or not math.isfinite(val):
                        raise ValueError('Non-numeric sportsbook spread')
                    vals[key] = float(val)
            providers[name] = vals
        row = {}
        for key in ('open','latest'):
            values = [v[key] for v in providers.values() if key in v]
            row[key] = median(values) if values else None
            row[key+'_books'] = len(values)
        result[ident] = row
    return result


def read(season, directory=DIRECTORY):
    path = directory / f'{season}.json'
    return json.loads(path.read_text()) if path.exists() else {'games':{},'observed_at':None}


def fetch(season, key):
    from sync_data import NoRedirect
    request = urllib.request.Request('https://api.collegefootballdata.com/lines?' + urllib.parse.urlencode({'year':season,'seasonType':'both'}),
        headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'nateoconnell.com forecasts'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=30) as response: body=response.read(8*1024*1024+1)
    except urllib.error.HTTPError as e: raise ValueError(f'CFBD lines HTTP {e.code}') from None
    except (urllib.error.URLError,TimeoutError,OSError): raise ValueError('CFBD lines unavailable') from None
    if len(body)>8*1024*1024: raise ValueError('CFBD lines response exceeds 8 MB')
    payload=json.loads(body)
    if not isinstance(payload,list): raise ValueError('Expected sportsbook game array')
    return payload


def sync(season, observation_key, key, directory=DIRECTORY, fetcher=fetch):
    old=read(season,directory)
    if old.get('observation_key')==observation_key:
        return {'requests':0,'status':'cached'}
    if not key or key.startswith('Bearer '): return {'requests':0,'status':'CFBD_API_KEY missing or invalid; market comparison remains unavailable/stale'}
    games=consensus(fetcher(season,key))
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    body={'schema':'cfb-market-consensus-v1','season':season,'observation_key':observation_key,
        'observed_at':old['observed_at'] if old.get('games')==games else now,'checked_at':now,'games':games}
    directory.mkdir(parents=True,exist_ok=True)
    (directory/f'{season}.json').write_text(json.dumps(body,allow_nan=False,separators=(',',':'))+'\n')
    return {'requests':1,'status':'updated','games':len(games)}
