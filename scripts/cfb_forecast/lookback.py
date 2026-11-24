"""Join frozen predictions to saved results. No network, fitting, or new forecasts."""
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/cfb'))
from sync_data import checked_game_status, instant, merge_games, reviewed_game_statuses

SCHEMA = 'cfb-lookback-v1'
PUBLIC = ROOT / 'assets/data/cfb/projections'


def read(path):
    return json.loads(path.read_text())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def timing(meta, kickoff):
    """Observation dates are not evidence of when a prediction was produced."""
    if meta.get('historical_reconstruction'):
        return 'reconstruction'
    saved = meta.get('saved_at')
    if not saved:
        return 'unverified'
    saved = instant(saved)
    if saved >= instant(kickoff):
        return 'after_kickoff'
    observed = [meta.get('observed_at'), meta.get('through_date')]
    observed += [value.get('observed_at') if isinstance(value, dict) else value
                 for value in meta.get('input_observations', {}).values()]
    observed += [meta.get('quarterbacks', {}).get(key) for key in ('observed_at', 'availability_observed_at')]
    # Supplied covariates may have no dated observation. Never infer a date for
    # those; saved_at still proves the estimate itself existed before kickoff.
    for value in observed:
        if value and instant(value) > saved:
            return 'unverified'
    return 'pregame'


def saved_games(season, directory):
    feeds = [read(directory / str(season) / (name + '.json'))
             for name in ('games', 'games-fcs') if (directory / str(season) / (name + '.json')).exists()]
    if not feeds:
        raise ValueError(f'No saved results feed for lookback season {season}')
    games = merge_games(feeds[0]['payload'], feeds[1]['payload'] if len(feeds) > 1 else [])
    checked = min(instant(f['retrieved_at']) for f in feeds).isoformat()
    return {g['id']: g for g in games}, checked


def game_row(raw, checked, corrections):
    status = checked_game_status(raw, corrections.get(raw['id']))
    final = None
    if not status and raw.get('completed') is True:
        h, a = raw.get('homePoints'), raw.get('awayPoints')
        if (type(h) is int and type(a) is int and min(h, a) >= 0 and h != a
                and instant(raw['startDate']) < instant(checked)):
            final = {'home': h, 'away': a}
        # A placeholder tied final is not a scored forecast. Keep it visible as
        # unverified rather than inventing a result or blocking the whole archive.
        status = 'final' if final else 'unverified'
    return {'id': raw['id'], 'season': raw['season'], 'week': raw['week'],
            'season_type': raw['seasonType'], 'date': raw['startDate'],
            'home': {'id': str(raw['homeId']), 'name': raw['homeTeam']},
            'away': {'id': str(raw['awayId']), 'name': raw['awayTeam']},
            'neutral': raw['neutralSite'], 'status': status or 'scheduled',
            'result': final, 'predictions': []}


def projection(game, edition, provenance):
    result = {'edition': edition, 'timing': provenance, 'home_margin': game['home_margin']}
    if not finite(result['home_margin']):
        raise ValueError('Nonfinite lookback margin')
    if 'p_home' in game:
        if not finite(game['p_home']) or not 0 <= game['p_home'] <= 1:
            raise ValueError('Invalid saved win probability')
        result['p_home'] = game['p_home']
    for level in (80, 95):
        low, high = (f'margin_{side}{level}' for side in ('lo', 'hi'))
        if low in game and high in game:
            if not all(finite(game[k]) for k in (low, high)) or game[low] > game[high]:
                raise ValueError('Invalid saved predictive range')
            result.update({low: game[low], high: game[high]})
    if game.get('scores'):
        result['scores'] = {}
        for side in ('home', 'away'):
            values = {key: game['scores'][side][key] for key in ('mean', 'median', 'lo80', 'hi80', 'lo95', 'hi95')}
            if not all(finite(v) and v >= 0 for v in values.values()):
                raise ValueError('Invalid saved team-score prediction')
            result['scores'][side] = values
    return result


def build(public=PUBLIC, seasons=ROOT / '_cfb_data/seasons', evidence=None):
    evidence = read(ROOT / '_cfb_data/forecast_inputs/evaluation.json') if evidence is None else evidence
    index = read(public / 'index.json')
    years = sorted({r['season'] for r in index['snapshots']} |
                   {r['season'] for rows in evidence.values() for r in rows})
    corrections = reviewed_game_statuses()
    reports, raw, by_game = {}, {}, {}
    for year in years:
        raw[year], checked = saved_games(year, seasons)
        reports[year] = {'schema': SCHEMA, 'season': year, 'results_checked_at': checked, 'editions': {}, 'games': []}
        by_game[year] = {}

    def entry(year, ident):
        if ident not in raw[year]:
            raise ValueError(f'Lookback game {ident} missing from saved {year} results')
        if ident not in by_game[year]:
            by_game[year][ident] = game_row(raw[year][ident], reports[year]['results_checked_at'], corrections)
        return by_game[year][ident]

    for row in index['snapshots']:
        if not re.fullmatch(r'forecast-[a-f0-9]{16}\.json', row['file']):
            raise ValueError('Invalid archived forecast filename')
        snapshot = read(public / row['file']); meta = snapshot['meta']; year = meta['season']
        if year != row['season']:
            raise ValueError('Forecast index season mismatch')
        edition = row['id']
        reports[year]['editions'][edition] = {
            'kind': 'saved', 'saved_at': meta.get('saved_at'), 'observed_at': meta['observed_at'],
            'through_date': meta['through_date'], 'model': meta.get('model'),
            'historical_reconstruction': meta.get('historical_reconstruction', False),
            'caveat': meta.get('prior_caveat', '')}
        seen = set()
        for game in snapshot['games']:
            target = entry(year, game['id'])
            if (game['id'] in seen or str(game['home']) != target['home']['id']
                    or str(game['away']) != target['away']['id']):
                raise ValueError('Duplicate game or mismatched teams in saved forecast')
            seen.add(game['id'])
            # Rescheduling cannot retroactively turn an after-kickoff prediction
            # into a genuine pregame estimate. Check both recorded kickoffs.
            cutoff = min(instant(game['date']), instant(target['date'])).isoformat()
            target['predictions'].append(projection(game, edition, timing(meta, cutoff)))

    for period, rows in evidence.items():
        seen = set()
        for row in rows:
            year, ident = row['season'], row['game_id']; target = entry(year, ident)
            edition = f'earlier-{year}-{period}'
            reports[year]['editions'][edition] = {
                'kind': 'earlier', 'period': period, 'saved_at': None,
                'caveat': 'Earlier power model, before QB and team-score extensions. Weekly fits use earlier game results, '
                          'but some covariates were collected later. These are retrospective estimates, not recorded pregame forecasts.'}
            if ident in seen or not target['result'] or target['result']['home'] - target['result']['away'] != row['actual']:
                raise ValueError(f'Earlier evaluation does not match final result for game {ident}')
            seen.add(ident)
            target['predictions'].append(projection({'home_margin': row['model']}, edition, 'reconstruction'))

    for year, report in reports.items():
        report['games'] = sorted(by_game[year].values(), key=lambda g: (g['date'], g['id']))
        for game in report['games']:
            game['predictions'].sort(key=lambda p: p['edition'])
    return reports


def write(reports, destination=PUBLIC):
    # Validate/encode every season before replacing any published report.
    encode = lambda value: (json.dumps(value, allow_nan=False, separators=(',', ':')) + '\n').encode()
    output = {f'lookback-{year}.json': encode(report) for year, report in reports.items()}
    output['lookback-index.json'] = encode({'schema': SCHEMA, 'seasons': [
        {'season': year, 'file': f'lookback-{year}.json', 'games': len(reports[year]['games'])}
        for year in sorted(reports, reverse=True)]})
    for name, body in output.items():
        path = destination / name
        if not path.exists() or path.read_bytes() != body:
            path.write_bytes(body)
    return sum(map(len, output.values()))


if __name__ == '__main__':
    reports = build()
    print(json.dumps({'lookback_seasons': sorted(reports), 'games': sum(len(r['games']) for r in reports.values()),
                      'public_bytes': write(reports), 'api_requests': 0, 'fits': 0}))
