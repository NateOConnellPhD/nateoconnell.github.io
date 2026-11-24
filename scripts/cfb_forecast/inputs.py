"""Read saved provider responses; this feature never fetches football data."""
import datetime as dt
import json
import math
from pathlib import Path

from season_inputs import load_fit_inputs
from .config import CONFIG
from sync_data import DATA, checked_game_status, digest, instant, merge_games, reviewed_game_statuses

ROOT = Path(__file__).resolve().parents[2]
PRIORS = ROOT / '_cfb_data' / 'forecast_priors'


def preseason(season, directory=PRIORS):
    path = directory / f'{season}.json'
    if not path.exists():
        raise ValueError(f'No reviewed preseason forecasting prior for {season}; previous forecasts are preserved')
    value = json.loads(path.read_text())
    if (value['season'] != season or value['schema'] != 'cfb-forecast-prior-v7' or value.get('model') != CONFIG.model
            or value['previous_season'] != season - 1 or not value['training_seasons']
            or max(value['training_seasons']) >= season or not math.isfinite(value['sd']) or value['sd'] <= 0
            or not value['mean_by_id'] or any(not k.isdigit() or int(k) <= 0 or not math.isfinite(v)
                for k, v in value['mean_by_id'].items())):
        raise ValueError('Invalid preseason prior or training-season leakage')
    if (not value.get('fcs_mean_by_id') or not math.isfinite(value['fcs_sd']) or value['fcs_sd'] <= 0
            or any(not k.isdigit() or not math.isfinite(v) for k, v in value['fcs_mean_by_id'].items())
            or not math.isfinite(value['fcs_gap'])):
        raise ValueError('Invalid FCS forecasting prior')
    return value


def is_playoff(game):
    text = str(game.get('notes') or '').lower()
    return game.get('isCfp') is True or (game.get('homeClassification') == game.get('awayClassification') == 'fbs'
        and any(word in text for word in ('playoff', 'cfp', 'national championship')))


def schedule_rows(raw, teams, cutoff):
    """Only not-yet-started FBS-involving DI games, never a past unfinished score."""
    roster = {t['id']: t for t in teams}; corrections = reviewed_game_statuses()
    result = []
    for g in raw:
        if g['completed'] or instant(g['startDate']) <= cutoff or checked_game_status(g, corrections.get(g['id'])):
            continue
        if g['seasonType'] != 'regular' and not is_playoff(g): continue
        h, a = g['homeId'], g['awayId']
        if h not in roster or a not in roster or not any(roster[t]['classification'] == 'fbs' for t in (h, a)):
            continue
        if type(g['neutralSite']) is not bool: raise ValueError('Unknown forecast venue')
        result.append({'id': g['id'], 'week': g['week'], 'season_type': g['seasonType'],
                       'date': g['startDate'], 'home': str(h), 'away': str(a), 'neutral': g['neutralSite']})
    return sorted(result, key=lambda g: (g['date'], g['id']))


def load(season, root=DATA, prior_directory=PRIORS, forecast_week=None):
    prior = preseason(season, prior_directory)
    inputs = load_fit_inputs(season, root=root)
    folder = Path(root) / str(season)
    saved = [json.loads((folder / f'{name}.json').read_text()) for name in ('games', 'games-fcs')]
    raw = merge_games(*(s['payload'] for s in saved)); by_id = {g['id']: g for g in raw}
    # A historical window uses the same model as production and strictly earlier
    # regular-season games. The kickoff guard catches rescheduled games too.
    observed = min(instant(s['retrieved_at']) for s in saved)
    upcoming = schedule_rows(raw, inputs['teams'], observed)
    if forecast_week is not None:
        candidates = [g for g in raw if (g['week'] == forecast_week and g['seasonType'] == 'regular')
                      or (forecast_week == 99 and g['seasonType'] == 'postseason' and is_playoff(g))]
        if not candidates: raise ValueError('No games in the requested forecasting window')
        first = min(instant(g['startDate']) for g in candidates)
        if first > observed: raise ValueError('Historical forecast window is later than the saved observation')
        keep = [i for i, g in enumerate(inputs['games']) if g['week'] < forecast_week and instant(g['start_date']) < first]
        if any(instant(g['start_date']) >= first for g in inputs['games'] if g['week'] < forecast_week):
            raise ValueError('Rescheduled training game starts on or after the forecast window; review the window')
        inputs['games'] = [inputs['games'][i] for i in keep]
        inputs['data'] = {k: [v[i] for i in keep] for k, v in inputs['data'].items()}
        eligible = [{**g, 'completed': False} for g in candidates]
        upcoming = schedule_rows(eligible, inputs['teams'], first - dt.timedelta(microseconds=1))
        observed = first
    expectancy = [by_id[g['id']].get('homePostgameWinProbability') for g in inputs['games']]
    through = max((g['week'] for g in inputs['games']), default=0)
    upcoming = [g for g in upcoming if g['season_type'] != 'regular' or g['week'] > through]
    inputs['forecast_week'] = forecast_week or through + 1
    inputs['last_training_week'] = through
    if inputs['games']:
        last_start = max(instant(g['start_date']) for g in inputs['games'])
        for g in upcoming:
            g['ahead'] = max(g['week'] - through, 1) if g['season_type'] == 'regular' else max(1, math.ceil((instant(g['date']) - last_start).total_seconds() / (7 * 86400)))
    else:
        for g in upcoming: g['ahead'] = 1
    if not set(prior['mean_by_id']) <= {str(t['id']) for t in inputs['teams'] if t['classification'] == 'fbs'}:
        raise ValueError('Preseason prior IDs do not match the forecast-season FBS roster')
    numerical_prior = {k: prior[k] for k in ('mean_by_id','sd','fcs_mean_by_id','fcs_sd','fcs_gap','tau_fbs','tau_fcs','sigma','config')}
    training_key = digest({'teams': inputs['teams'], 'data': inputs['data'],
        'structure': inputs['strength_structure'], 'expectancy': expectancy, 'weeks': [g['week'] for g in inputs['games']], 'prior': numerical_prior, 'history': inputs['home_history']['input_sha256']})
    return inputs, prior, expectancy, upcoming, observed.isoformat(), training_key
