"""Cache AP/CFP editions independently of model inputs, fits and snapshots.

One rankings request retrieves a season's polls. Completed seasons are reused;
the active season is refreshed by a separate, lightweight scheduled workflow.
"""
import datetime as dt
import json
import os
from pathlib import Path

from sync_data import (API, DATA, ROOT, UTC, encoded, envelope, fetch,
                       instant, integer, read_saved, text)

PUBLIC = ROOT / 'assets' / 'data' / 'cfb' / 'seasons'
POLL_NAMES = {'AP Top 25': 'ap', 'Playoff Committee Rankings': 'cfp'}
SCHEMA = 'margin-of-merit-polls-v1'


def normalize(season, payload, teams):
    roster = {integer(t.get('id'), 'team.id', 1): t for t in teams}
    names = {text(t.get('school'), 'school').casefold(): t['id'] for t in teams}
    editions = {}
    for week in payload:
        if week.get('season') != season:
            raise ValueError('Poll response contains another season')
        kind = week.get('seasonType')
        if kind not in ('regular', 'postseason'):
            raise ValueError('Unexpected poll season type')
        number = integer(week.get('week'), 'poll week')
        if not isinstance(week.get('polls'), list):
            raise ValueError('Expected polls array')
        for poll in week['polls']:
            name = POLL_NAMES.get(poll.get('poll'))
            if not name:
                continue
            label = f"{season} {kind} week {number}, {poll['poll']}"
            final = poll.get('isFinal')
            # CFBD's Poll schema permits null; older responses may omit it.
            # Only an explicit true marks an edition as final in the UI.
            if final is not None and type(final) is not bool:
                raise ValueError(f'Invalid isFinal for {label}: expected boolean or null')
            final = final is True
            if not isinstance(poll.get('ranks'), list):
                raise ValueError(f'Invalid ranks for {label}: expected an array')
            if not poll['ranks']:
                continue  # An empty edition is unavailable, not 138 unranked teams.
            ranks, seen = [], set()
            for rank in poll['ranks']:
                if 'rank' in rank and rank['rank'] is None:
                    continue  # A provider-unranked entry has no Top 25 position.
                position = integer(rank.get('rank'), 'poll rank', 1)
                if position > 25:
                    continue  # Receiving votes is not a Top 25 rank.
                school = text(rank.get('school'), 'poll school')
                ident = rank.get('teamId')
                if ident is None:
                    ident = names.get(school.casefold())  # Exact match for older API responses only.
                if type(ident) is not int or ident not in roster:
                    raise ValueError('Poll team does not match the saved FBS roster: ' + school)
                if ident in seen:
                    raise ValueError('Duplicate team in poll')
                seen.add(ident)
                ranks.append({'id': ident, 'rank': position, 'name': roster[ident]['school']})
            if not ranks or min(r['rank'] for r in ranks) != 1:
                raise ValueError('Poll has no first-ranked team')
            # Ties are valid; team IDs, not rank numbers, must be unique.
            ident = f'{name}-{kind}-{number}' + ('-final' if final else '')
            edition = {'id': ident, 'poll': name, 'week': number, 'season_type': kind,
                       'final': final, 'ranks': sorted(ranks, key=lambda r: (r['rank'], r['id']))}
            if ident in editions and editions[ident] != edition:
                raise ValueError('Conflicting copies of the same poll edition')
            editions[ident] = edition
    return sorted(editions.values(), key=lambda e: (e['season_type'] != 'regular', e['week'], e['poll'], e['final']))


def sync_polls(season, key, *, destination=DATA, public=PUBLIC, now=None, fetcher=fetch):
    now = now or dt.datetime.now(UTC)
    if type(season) is not int or not 2002 <= season <= now.year:
        raise ValueError('Poll season must be from 2002 through the current year')
    folder = Path(destination) / str(season)
    teams = read_saved(folder / 'teams.json', season, '/teams/fbs', {'year': season})
    if teams is None:
        raise ValueError('Sync the season roster before its polls')
    parameters = {'year': season, 'seasonType': 'both'}
    old = read_saved(folder / 'polls.json', season, '/rankings', parameters)
    # A season checked after the postseason has finished is immutable unless
    # an owner explicitly removes that cached source to request corrections.
    closed = dt.datetime(season + 1, 2, 1, tzinfo=UTC)
    cached = old and (instant(old['retrieved_at']) >= closed or
                      now - instant(old['retrieved_at']) < dt.timedelta(hours=6))
    if cached:
        fresh, calls = old, 0
    else:
        key = key.strip()
        if not key or key.lower().startswith('bearer ') or any(c.isspace() for c in key):
            raise ValueError('Set CFBD_API_KEY to the API key only, without a Bearer prefix')
        fresh = envelope(season, '/rankings', parameters,
                         fetcher('/rankings', parameters, key), now.isoformat())
        calls = 1
    editions = normalize(season, fresh['payload'], teams['payload'])
    if old:
        previous = normalize(season, old['payload'], teams['payload'])
        if not {p['id'] for p in previous} <= {p['id'] for p in editions}:
            raise ValueError('Previously saved poll editions disappeared; cached polls were preserved')
    result = {'schema': SCHEMA, 'season': season, 'source': API + '/rankings',
              'retrieved_at': fresh['retrieved_at'], 'source_sha256': fresh['payload_sha256'],
              'week_convention': 'Provider poll-week labels; release dates are not supplied by this endpoint.',
              'editions': editions}
    # Validate the complete season before replacing either file. The workflow
    # commits raw provenance and the compact public file together.
    target = Path(public) / str(season) / 'polls.json'
    source_body, public_body = encoded(fresh), encoded(result)
    target.parent.mkdir(parents=True, exist_ok=True)
    for path, body in ((folder / 'polls.json', source_body), (target, public_body)):
        if not path.exists() or path.read_bytes() != body:
            path.write_bytes(body)
    return {'season': season, 'requests': calls, 'editions': len(editions)}


def main():
    # Only seasons with a saved, checked roster are eligible. No new roster,
    # game fetch, numerical environment, or HMC run is triggered here.
    seasons = sorted(int(p.name) for p in DATA.iterdir()
                     if p.is_dir() and p.name.isdigit() and int(p.name) >= 2002 and (p / 'teams.json').exists())
    for season in seasons:
        print(json.dumps(sync_polls(season, os.environ.get('CFBD_API_KEY', ''))), flush=True)


if __name__ == '__main__':
    main()
