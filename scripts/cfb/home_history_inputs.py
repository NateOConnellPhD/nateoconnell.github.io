"""Saved, season-specific FBS scores for the preceding three home-prior years.

Standard library only. No proxy years, roster heuristics, current scores, or
ratings. CFBD IDs identify schools across years; strengths remain team-season
specific. Fetch missing historical files once, never per visitor or per week.
"""
import datetime as dt
import json
from pathlib import Path

from season_inputs import CORRECTIONS, prepare
from sync_data import DATA, UTC, encoded, envelope, fetch, instant, normalize, read_saved
from sync_data import digest


def years_for(season):
    if type(season) is not int or season < 2002:
        raise ValueError('Ranking season must be 2002 or later')
    return list(range(season - 3, season))


def endpoints(year):
    return {'teams': ('/teams/fbs', {'year': year}),
            'games': ('/games', {'year': year, 'seasonType': 'both', 'classification': 'fbs'})}


def season_end(year):
    # Historical home fitting needs a complete season, not weekly cutoffs.
    # Use the following preseason boundary, including the exceptional 2020 spring.
    return dt.datetime(year+1, 8, 1, tzinfo=UTC)


def read_sources(year, root):
    result = {}
    for name, (endpoint, params) in endpoints(year).items():
        saved = read_saved(Path(root) / str(year) / (name + '.json'), year, endpoint, params)
        if saved is None:
            raise ValueError(f'Missing historical home-prior {year}/{name}.json; fetch the exact preceding three seasons')
        result[name] = saved
    return result


def season_history(year, target, sources, corrections):
    observed = instant(sources['games']['retrieved_at'])
    boundary = dt.datetime(target, 8, 1, tzinfo=UTC)
    end = season_end(year)
    if end > observed or end > boundary or year not in years_for(target):
        raise ValueError(f'Historical home-prior season {year} is not complete before season {target}')
    raw = sources['games']['payload']
    start = dt.datetime(year, 8, 1, tzinfo=UTC)
    if any(not start <= instant(g['startDate']) < end for g in raw):
        raise ValueError(f'Historical game date is outside season {year}')
    # No fabricated weekly calendar: earlier home-history years need only the
    # provider's season, seasonType, final scores, roster, and venue designation.
    normalized = normalize(year, sources['teams']['payload'], None, raw, observed, require_calendar=False)
    inputs = prepare(normalized, raw, corrections, cutoff=end)
    games = [{'season': year, 'id': g['id'], 'home_id': g['home_id'], 'away_id': g['away_id'],
              'venue': int(not g['neutral_site']), 'margin': g['home_points'] - g['away_points']}
             for g in inputs['games']]
    if len(games) < 100:
        raise ValueError(f'Historical home-prior season {year} has only {len(games)} confirmed FBS–FBS games')
    audit = {'season': year, 'games': len(games), 'fbs_teams': len(inputs['teams']),
             'membership_source': 'CFBD season FBS roster; stable team IDs',
             'season_boundary': end.isoformat(), 'scope': 'completed regular season; no weekly calendar required',
             'venue_corrections': inputs['venue_corrections'],
             'sources': {name: {k: s[k] for k in ('source', 'parameters', 'payload_sha256')}
                         for name, s in sources.items()}}
    return games, audit


def load_history(season, *, root=DATA, corrections_path=CORRECTIONS):
    corrections = json.loads(Path(corrections_path).read_text())
    games, audit = [], []
    for year in years_for(season):
        rows, record = season_history(year, season, read_sources(year, root), corrections)
        games.extend(rows); audit.append(record)
    identity = {'years': years_for(season), 'games': games, 'audit': audit}
    return {**identity, 'input_sha256': digest(identity)}


def history_available(season, *, root=DATA):
    for year in years_for(season):
        if not all((Path(root) / str(year) / (name + '.json')).exists() for name in endpoints(year)):
            return False
        sources = read_sources(year, root)
        if instant(sources['games']['retrieved_at']) < season_end(year):
            return False
    return True


def ensure_history(season, key, *, root=DATA, fetcher=fetch, now=None):
    """Validate complete windows before writing any newly fetched files."""
    now = now or dt.datetime.now(UTC)
    corrections = json.loads(CORRECTIONS.read_text())
    writes, requests = [], 0
    for year in years_for(season):
        sources = {}
        for name, (endpoint, params) in endpoints(year).items():
            path = Path(root) / str(year) / (name + '.json')
            saved = read_saved(path, year, endpoint, params)
            if saved is None:
                payload = fetcher(endpoint, params, key)
                saved = envelope(year, endpoint, params, payload, now.isoformat())
                writes.append((path, saved)); requests += 1
            sources[name] = saved
        # A prior season may have been cached while it was still in progress.
        if instant(sources['games']['retrieved_at']) < season_end(year) <= now:
            endpoint, params = endpoints(year)['games']
            saved = envelope(year, endpoint, params, fetcher(endpoint, params, key), now.isoformat())
            sources['games'] = saved
            writes.append((Path(root) / str(year) / 'games.json', saved)); requests += 1
        season_history(year, season, sources, corrections)
    for path, value in writes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded(value))
    return requests
