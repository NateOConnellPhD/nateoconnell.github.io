"""Read saved provider responses; this feature never fetches football data."""
import datetime as dt
import json
import math
from pathlib import Path

from season_inputs import load_fit_inputs
from sync_data import DATA, checked_game_status, digest, instant, merge_games, reviewed_game_statuses

ROOT = Path(__file__).resolve().parents[2]
PRIORS = ROOT / '_cfb_data' / 'forecast_priors'


def preseason(season, directory=PRIORS):
    path = directory / f'{season}.json'
    if not path.exists():
        raise ValueError(f'No reviewed preseason forecasting prior for {season}; previous forecasts are preserved')
    value = json.loads(path.read_text())
    if (value['season'] != season or value['schema'] != 'cfb-forecast-prior-v1'
            or value['previous_season'] != season - 1 or not value['training_seasons']
            or max(value['training_seasons']) >= season or not math.isfinite(value['sd']) or value['sd'] <= 0
            or not value['mean_by_id'] or any(not k.isdigit() or int(k) <= 0 or not math.isfinite(v)
                for k, v in value['mean_by_id'].items())):
        raise ValueError('Invalid preseason prior or training-season leakage')
    return value


def schedule_rows(raw, teams, cutoff):
    """Only not-yet-started FBS-involving DI games, never a past unfinished score."""
    roster = {t['id']: t for t in teams}; corrections = reviewed_game_statuses()
    result = []
    for g in raw:
        if g['completed'] or instant(g['startDate']) <= cutoff or checked_game_status(g, corrections.get(g['id'])):
            continue
        h, a = g['homeId'], g['awayId']
        if h not in roster or a not in roster or not any(roster[t]['classification'] == 'fbs' for t in (h, a)):
            continue
        if type(g['neutralSite']) is not bool: raise ValueError('Unknown forecast venue')
        result.append({'id': g['id'], 'week': g['week'], 'season_type': g['seasonType'],
                       'date': g['startDate'], 'home': str(h), 'away': str(a), 'neutral': g['neutralSite']})
    return sorted(result, key=lambda g: (g['date'], g['id']))


def load(season, root=DATA, prior_directory=PRIORS):
    inputs = load_fit_inputs(season, root=root)
    folder = Path(root) / str(season)
    saved = [json.loads((folder / f'{name}.json').read_text()) for name in ('games', 'games-fcs')]
    raw = merge_games(*(s['payload'] for s in saved)); by_id = {g['id']: g for g in raw}
    expectancy = [by_id[g['id']].get('homePostgameWinProbability') for g in inputs['games']]
    prior = preseason(season, prior_directory)
    if not set(prior['mean_by_id']) <= {str(t['id']) for t in inputs['teams'] if t['classification'] == 'fbs'}:
        raise ValueError('Preseason prior IDs do not match the forecast-season FBS roster')
    observed = max(instant(s['retrieved_at']) for s in saved)
    upcoming = schedule_rows(raw, inputs['teams'], observed)
    training_key = digest({'teams': inputs['teams'], 'data': inputs['data'],
        'expectancy': expectancy, 'prior': prior, 'history': inputs['home_history']['input_sha256']})
    return inputs, prior, expectancy, upcoming, observed.isoformat(), training_key


def previous_games(season, root=DATA):
    folder = Path(root) / str(season - 1)
    saved = json.loads((folder / 'games.json').read_text())
    if instant(saved['retrieved_at']) < dt.datetime(season, 8, 1, tzinfo=dt.timezone.utc):
        raise ValueError('Previous season is not complete in the saved feed')
    fbs = {t['id'] for t in json.loads((folder / 'teams.json').read_text())['payload']}
    corrections = reviewed_game_statuses(); games = []
    for g in saved['payload']:
        if not g['completed'] or checked_game_status(g, corrections.get(g['id'])): continue
        if not any(g[k] in fbs for k in ('homeId', 'awayId')): continue
        if any(g[k] not in ('fbs', 'fcs') for k in ('homeClassification', 'awayClassification')): continue
        if g['homePoints'] == g['awayPoints']: raise ValueError('Unresolved tied previous-season result')
        games.append(g)
    return games, fbs
