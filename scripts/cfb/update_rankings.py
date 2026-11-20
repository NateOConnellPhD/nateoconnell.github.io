"""Refresh the current season and publish immutable, checked website snapshots.

Two phases let Actions skip numerical installation when the published result
already matches the inputs and implementation. No browser triggers this code.
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import os
from pathlib import Path
import sys

from season_inputs import load_inputs
from sync_data import ROOT, UTC, digest, encoded, instant, sync

PUBLIC = ROOT / 'assets' / 'data' / 'cfb'
TASK = ROOT / '.codex-tmp' / 'cfb-refit'
PLAN = TASK / 'update-plan.json'
SCHEMA = 'margin-of-merit-index-v1'
SOURCES = ('model.py', 'refit_2024.py', 'loo_scoring.py', 'ranking_policy.py',
           'season_inputs.py', 'fit_saved_season.py', 'requirements.txt', 'update_rankings.py',
           'posterior_summary.py', 'historical_rankings.py')


def current_season(now):
    return now.year if now.month >= 8 else now.year - 1


def request_key(inputs):
    import hashlib
    return digest({'inputs': inputs['fit_input_sha256'], 'venue_corrections': inputs['venue_corrections_sha256'],
                   'through_week': inputs.get('through_week'),
                   'sources': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in SOURCES}, 'seed': 20261120, 'exact_loo': True})


def read_index(destination=PUBLIC):
    path = destination / 'index.json'
    index = json.loads(path.read_text()) if path.exists() else {
        'schema': SCHEMA, 'latest': None, 'snapshots': [], 'last_attempt': None}
    if index.get('schema') != SCHEMA or not isinstance(index.get('snapshots'), list):
        raise ValueError('Unrecognized ranking archive index')
    return index


def write_index(index, destination=PUBLIC):
    destination.mkdir(parents=True, exist_ok=True)
    # Git commits this index and all newly created snapshots together.
    (destination / 'index.json').write_bytes(encoded(index))


def matching_snapshot(index, key, destination=PUBLIC, *, historical=False):
    seen_seasons = set()
    for row in index['snapshots']:
        # Only the newest published result for a season can make an update a
        # no-op. If a provider correction restores an older input set, rerun the
        # cache-aware pipeline so the newer, incorrect result is superseded.
        window = (row['season'], row['week']) if historical else row['season']
        if window in seen_seasons:
            continue
        # Historical reconstructions and observed live updates are separate
        # windows, even when their included game sets happen to coincide.
        if historical and row.get('kind') != 'reconstruction':
            continue
        seen_seasons.add(window)
        if row['request_key'] != key:
            continue
        path = destination / row['json']
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Invalid snapshot path')
        result = json.loads(path.read_text())
        if digest(result) != row['sha256'] or not result['publication_ready']:
            raise ValueError('Saved published snapshot failed its integrity check')
        return row
    return None


def validate_candidate(result, inputs):
    if (result['season'] != inputs['season'] or result['games'] != len(inputs['games'])
            or result['identity']['inputs']['fit_input_sha256'] != inputs['fit_input_sha256']):
        raise ValueError('Candidate does not match the saved season inputs')
    d, loo = result['sampling_diagnostics'], result['loo_diagnostics']
    if (not d['sampling_checks_passed'] or d['max_rank_normalized_rhat'] > 1.01
            or min(d['min_bulk_ess'], d['min_tail_ess']) < 400
            or d['divergences'] or d['tree_depth_limit_hits'] or min(d['bfmi_by_chain']) < .3):
        raise ValueError('Candidate failed sampling requirements')
    if (loo['unreliable_games'] != 0
            or loo.get('psis_unreliable_games', 0) != loo.get('exact_refits', 0)
            or loo.get('max_transport_mean_error', math.inf) > .005):
        raise ValueError('Candidate failed LOO/transport requirements')
    # Reproduce the published policy from its saved browser inputs. A snapshot
    # must not publish an order that the reader controls cannot reproduce.
    from ranking_policy import CANONICAL, order_policy, prepare_policy
    policy_input = result['policy_inputs']
    expected = order_policy(prepare_policy(inputs['teams'], inputs['games'], policy_input['means'],
                                          policy_input['probabilities'], season=inputs['season'],
                                          specification=CANONICAL))
    for field in ('specification', 'policy_sha256', 'policy_inputs', 'order', 'raw_order',
                  'unranked', 'confidence_lock_count', 'protected_team_ids', 'protection_exceptions', 'audit'):
        if result[field] != expected[field]:
            raise ValueError('Candidate v4 policy replay failed: ' + field)
    rows = result['teams']
    if len(rows) != len(inputs['teams']) or {r['id'] for r in rows} != {t['id'] for t in inputs['teams']}:
        raise ValueError('Candidate roster does not match the season roster')
    ranked = [r for r in rows if r['status'] == 'ranked']
    if sorted(r['rank'] for r in ranked) != list(range(1, len(ranked) + 1)):
        raise ValueError('Candidate ranks must be consecutive and unique')
    if [r['id'] for r in sorted(ranked, key=lambda r: r['rank'])] != result['order']:
        raise ValueError('Candidate rank order is inconsistent')
    counts = {t['id']: [0, 0] for t in inputs['teams']}
    means = dict(zip((t['id'] for t in inputs['teams']), policy_input['means']))
    for g in inputs['games']:
        home_won = g['home_points'] > g['away_points']
        counts[g['home_id']][int(not home_won)] += 1
        counts[g['away_id']][int(home_won)] += 1
    for row in rows:
        if not math.isclose(row['merit_mean'], means[row['id']], rel_tol=0, abs_tol=1e-12):
            raise ValueError('Policy means do not match published merit summaries')
        if [row['wins_fbs'], row['losses_fbs']] != counts[row['id']]:
            raise ValueError('Published records do not match eligible games')
        if row['status'] != 'ranked':
            if sum(counts[row['id']]) or row['rank'] is not None:
                raise ValueError('A team with eligible games was left unranked')
            continue
        for stem in ('merit', 'sos', 'raw_rank'):
            values = [row[stem + suffix] for suffix in ('_lo90', '_mean', '_hi90')]
            if not all(math.isfinite(x) for x in values) or values[0] > values[2]:
                raise ValueError('Invalid uncertainty summary')
        for k in (8, 10, 25):
            p = row[f'p_raw_merit_top{k}']
            if not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError('Invalid top-K probability')
    for k in (8, 10, 25):
        if not math.isclose(sum(r[f'p_raw_merit_top{k}'] for r in ranked), min(k, len(ranked)), abs_tol=1e-8):
            raise ValueError('Top-K probabilities do not sum to K')
    # Reject nonfinite values anywhere, even outside the displayed fields.
    if 'posterior' in result:
        from posterior_summary import validate
        validate(result)
    encoded(result)


def publish(result, inputs, key, now, destination=PUBLIC):
    validate_candidate(result, inputs)
    week = inputs.get('through_week')
    kind = 'reconstruction' if week is not None else 'observed'
    if week is None:
        week = max(g['week'] for g in inputs['games'])
    snapshot = {**result, 'schema': 'margin-of-merit-snapshot-v1',
                'status': 'published', 'publication_ready': True, 'request_key': key,
                'published_at': now.isoformat(), 'data_observed_at': inputs['source']['games']['retrieved_at'],
                'latest_game_kickoff': max(g['start_date'] for g in inputs['games']),
                'week': week, 'kind': kind,
                'scope': 'Completed regular-season FBS–FBS games, including conference championships; no bowls/CFP.',
                'game_ids': [g['id'] for g in inputs['games']]}
    checksum = digest(snapshot)
    ident = f"{inputs['season']}-w{week:02d}-{checksum[:16]}"
    relative = Path('seasons') / str(inputs['season']) / ident
    json_path = destination / relative.with_suffix('.json')
    body = encoded(snapshot)
    if json_path.exists() and json_path.read_bytes() != body:
        raise ValueError('Refusing to replace an immutable historical snapshot')
    columns = ('rank', 'name', 'conference', 'wins_fbs', 'losses_fbs', 'merit_mean', 'merit_median', 'merit_sd', 'merit_lo90',
               'merit_hi90', 'raw_merit_rank', 'raw_rank_lo90', 'raw_rank_hi90', 'p_raw_merit_top8',
               'p_raw_merit_top10', 'p_raw_merit_top25', 'raw_rank_mean', 'raw_rank_median', 'raw_rank_sd',
               'sos_median', 'sos_sd', 'sos_lo90', 'sos_hi90', 'sos_mean')
    # CSV defaults to CRLF. Use repository-safe LF endings so generated rows
    # pass the workflow's whitespace check, including rows with empty fields.
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(snapshot['teams'])
    index = read_index(destination)
    row = {'id': ident, 'season': inputs['season'], 'week': week, 'games': len(inputs['games']), 'kind': kind,
           'published_at': snapshot['published_at'], 'data_observed_at': snapshot['data_observed_at'],
           'data_cutoff': snapshot['data_cutoff'], 'request_key': key, 'sha256': checksum,
           'json': relative.with_suffix('.json').as_posix(), 'csv': relative.with_suffix('.csv').as_posix()}
    index['snapshots'] = [r for r in index['snapshots'] if r['id'] != ident] + [row]
    index['snapshots'].sort(key=lambda r: (r['season'], instant(r['data_cutoff']), instant(r['published_at'])), reverse=True)
    index['latest'] = index['snapshots'][0]['id']
    if kind == 'observed':
        index['last_attempt'] = {'season': inputs['season'], 'at': now.isoformat(), 'status': 'updated'}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes(body)
    (destination / relative.with_suffix('.csv')).write_text(output.getvalue())
    from historical_rankings import write_series
    write_series(index, inputs['season'], destination)
    write_index(index, destination)
    return row


def prepare(season, refresh_metadata=False):
    now = dt.datetime.now(UTC)
    year = current_season(now) if season == 'current' else int(season)
    if not 2024 <= year <= now.year:
        raise ValueError('Use 2024 or later; earlier conference policies need explicit configuration')
    fetched = sync(year, os.environ.get('CFBD_API_KEY', ''), refresh_metadata=refresh_metadata)
    inputs = load_inputs(year)
    key = request_key(inputs)
    reusable = matching_snapshot(read_index(), key)
    TASK.mkdir(parents=True, exist_ok=True)
    plan = {'season': year, 'key': key, 'needs_fit': reusable is None, 'requests': fetched['requests']}
    PLAN.write_bytes(encoded(plan))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as handle:
            handle.write(f"season={year}\nkey={key}\nneeds_fit={str(plan['needs_fit']).lower()}\n")
    print(json.dumps(plan), flush=True)


def complete(destination=PUBLIC):
    plan = json.loads(PLAN.read_text())
    week = plan.get('through_week')
    inputs = load_inputs(plan['season'], through_week=week)
    if request_key(inputs) != plan['key']:
        raise ValueError('Inputs or implementation changed after preparing the update')
    index = read_index(destination)
    previous = matching_snapshot(index, plan['key'], destination, historical=week is not None)
    if previous:
        index['last_attempt'] = {'season': plan['season'], 'at': dt.datetime.now(UTC).isoformat(), 'status': 'unchanged'}
        write_index(index, destination)
        print('Published ranking already matches; no installation, HMC, or LOO calculation needed.')
        return previous
    from fit_saved_season import run
    from posterior_summary import attach
    result = run(plan['season'], through_week=week, exact_loo=True)
    attach(result, inputs, TASK)
    row = publish(result, inputs, plan['key'], dt.datetime.now(UTC), destination)
    print(json.dumps({'published': row['id'], 'season': row['season'], 'games': row['games']}))
    return row


def record_failure(season, destination=PUBLIC, *, historical=False):
    index = read_index(destination)
    index['backfill' if historical else 'last_attempt'] = {
        'season': season, 'at': dt.datetime.now(UTC).isoformat(), 'status': 'failed'}
    write_index(index, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('prepare', 'complete', 'failed'))
    parser.add_argument('--season', default='current')
    parser.add_argument('--refresh-metadata', action='store_true')
    parser.add_argument('--history', action='store_true', help='Resume one missing weekly reconstruction, 2024 onward')
    args = parser.parse_args()
    if args.phase == 'prepare':
        if args.history:
            from historical_rankings import prepare_history
            prepare_history()
        else:
            prepare(args.season, args.refresh_metadata)
    elif args.phase == 'failed':
        plan = json.loads(PLAN.read_text())
        record_failure(plan['season'], historical=plan.get('through_week') is not None)
    else:
        if not json.loads(PLAN.read_text()).get('needs_fit', True) and json.loads(PLAN.read_text()).get('history_done'):
            print('All eligible historical weeks are saved; nothing to fit.')
            return
        row = complete()
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as handle:
                handle.write(f"## Margin of Merit: {row['season']}\n\n{row['games']} completed FBS–FBS games. "
                             f"[View rankings](https://nateoconnell.com/blog/cfb/)\n\n"
                             f"Saved snapshot: `{row['id']}`. The following step commits the files and requests a Pages build.\n")


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('Ranking update stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
