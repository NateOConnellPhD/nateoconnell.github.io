"""Publish completed weeks using the existing cached fitting pipeline.

Calendar selection belongs here, outside the numerical request-key sources:
changing when a snapshot becomes current must not invalidate historical fits.
"""
import argparse
import datetime as dt
import json
import os
import sys

import update_rankings as pipeline
from historical_rankings import closed_weeks, prepare_history
from season_inputs import load_inputs
from sync_data import DATA, UTC, encoded, instant, read_saved, sync


def calendar_for(season, root=DATA):
    saved = read_saved(root / str(season) / 'calendar.json', season, '/calendar', {'year': season})
    if saved is None:
        raise ValueError(f'Missing saved calendar for {season}')
    return saved['payload']


def current_plan(season, now, root=DATA, destination=pipeline.PUBLIC):
    saved = read_saved(root / str(season) / 'games.json', season, '/games',
                       {'year': season, 'seasonType': 'both', 'classification': 'fbs'})
    if saved is None:
        raise ValueError(f'Missing saved games for {season}')
    weeks = closed_weeks(calendar_for(season, root), min(now, instant(saved['retrieved_at'])))
    for week in weeks:
        try:
            inputs = load_inputs(season, through_week=week, root=root)
        except ValueError as error:
            if str(error) == 'No eligible completed games at the selected cutoff':
                continue
            raise
        key = pipeline.request_key(inputs)
        reusable = pipeline.matching_snapshot(pipeline.read_index(destination), key, destination, historical=True)
        return {'mode': 'current', 'season': season, 'through_week': week,
                'key': key, 'needs_fit': reusable is None}
    return {'mode': 'current', 'season': season, 'key': 'no-completed-week',
            'needs_fit': False, 'no_completed_week': True}


def mark_completed(index, root=DATA):
    seasons = {r['season'] for r in index['snapshots']}
    ends = {season: {w['week']: instant(w['endDate']) for w in calendar_for(season, root)
                     if w['seasonType'] == 'regular'} for season in seasons}
    for row in index['snapshots']:
        end = ends[row['season']].get(row['week'])
        # Compare with the snapshot's own cutoff, never today's clock. An old
        # partial-week snapshot does not become complete just by getting older.
        row['week_complete'] = bool(end is not None and instant(row['data_cutoff']) >= end)
    complete = [r for r in index['snapshots'] if r['week_complete']]
    latest = max(complete, key=lambda r: (r['season'], r['week'], instant(r['data_cutoff']),
                                        instant(r['published_at'])), default=None)
    index['latest'] = latest['id'] if latest else None
    return index


def refresh_index(destination=pipeline.PUBLIC, root=DATA):
    pipeline.write_index(mark_completed(pipeline.read_index(destination), root), destination)


def prepare(season, refresh_metadata=False):
    now = dt.datetime.now(UTC)
    year = pipeline.current_season(now) if season == 'current' else int(season)
    if not 2002 <= year <= now.year:
        raise ValueError('Use a season from 2002 through the current year')
    fetched = sync(year, os.environ.get('CFBD_API_KEY', ''), refresh_metadata=refresh_metadata)
    plan = current_plan(year, dt.datetime.now(UTC))
    plan['requests'] = fetched['requests']
    pipeline.TASK.mkdir(parents=True, exist_ok=True)
    pipeline.PLAN.write_bytes(encoded(plan))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write(f"season={year}\nkey={plan['key']}\nneeds_fit={str(plan['needs_fit']).lower()}\n")
    print(json.dumps(plan), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'complete', 'failed'))
    parser.add_argument('--season', default='current')
    parser.add_argument('--refresh-metadata', action='store_true')
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    if args.phase == 'prepare':
        if args.history:
            prepare_history()
        else:
            prepare(args.season, args.refresh_metadata)
    else:
        plan = json.loads(pipeline.PLAN.read_text())
        if args.phase == 'failed':
            pipeline.record_failure(plan['season'], historical=plan.get('mode') != 'current')
        elif plan.get('no_completed_week'):
            print('No completed week with eligible games yet; retaining the last published rankings.')
        elif plan.get('history_done'):
            print('All eligible historical weeks are saved; nothing to fit.')
        elif plan.get('history_scan_only'):
            print('Saved historical data; continuing to the next season with eligible games.')
        else:
            row = pipeline.complete()
            if plan.get('mode') == 'current':
                index = pipeline.read_index()
                index['last_attempt'] = {'season': row['season'], 'at': dt.datetime.now(UTC).isoformat(),
                                         'status': 'updated' if plan['needs_fit'] else 'unchanged'}
                pipeline.write_index(index)
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
                    handle.write(f"## Margin of Merit: {row['season']}, through Week {row['week']}\n\n"
                                 f"{row['games']} completed FBS–FBS games. Saved snapshot: `{row['id']}`.\n\n"
                                 "[View rankings](https://nateoconnell.com/blog/cfb/) after the Pages build.\n")
    refresh_index()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('Weekly publication stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
