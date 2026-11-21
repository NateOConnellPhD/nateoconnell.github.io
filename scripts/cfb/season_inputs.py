"""Prepare audited fit inputs from saved CFBD responses, without network calls.

Keep provider files unchanged. Reviewed corrections are a separate versioned
layer and are included in input provenance. Historical cutoffs are retrospective:
the feed records kickoff and final status, not exact historical completion time.
"""
import json
from pathlib import Path

from sync_data import DATA, digest, instant, normalize, read_saved, merge_games

CORRECTIONS = Path(__file__).with_name('venue_corrections.json')


def prepare(normalized, raw_games, corrections, *, cutoff, through_week=None):
    season = normalized['season']
    raw = {g['id']: g for g in raw_games}
    if len(raw) != len(raw_games):
        raise ValueError('Duplicate source game IDs')
    if corrections.get('schema') != 'reviewed-venues-v1':
        raise ValueError('Unsupported venue correction schema')
    by_id = {}
    for row in corrections['games']:
        if row['season'] != season:
            continue
        ident = row['game_id']
        if ident in by_id or type(row['neutral_site']) is not bool or not row['sources'] or not row['reason']:
            raise ValueError('Invalid or duplicate venue correction')
        by_id[ident] = row
    games, audit = [], []
    for original in normalized['games']:
        if (not original['eligible'] or instant(original['start_date']) > cutoff
                or (through_week is not None and original['week'] > through_week)):
            continue
        game = dict(original)
        correction = by_id.get(game['id'])
        if correction:
            source = raw[game['id']]
            expected = correction['expected']
            for key in ('homeId', 'awayId', 'homePoints', 'awayPoints', 'venue'):
                if source.get(key) != expected[key]:
                    raise ValueError(f"Review stale venue correction for game {game['id']}: {key}")
            audit.append({**correction, 'provider_neutral_site': original['neutral_site'],
                          'changed': original['neutral_site'] != correction['neutral_site']})
            game['neutral_site'] = correction['neutral_site']
        games.append(game)
    if not games:
        raise ValueError('No eligible completed games at the selected cutoff')
    teams = normalized['teams']
    index = {t['id']: i for i, t in enumerate(teams)}
    data = {'home': [index[g['home_id']] for g in games],
            'away': [index[g['away_id']] for g in games],
            'venue': [int(not g['neutral_site']) for g in games],
            'margin': [g['home_points'] - g['away_points'] for g in games]}
    fbs_indices = [i for i, t in enumerate(teams) if t.get('classification', 'fbs') == 'fbs']
    scored = [i for i, g in enumerate(games) if g['home_fbs'] or g['away_fbs']]
    if not scored:
        raise ValueError('No eligible completed games at the selected cutoff')
    return {'season': season, 'teams': teams, 'games': games, 'data': data,
            'fbs_indices': fbs_indices, 'scored_game_indices': scored, 'statistical_scope': normalized['summary'].get('scope', 'fbs_only'),
            'fit_input_sha256': digest({'teams': teams, 'games': games}),
            'venue_corrections': audit, 'venue_corrections_sha256': digest(audit),
            'cutoff': cutoff.isoformat(), 'through_week': through_week,
            'cutoff_interpretation': 'Observed final status with kickoff cutoff; historical reconstruction is retrospective.'}


def load_inputs(season, *, through_week=None, as_of=None, root=DATA, corrections_path=CORRECTIONS):
    if type(season) is not int or season < 2002:
        raise ValueError('Invalid season')
    folder = Path(root) / str(season)
    sources = {}
    for name, endpoint, params in (
        ('teams', '/teams/fbs', {'year': season}),
        ('calendar', '/calendar', {'year': season}),
        ('games', '/games', {'year': season, 'seasonType': 'both', 'classification': 'fbs'}),
        ('games-fcs', '/games', {'year': season, 'seasonType': 'both', 'classification': 'fcs'}),
    ):
        sources[name] = read_saved(folder / (name + '.json'), season, endpoint, params)
        if sources[name] is None:
            raise ValueError(f'Missing saved {name}; run the data-sync workflow for this season')
    if not sources['games']['payload'] or not sources['games-fcs']['payload']:
        raise ValueError('Joint FBS/FCS fitting requires both saved game feeds')
    observed = min(instant(sources[key]['retrieved_at']) for key in ('games', 'games-fcs'))
    raw_games = merge_games(sources['games']['payload'], sources['games-fcs']['payload'])
    normalized = normalize(season, sources['teams']['payload'], sources['calendar']['payload'],
                           raw_games, max(instant(sources[key]['retrieved_at']) for key in ('games', 'games-fcs')),
                           include_fcs=True)
    cutoff = instant(as_of) if as_of else observed
    if through_week is not None:
        if type(through_week) is not int or through_week < 0:
            raise ValueError('Invalid week')
        weeks = [w for w in sources['calendar']['payload']
                 if w['seasonType'] == 'regular' and w['week'] == through_week]
        if len(weeks) != 1:
            raise ValueError('Selected week is absent from the saved calendar')
        end = instant(weeks[0]['endDate'])
        if not as_of and end > observed:
            raise ValueError('Selected week has not ended in this saved snapshot; use an explicit as-of cutoff')
        cutoff = min(cutoff, end)
    if cutoff > observed:
        raise ValueError('Cutoff is later than the saved data observation')
    corrections = json.loads(Path(corrections_path).read_text())
    result = prepare(normalized, raw_games, corrections,
                     cutoff=cutoff, through_week=through_week)
    result['source'] = {name: {k: value[k] for k in ('source', 'parameters', 'retrieved_at', 'payload_sha256')}
                        for name, value in sources.items()}
    return result
