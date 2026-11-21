"""Fetch and retain one CFBD season; standard library only, no inference.

First sync: FBS roster, calendar, FBS games and FCS games (four requests).
Later syncs: two games requests, reusing metadata. Historical sources are cached. No automatic retry.
All responses are validated before existing saved files are replaced.
"""
import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / '_cfb_data' / 'seasons'
API = 'https://api.collegefootballdata.com'
MAX_RESPONSE = 8 * 1024 * 1024
SCHEMA = 'cfbd-season-v1'
UTC = dt.timezone.utc


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                       allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Missing game/calendar timestamp')
    date = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Game/calendar timestamps must include a time zone')
    return date.astimezone(UTC)


def integer(value, field, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Invalid integer field: ' + field)
    return value


def text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError('Invalid text field: ' + field)
    return value.strip()


def boolean(value, field):
    if type(value) is not bool:
        raise ValueError('Invalid boolean field: ' + field)
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('CFBD redirected the request; credentials were not forwarded')


def fetch(path, parameters, key):
    if path not in ('/games', '/teams/fbs', '/calendar', '/rankings'):
        raise ValueError('Unsupported data endpoint')
    url = API + path + '?' + urllib.parse.urlencode(parameters)
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + key, 'Accept': 'application/json',
        'User-Agent': 'nateoconnell.com Margin of Merit data sync'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as error:
        explanations = {401: 'check the CFBD_API_KEY repository secret',
                        403: 'check endpoint access for this key',
                        429: 'API quota/rate limit reached; retry later'}
        raise ValueError(f'CFBD HTTP {error.code}: ' + explanations.get(error.code, 'try again later')) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Could not reach CFBD; saved data were preserved') from None
    if len(body) > MAX_RESPONSE:
        raise ValueError('CFBD response exceeded the 8 MB limit')
    try:
        rows = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError('CFBD did not return valid JSON') from None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Expected a CFBD array of records')
    return rows


def envelope(season, path, parameters, payload, retrieved_at):
    return {'schema': SCHEMA, 'season': season, 'source': API + path,
            'parameters': parameters, 'retrieved_at': retrieved_at,
            'payload_sha256': digest(payload), 'payload': payload}


def read_saved(path, season, endpoint, parameters):
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    if (result.get('schema') != SCHEMA or result.get('season') != season
            or result.get('source') != API + endpoint or result.get('parameters') != parameters
            or result.get('payload_sha256') != digest(result.get('payload'))):
        raise ValueError('Saved source provenance is invalid: ' + path.name)
    instant(result['retrieved_at'])
    return result


def game_team_context(row, side):
    return (f"season {row.get('season')}, game {row.get('id')}, "
            f"{side} team {row.get(side + 'Team')!r} (ID {row.get(side + 'Id')}), "
            f"classification {row.get(side + 'Classification')!r}")


def fcs_playoff(row, roster):
    """Provider seasonType alone misses FCS playoff games labelled regular.

    Conference title games are retained. CFBD exposes playoff metadata as a
    nested object; the handoff's tabular source calls it playoff_competition.
    """
    if any(roster.get(row.get(side + 'Id'), {}).get('classification') != 'fcs'
           for side in ('home', 'away')):
        return False
    return bool(row.get('playoff_competition') or row.get('playoffCompetition')
                or row.get('playoff')
                or re.search(r'\bFCS\s+Championship\b', str(row.get('notes') or ''), re.I))


def normalize(season, teams, calendar, games, observed_at, *, include_fcs=False, require_calendar=True):
    """Keep future/non-final games for audit, but never in eligible model inputs.

    This describes status observed at retrieval. A later fetch cannot establish
    exact historical completion times; historical weekly reconstruction needs
    explicit dated cutoffs and must retain that qualification.
    """
    roster = {}
    if not teams:
        raise ValueError('Empty season FBS roster')
    for team in teams:
        ident = integer(team.get('id'), 'team.id', 1)
        if ident in roster:
            raise ValueError('Duplicate FBS team ID')
        if team.get('classification') not in (None, 'fbs'):
            raise ValueError('Non-FBS team in season FBS roster')
        roster[ident] = {'id': ident, 'name': text(team.get('school'), 'school'),
                         'conference': team.get('conference')}
    fbs_ids = set(roster)
    if include_fcs:
        for row in games:
            for side in ('home', 'away'):
                if row.get(side + 'Classification') != 'fcs': continue
                ident = integer(row.get(side + 'Id'), side + 'Id', 1)
                team = {'id': ident, 'name': text(row.get(side + 'Team'), side + 'Team'),
                        'conference': row.get(side + 'Conference'), 'classification': 'fcs'}
                if ident in fbs_ids or (ident in roster and roster[ident] != team):
                    raise ValueError('Inconsistent FCS membership in season games: ' + game_team_context(row, side))
                roster[ident] = team
        for ident in fbs_ids: roster[ident]['classification'] = 'fbs'
    weeks = set()
    if require_calendar and not calendar:
        raise ValueError('Empty season calendar')
    for row in calendar or []:
        if row.get('season') != season:
            raise ValueError('Calendar contains another season')
        pair = (text(row.get('seasonType'), 'seasonType'), integer(row.get('week'), 'week'))
        if pair in weeks:
            raise ValueError('Duplicate calendar season-type/week')
        weeks.add(pair)
        if instant(row.get('startDate')) >= instant(row.get('endDate')):
            raise ValueError('Calendar start must precede end')
    if not games:
        raise ValueError('Empty season games response; refusing to replace saved data')
    ids, normalized, excluded = set(), [], Counter()
    for row in games:
        ident = integer(row.get('id'), 'game.id', 1)
        if ident in ids:
            raise ValueError('Duplicate game ID')
        ids.add(ident)
        if row.get('season') != season:
            raise ValueError('Games response contains another season')
        home = integer(row.get('homeId'), 'homeId', 1)
        away = integer(row.get('awayId'), 'awayId', 1)
        if home == away:
            raise ValueError('A team cannot play itself')
        start = instant(row.get('startDate'))
        final = boolean(row.get('completed'), 'completed')
        neutral = boolean(row.get('neutralSite'), 'neutralSite')
        kind = text(row.get('seasonType'), 'seasonType')
        if kind not in ('regular', 'postseason'):
            raise ValueError('Unexpected season type in regular/postseason response')
        week = integer(row.get('week'), 'week')
        if require_calendar and (kind, week) not in weeks:
            raise ValueError('Game week absent from cached calendar; refresh metadata explicitly')
        unclassified = []
        inferred = {}
        for side, team_id in (('home', home), ('away', away)):
            classification = row.get(side + 'Classification')
            # CFBD's game classifications are nullable. Recover only membership
            # established by the season FBS roster or an explicit FCS game row.
            # Never assume that an opponent of an FCS team is also Division I.
            if classification is None:
                classification = 'fbs' if team_id in fbs_ids else roster.get(team_id, {}).get('classification')
                if classification is None:
                    unclassified.append(side)
                    continue
                inferred[side] = classification
            elif classification not in ('fbs', 'fcs', 'ii', 'iii', 'ii/iii'):
                raise ValueError('Unknown game team classification: ' + game_team_context(row, side))
            if (classification == 'fbs') != (team_id in fbs_ids):
                raise ValueError('Game FBS membership disagrees with season roster; review metadata: '
                                 + game_team_context(row, side))
            if include_fcs and team_id in roster and classification != roster[team_id]['classification']:
                raise ValueError('Game classification disagrees with season membership: ' + game_team_context(row, side))
        hp, ap = row.get('homePoints'), row.get('awayPoints')
        if final:
            integer(hp, 'homePoints')
            integer(ap, 'awayPoints')
            if start > observed_at:
                raise ValueError('A future game is marked completed')
        reasons = []
        if fcs_playoff(row, roster):
            reasons.append('fcs_playoff')
        if kind != 'regular':
            reasons.append('postseason_not_in_scope')
        if unclassified:
            reasons.append('unclassified_team')
        elif home not in roster or away not in roster:
            reasons.append('outside_division_i' if include_fcs else 'not_fbs_vs_fbs')
        if not final:
            reasons.append('not_completed')
        if start > observed_at:
            reasons.append('future_game')
        if not reasons and hp == ap:
            raise ValueError('Tied Division I final requires an explicit tie policy')
        excluded.update(reasons)
        game = {'id': ident, 'season': season, 'week': week, 'season_type': kind,
            'start_date': start.isoformat(), 'neutral_site': neutral, 'completed': final,
            'home_id': home, 'away_id': away,
            'home_name': text(row.get('homeTeam'), 'homeTeam'),
            'away_name': text(row.get('awayTeam'), 'awayTeam'),
            'home_conference': row.get('homeConference'), 'away_conference': row.get('awayConference'),
            'home_fbs': home in fbs_ids, 'away_fbs': away in fbs_ids,
            # In-progress scores are never inputs to the model.
            'home_points': hp if final else None, 'away_points': ap if final else None,
            'eligible': not reasons, 'exclusions': reasons}
        if unclassified:
            game['unclassified_sides'] = unclassified
        if inferred:
            game['inferred_classifications'] = inferred
        if 'fcs_playoff' in reasons:
            game['playoff_evidence'] = {key: row[key] for key in
                ('notes', 'playoff', 'playoff_competition', 'playoffCompetition') if row.get(key)}
        normalized.append(game)
    normalized.sort(key=lambda row: (row['start_date'], row['id']))
    roster_list = [roster[key] for key in sorted(roster)]
    eligible = [row for row in normalized if row['eligible']]
    played = {row[key] for row in eligible for key in ('home_id', 'away_id')}
    return {'schema': SCHEMA, 'season': season, 'teams': roster_list, 'games': normalized,
        'model_input_sha256': digest({'schema': SCHEMA, 'season': season, 'teams': roster_list, 'games': eligible}),
        'summary': {'fbs_teams': len(fbs_ids), 'fcs_teams': len(roster)-len(fbs_ids), 'saved_games': len(games), 'eligible_completed_games': len(eligible),
                    'teams_without_fbs_games': sorted(fbs_ids - played),
                    'scope': 'joint_fbs_fcs' if include_fcs else 'fbs_only',
                    'exclusion_counts': dict(sorted(excluded.items())),
                    'publication_ready': False,
                    'note': 'Data validation only. Rankings require model, LOO, policy, and readiness checks.'}}


def merge_games(primary, additional):
    """An FBS/FCS meeting may appear in both responses; count it once."""
    games = {}
    for feed in (primary, additional):
        seen = set()
        for row in feed:
            ident = integer(row.get('id'), 'game.id', 1)
            if ident in seen: raise ValueError('Duplicate game ID within a feed')
            seen.add(ident)
            if ident in games and games[ident] != row:
                raise ValueError('FBS/FCS feeds disagree on a shared game; saved data were preserved')
            games[ident] = row
    return [games[key] for key in sorted(games)]


def sync(season, key, *, destination=DATA, refresh_metadata=False, fetcher=fetch, now=None):
    now = now or dt.datetime.now(UTC)
    if type(season) is not int or not 2002 <= season <= now.year:
        raise ValueError('Season must be from 2002 through the current year')
    key = key.strip()
    if not key or key.lower().startswith('bearer ') or any(c.isspace() for c in key):
        raise ValueError('Set CFBD_API_KEY to the API key only, without a Bearer prefix')
    folder = Path(destination) / str(season)
    endpoints = {'teams.json': ('/teams/fbs', {'year': season}),
                 'calendar.json': ('/calendar', {'year': season}),
                 'games.json': ('/games', {'year': season, 'seasonType': 'both', 'classification': 'fbs'}),
                 'games-fcs.json': ('/games', {'year': season, 'seasonType': 'both', 'classification': 'fcs'})}
    proposed, calls = {}, 0
    for name, (endpoint, parameters) in endpoints.items():
        old = read_saved(folder / name, season, endpoint, parameters)
        if name not in ('games.json', 'games-fcs.json') and old is not None and not refresh_metadata:
            proposed[name] = old
            continue
        payload = fetcher(endpoint, parameters, key)
        if name in ('games.json', 'games-fcs.json') and not payload:
            raise ValueError('Empty ' + name + ' response; joint FBS/FCS coverage cannot be established')
        calls += 1
        fresh = envelope(season, endpoint, parameters, payload, now.isoformat())
        # Reobserving games advances the joint cutoff even when scores are unchanged.
        # Metadata timestamps do not affect that cutoff.
        proposed[name] = old if name not in ('games.json', 'games-fcs.json') and old and old['payload_sha256'] == fresh['payload_sha256'] else fresh
    result = normalize(season, proposed['teams.json']['payload'], proposed['calendar.json']['payload'],
                       merge_games(proposed['games.json']['payload'], proposed['games-fcs.json']['payload']),
                       now, include_fcs=True)
    previous = folder / 'normalized.json'
    old = json.loads(previous.read_text()) if previous.exists() else None
    if old:
        prior_ids = {r['id'] for r in old['games'] if r['eligible']}
        current_ids = {r['id'] for r in result['games'] if r['eligible']}
        # A methodology change may remove explicitly identified playoff games.
        # Missing finals or other upstream changes still stop publication.
        newly_excluded_playoffs = {r['id'] for r in result['games'] if 'fcs_playoff' in r['exclusions']}
        if not prior_ids <= current_ids | newly_excluded_playoffs:
            raise ValueError('Previously eligible final games disappeared; review upstream changes before replacing data')
    proposed['normalized.json'] = result
    changed = [name for name, value in proposed.items()
               if not (folder / name).exists() or (folder / name).read_bytes() != encoded(value)]
    # No file changes are made until every API response and prior-game check passes.
    # Git commits the entire set together; a failed workflow never commits a partial set.
    if changed:
        folder.mkdir(parents=True, exist_ok=True)
        for name in changed:
            (folder / name).write_bytes(encoded(proposed[name]))
    return {'season': season, 'requests': calls, 'changed_files': changed,
            'model_inputs_changed': not old or old['model_input_sha256'] != result['model_input_sha256'],
            'model_input_sha256': result['model_input_sha256'], **result['summary']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--refresh-metadata', action='store_true')
    args = parser.parse_args()
    try:
        result = sync(args.season, os.environ.get('CFBD_API_KEY', ''), refresh_metadata=args.refresh_metadata)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('CFB sync stopped: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as handle:
            handle.write(f"## CFB data sync: {result['season']}\n\n"
                         f"- API requests this run: {result['requests']}\n"
                         f"- FBS teams: {result['fbs_teams']}\n"
                         f"- Saved games: {result['saved_games']}\n"
                         f"- Eligible completed games: {result['eligible_completed_games']}\n"
                         f"- Model inputs changed: {result['model_inputs_changed']}\n\n"
                         'Data connection and validation only; no model ran and no rankings were published.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
