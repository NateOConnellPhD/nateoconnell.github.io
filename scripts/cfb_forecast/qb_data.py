"""Refresh the supplied QB model's public data daily; one bounded raw file at a time."""
import argparse
import csv
import datetime as dt
import gc
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/cfb'))
from cfb_forecast.refresh import read, write, season_for
from sync_data import digest

DIRECTORY = ROOT / '_cfb_data/forecast_inputs/qb'
BASE = 'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/'
TASK = ROOT / '.codex-tmp/cfb-refit/qb-download'
COLUMNS = ['season','week','season_type','game_id','home','away','pos_team','def_pos_team',
           'passer_id','n','epa_sum','epa2_sum','first_play']


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.hostname not in {'github.com',
                'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
            raise ValueError('Unexpected QB release redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(relative, path, etag=None, limit=128*1024*1024):
    headers = {'User-Agent': 'nateoconnell.com daily QB refresh'}
    if etag: headers['If-None-Match'] = etag
    try:
        with urllib.request.build_opener(ReleaseRedirect()).open(
                urllib.request.Request(BASE + relative, headers=headers), timeout=90) as response:
            path.parent.mkdir(parents=True, exist_ok=True)
            n = 0; sha = hashlib.sha256()
            with path.open('wb') as stream:
                while chunk := response.read(1024*1024):
                    n += len(chunk)
                    if n > limit: raise ValueError('QB source exceeds its bounded download size')
                    sha.update(chunk); stream.write(chunk)
            return {'etag': response.headers.get('ETag'), 'sha256': sha.hexdigest(), 'url': BASE + relative}
    except urllib.error.HTTPError as error:
        if error.code == 304 and etag: return None
        raise ValueError(f'QB source {relative}: HTTP {error.code}') from None


def validate(frame, season):
    import numpy as np
    if not set(COLUMNS) <= set(frame.columns) or frame.empty: raise ValueError('No usable QB dropbacks')
    missing = frame[COLUMNS].isna()
    if missing.any().any():
        fields = ', '.join(missing.columns[missing.any()])
        rows = missing.any(axis=1)
        games = ', '.join(map(str, frame.loc[rows, 'game_id'].drop_duplicates().head(5)))
        raise ValueError(f'Incomplete QB dropback rows for {season}: missing {fields}; '
                         f'game IDs {games} ({int(rows.sum())} rows)')
    numeric = frame[['season','week','game_id','passer_id','n','epa_sum','epa2_sum','first_play']].to_numpy(float)
    if not np.isfinite(numeric).all() or (frame.season != season).any() or (frame.n <= 0).any():
        raise ValueError('Invalid QB season or numerical input')
    if not set(frame.season_type) <= {'regular','postseason'}: raise ValueError('Unknown QB season type')
    if frame.duplicated(['game_id','pos_team','passer_id']).any(): raise ValueError('Duplicate passer-game')
    if (frame.epa2_sum + 1e-7 < frame.epa_sum**2 / frame.n).any(): raise ValueError('Invalid EPA sum of squares')


def refresh(season, directory=DIRECTORY, task=TASK, now=None, fetch=download, public_status=None):
    import pandas as pd
    import pyreadr
    from cfb_forecast.qb_extract import dropbacks
    now = now or dt.datetime.now(dt.timezone.utc); stamp = now.isoformat()
    directory, task = Path(directory), Path(task)
    if not 2023 <= season <= season_for(now): raise ValueError('Unsupported QB forecast season')
    state = read(directory/'refresh.json', {'seasons': {}})
    failures = []
    for year in range(2021, season+1):
        path = directory/f'{year}.json'; old = read(path)
        info = state['seasons'].get(str(year), {})
        # Multiple production triggers on the same day share this observation.
        pbp_url = f'cfbfastR_cfb_pbp/play_by_play_{year}.rds'
        schedule_url = f'cfb_schedules/cfb_schedules_{year}.csv.gz'
        same_source = info.get('url') == BASE + pbp_url
        if old and same_source and info.get('checked_at','')[:10] == stamp[:10] and not info.get('error'): continue
        raw = task/f'pbp-{year}.rds'; schedule = task/f'schedule-{year}.csv.gz'
        try:
            src = fetch(pbp_url, raw, info.get('etag') if old and same_source else None)
            # Current roster refresh is independent of play-by-play changes.
            # Older saved schedules have only IDs/dates: fetch their metadata
            # once, even if the provider's schedule ETag has not changed.
            has_labels = old and old.get('schedule') and all(
                r.get('season_type') in {'regular','postseason'} for r in old['schedule'])
            sch = fetch(schedule_url, schedule,
                        info.get('schedule_etag') if has_labels and same_source else None, limit=8*1024*1024)
            value = dict(old) if old else {}
            if sch:
                with gzip.open(schedule, 'rb') as stream: body = stream.read(8*1024*1024+1)
                if len(body) > 8*1024*1024: raise ValueError('QB schedule exceeds decompressed size limit')
                rows = list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
                fbs = {r[side+'_team'] for r in rows for side in ('home','away') if r[side+'_division']=='fbs'}
                if len(fbs) < 100: raise ValueError('Incomplete QB season classification')
                value['fbs'] = sorted(fbs)
                value['schedule'] = [{'id':int(r['game_id']), 'date':r['start_date'],
                    'season_type':r['season_type']} for r in rows if r.get('start_date')]
            if src:
                try: df = next(iter(pyreadr.read_r(str(raw)).values()))
                except Exception as error:
                    raise ValueError(f'Cannot read QB play-by-play: {type(error).__name__}') from error
                season_types = {}
                for row in value.get('schedule', []):
                    label = row.get('season_type')
                    if label not in {'regular','postseason'}: continue
                    if row['id'] in season_types and season_types[row['id']] != label:
                        raise ValueError(f"Conflicting QB schedule labels for game {row['id']}")
                    season_types[row['id']] = label
                frame, names = dropbacks(df, year, season_types); del df; gc.collect()
                validate(frame, year)
                if old:
                    old_keys = {(r[3],r[6]) for r in old['rows']}
                    new_keys = set(zip(frame.game_id,frame.pos_team))
                    if not old_keys <= new_keys: raise ValueError('QB feed lost saved passer-games; previous data retained')
                value.update(columns=COLUMNS, rows=frame[COLUMNS].values.tolist(),
                    names={**(old or {}).get('names',{}), **names})
                del frame
            if not value or not value.get('fbs'): raise ValueError('Missing QB baseline')
            value.update(season=year, schema='qb-dropbacks-v1')
            body_key = digest({k:value[k] for k in ('columns','rows','fbs','schedule')})
            value['input_key'] = body_key
            value['observed_at'] = stamp if not old or body_key != old['input_key'] else old['observed_at']
            write(path, value)
            info = {**info, **(src or {}), 'checked_at':stamp, 'error':None,
                    'schedule_etag':(sch or {}).get('etag',info.get('schedule_etag'))}
        except (ValueError, OSError, KeyError, urllib.error.URLError) as error:
            info = {**info, 'checked_at':stamp, 'error':str(error)}
            failures.append(f'{year}: {error}')
        finally:
            for p in (raw,schedule): p.unlink(missing_ok=True)
            gc.collect()
        state['seasons'][str(year)] = info
    state.update(checked_at=stamp, season=season, errors=failures)
    write(directory/'refresh.json',state)
    if public_status:
        current=read(directory/f'{season}.json',{})
        write(Path(public_status),{'season':season,'checked_at':stamp,
            'observed_at':current.get('observed_at'),'warnings':failures,
            'starter_rule':'Last game’s first passer unless explicitly overridden; no injury feed.'})
    # A new preseason has no current dropbacks yet. All earlier seasons remain mandatory.
    missing = [y for y in range(2021,season) if not (directory/f'{y}.json').exists()]
    if missing: raise ValueError(f'QB history unavailable for {missing}; cannot silently disable the QB model')
    for error in failures: print('::warning::QB refresh: ' + error)
    if task.exists() and not any(task.iterdir()): task.rmdir()
    print(json.dumps({'qb_checked_at':stamp,'warnings':failures,'missing_history':missing}))


def identity(season, directory=DIRECTORY, historical=False, *, require_current=False):
    """Stdlib preflight; timestamps never invalidate the model fit."""
    files = {str(y):read(Path(directory)/f'{y}.json') for y in range(2021,season+1)}
    if any(files[str(y)] is None for y in range(2021,season)):
        raise ValueError('QB history is missing; run the daily QB refresh before publishing')
    if require_current and files[str(season)] is None:
        state = read(Path(directory)/'refresh.json', {})
        reason = state.get('seasons', {}).get(str(season), {}).get('error')
        raise ValueError(f'Missing QB dropbacks for {season}: '
                         f'{reason or "run the daily QB refresh before publishing"}')
    from . import qb_availability
    return {'data':{y:v['input_key'] if v else None for y,v in files.items()},
        'names':digest({y:v.get('names',{}) if v else {} for y,v in files.items()}),
        'status':qb_availability.identity(season,directory) if not historical else None}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--season',default='current'); args=p.parse_args()
    year=season_for(dt.datetime.now(dt.timezone.utc)) if args.season=='current' else int(args.season)
    refresh(year,public_status=ROOT/'assets/data/cfb/projections/qb-status.json')
