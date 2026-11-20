"""Resumable weekly reconstruction queue and compact, static season trajectories.

One cutoff per worker. Reuse saved season data; never refetch for a reader or
each historical week. Publish only after the usual HMC/LOO gates succeed.
"""
import datetime as dt
import json
import os

from sync_data import DATA, UTC, encoded, instant, sync
from season_inputs import load_inputs

FIRST_SEASON = 2024  # The specified undefeated-P4 policy starts here.


def closed_weeks(calendar, observed):
    return sorted({w['week'] for w in calendar if w['seasonType'] == 'regular'
                   and w['week'] >= 0 and instant(w['endDate']) <= observed}, reverse=True)


def write_series(index, season, destination):
    """One row per week; revisions remain independently downloadable in index."""
    from update_rankings import digest
    weeks = {}
    for row in index['snapshots']:
        if row['season'] != season or row['week'] in weeks:
            continue
        path = destination / row['json']
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Invalid history path')
        saved = json.loads(path.read_text())
        if digest(saved) != row['sha256']:
            raise ValueError('Historical snapshot integrity check failed')
        fields = ('id', 'name', 'rank', 'raw_merit_rank', 'merit_mean', 'merit_median',
                  'merit_lo90', 'merit_hi90', 'raw_rank_mean', 'raw_rank_median',
                  'raw_rank_lo90', 'raw_rank_hi90', 'wins_fbs', 'losses_fbs')
        weeks[row['week']] = {k: row[k] for k in ('id', 'week', 'data_cutoff', 'json')}
        weeks[row['week']].update(policy_sha256=saved['policy_sha256'], kind=saved.get('kind', 'observed'),
                                 teams=[{k: t.get(k) for k in fields} for t in saved['teams']])
    target = destination / 'seasons' / str(season) / 'history.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded({'schema': 'margin-of-merit-history-v1', 'season': season,
                               'weeks': [weeks[w] for w in sorted(weeks)]}))


def prepare_history():
    from update_rankings import (TASK, PLAN, PUBLIC, current_season, matching_snapshot,
                                 read_index, request_key, write_index)
    now = dt.datetime.now(UTC)
    index = read_index()
    queue, coverage = [], []
    for season in range(current_season(now), FIRST_SEASON - 1, -1):
        folder = DATA / str(season)
        # The live workflow refreshes current-season data. Historical sources
        # are fetched just once; explicit data sync can later apply corrections.
        if not all((folder / (name + '.json')).exists() for name in ('teams', 'calendar', 'games')):
            sync(season, os.environ.get('CFBD_API_KEY', ''))
        calendar = json.loads((folder / 'calendar.json').read_text())['payload']
        observed = instant(json.loads((folder / 'games.json').read_text())['retrieved_at'])
        slots = []
        for depth, week in enumerate(closed_weeks(calendar, min(now, observed))):
            try:
                inputs = load_inputs(season, through_week=week)
            except ValueError as error:
                if str(error) == 'No eligible completed games at the selected cutoff':
                    continue
                raise
            key = request_key(inputs)
            saved = matching_snapshot(index, key, PUBLIC, historical=True)
            slots.append({'week': week, 'snapshot': saved['id'] if saved else None})
            if saved is None:
                queue.append({'season': season, 'through_week': week, 'key': key, 'needs_fit': True, 'depth': depth})
        coverage.append({'season': season, 'weeks': sorted(slots, key=lambda s: s['week'])})
    index['archive'] = coverage
    index['backfill'] = {'status': 'pending' if queue else 'complete', 'remaining': len(queue), 'at': now.isoformat()}
    # Make every season browsable early, then work backward across seasons.
    queue.sort(key=lambda p: (p['depth'], -p['season']))
    plan = {k: v for k, v in queue[0].items() if k != 'depth'} if queue else {
        'season': current_season(now), 'needs_fit': False, 'history_done': True}
    TASK.mkdir(parents=True, exist_ok=True)
    PLAN.write_bytes(encoded(plan))
    write_index(index)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write(f"season={plan['season']}\nkey={plan.get('key', 'complete')}\n"
                         f"needs_fit={str(plan['needs_fit']).lower()}\n"
                         f"continue_history={str(bool(queue)).lower()}\n")
    print(json.dumps({'next': plan, 'remaining': len(queue)}), flush=True)
