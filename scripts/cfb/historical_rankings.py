"""Resumable weekly reconstruction queue and compact, static season trajectories.

One cutoff per worker. Reuse saved season data; never refetch for a reader or
each historical week. Publish only after the usual HMC/LOO gates succeed.
"""
import datetime as dt
import json
import os

from sync_data import DATA, UTC, encoded, instant, sync
from season_inputs import load_fit_inputs as load_inputs
from home_history_inputs import ensure_history, history_available

FIRST_SEASON = 2002  # Earliest season supported by the saved-calendar input path.


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
                  'raw_rank_lo90', 'raw_rank_hi90', 'wins_fbs', 'losses_fbs', 'wins', 'losses')
        weeks[row['week']] = {k: row[k] for k in ('id', 'week', 'data_cutoff', 'json')}
        weeks[row['week']].update(policy_sha256=saved['policy_sha256'], kind=saved.get('kind', 'observed'),
                                 reference_rank=saved['reference_rank'],
                                 teams=[{k: t.get(k) for k in fields} for t in saved['teams']])
        references = {}
        for rank, descriptor in row['references'].items():
            target = destination / descriptor['json']
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Invalid reference history path')
            value = json.loads(target.read_text())
            if digest(value) != descriptor['sha256'] or value['reference_rank'] != int(rank):
                raise ValueError('Reference history integrity check failed')
            references[rank] = {'reference_rank': int(rank), 'policy_sha256': value['policy_sha256'],
                                'teams': [{k: t.get(k) for k in fields} for t in value['teams']]}
        weeks[row['week']]['references'] = references
    target = destination / 'seasons' / str(season) / 'history.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded({'schema': 'margin-of-merit-history-v1', 'season': season,
                               'weeks': [weeks[w] for w in sorted(weeks)]}))


def record_sampling_failure(plan, error):
    """Quarantine only a diagnosed sampling failure, keyed to exact inputs/source.

    A broken import, timeout or arbitrary code error still stops the workflow.
    """
    from update_rankings import read_index, write_index
    from sampling_retry import ExactLOOSamplingError
    from full_fit_retry import FullFitSamplingError
    if not isinstance(error, (ExactLOOSamplingError, FullFitSamplingError)):
        raise TypeError('Only a diagnosed sampling failure can defer an archive week')
    index = read_index()
    failure = {'season': plan['season'], 'week': plan['through_week'], 'key': plan['key'],
               'at': dt.datetime.now(UTC).isoformat(), 'reason': str(error), 'details': error.details}
    index['fit_failures'] = [f for f in index.get('fit_failures', []) if f['key'] != plan['key']] + [failure]
    for season in index.get('archive', []):
        if season['season'] == plan['season']:
            for week in season['weeks']:
                if week['week'] == plan['through_week']:
                    week.update(status='needs_attention', reason='Sampling checks failed')
    index['backfill'] = {**(index.get('backfill') or {}), 'status': 'pending',
                         'at': failure['at'], 'reason': 'A week needs attention; continuing other weeks.'}
    write_index(index)


def prepare_history(retry_failed=False):
    from update_rankings import (TASK, PLAN, PUBLIC, current_season, matching_snapshot,
                                 read_index, request_key, write_index)
    now = dt.datetime.now(UTC)
    index = read_index()
    failures = [] if retry_failed else index.get('fit_failures', [])
    queue, coverage, pending_seasons, unscanned = [], [], [], []
    previous_coverage = {row['season']: row for row in index.get('archive', [])}
    fetched_season = None
    for season in range(current_season(now), FIRST_SEASON - 1, -1):
        folder = DATA / str(season)
        # The live workflow refreshes current-season data. Historical sources
        # are fetched just once; explicit data sync can later apply corrections.
        current_saved = all((folder / (name + '.json')).exists() for name in ('teams', 'calendar', 'games', 'games-fcs'))
        if queue:
            # Finish the newest season first. Do not let an unrelated older
            # import fail while a current-season week is ready to be fitted.
            unscanned.append(season)
            if not current_saved:
                pending_seasons.append(season)
            coverage.append(previous_coverage.get(season, {'season': season, 'weeks': [],
                            'status': 'awaiting_scan' if current_saved else 'awaiting_data'}))
            continue
        if not current_saved or not history_available(season, root=DATA):
            # Discover at most one target season and its home-history window per job, then commit its inputs
            # with the checked result. A later bad season must not discard an
            # entire historical import and cause all those API calls to repeat.
            if fetched_season is not None:
                pending_seasons.append(season)
                coverage.append({'season': season, 'weeks': [], 'status': 'awaiting_data'})
                continue
            try:
                if not current_saved:
                    sync(season, os.environ.get('CFBD_API_KEY', ''))
                ensure_history(season, os.environ.get('CFBD_API_KEY', ''), root=DATA)
            except ValueError as error:
                raise ValueError(f'Historical season {season}: {error}') from error
            fetched_season = season
        calendar = json.loads((folder / 'calendar.json').read_text())['payload']
        observed = min(instant(json.loads((folder / name).read_text())['retrieved_at'])
                       for name in ('games.json', 'games-fcs.json'))
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
            # New inputs/source automatically retry this cutoff. Passed weeks
            # clear a prior failure. Unchanged failed weeks are not rerun forever.
            failures = [f for f in failures if (f['season'], f['week']) != (season, week)
                        or (not saved and f['key'] == key)]
            failed = next((f for f in failures if f['key'] == key), None)
            slots.append({'week': week, 'snapshot': saved['id'] if saved else None,
                          **({'status': 'needs_attention', 'reason': 'Sampling checks failed'} if failed else {})})
            if saved is None and failed is None:
                queue.append({'season': season, 'through_week': week, 'key': key, 'needs_fit': True, 'depth': depth})
        coverage.append({'season': season, 'weeks': sorted(slots, key=lambda s: s['week'])})
    index['archive'] = coverage
    index['fit_failures'] = failures
    pending = bool(queue or pending_seasons or unscanned)
    index['backfill'] = {'status': 'pending' if pending else 'needs_attention' if failures else 'complete', 'remaining': len(queue),
                         'failed_weeks': len(failures),
                         'pending_seasons': pending_seasons, 'unscanned_seasons': unscanned,
                         'first_season': FIRST_SEASON, 'at': now.isoformat()}
    # Latest season first, working backward by week before importing older years.
    queue.sort(key=lambda p: (-p['season'], p['depth']))
    plan = {k: v for k, v in queue[0].items() if k != 'depth'} if queue else {
        'season': current_season(now), 'needs_fit': False,
        'history_done': not pending, 'history_scan_only': pending, 'failed_weeks': len(failures)}
    TASK.mkdir(parents=True, exist_ok=True)
    PLAN.write_bytes(encoded(plan))
    write_index(index)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write(f"season={plan['season']}\nkey={plan.get('key', 'complete')}\n"
                         f"needs_fit={str(plan['needs_fit']).lower()}\n"
                         f"continue_history={str(pending).lower()}\n")
    print(json.dumps({'next': plan, 'remaining': len(queue), 'pending_seasons': pending_seasons}), flush=True)
