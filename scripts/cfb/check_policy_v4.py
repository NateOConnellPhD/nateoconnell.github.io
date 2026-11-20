"""Offline v4 parity and optional private-handoff replay. No files are written.

Usage: NODE=/path/to/node python3 -B scripts/cfb/check_policy_v4.py [--fixture DIR]
The optional DIR contains the handoff's saved NPZ, scores, and expected CSVs.
Only the small, non-object NPY arrays needed for policy replay are read. This
stdlib reader avoids installing a numerical environment for an ordering check.
"""
import argparse
import ast
import csv
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import unittest
import zipfile

from ranking_policy import CANONICAL, PolicyConflict, order_policy, prepare_policy
from test_ranking_policy import RankingTests, case


def parity(states):
    expected = []
    for state in states:
        try:
            r = order_policy(state)
            expected.append({key: r[key] for key in ('specification', 'order', 'raw_order', 'unranked',
                'confidence_lock_count', 'protected_team_ids', 'protection_exceptions', 'audit')})
        except PolicyConflict as error:
            expected.append({'error': True, 'decision': error.decision, 'audit': error.audit})
    process = subprocess.run([os.environ.get('NODE', 'node'), str(Path(__file__).with_name('check_policy_js.cjs'))],
        input=json.dumps([{'input': s['payload'], 'settings': s['specification']} for s in states]),
        text=True, capture_output=True, check=True, timeout=60)
    actual = json.loads(process.stdout)
    for i, (a, e) in enumerate(zip(actual, expected)):
        if a != e:
            raise AssertionError(f'Python/JavaScript parity failed in case {i}: ' +
                                 ', '.join(k for k in e if a.get(k) != e[k]))
    assert len(actual) == len(expected)
    print(f'Python/JavaScript orders and full audits match in {len(states)} cases.')


def array(archive, name):
    entry = archive.getinfo(name + '.npy')
    if entry.file_size > 8_000_000:
        raise ValueError('Unexpectedly large fixture array')
    f = io.BytesIO(archive.read(entry))
    signature = f.read(8)
    if signature[:6] != b'\x93NUMPY' or signature[6] not in (1, 2):
        raise ValueError('Unsupported fixture array')
    size = 2 if signature[6] == 1 else 4
    length = int.from_bytes(f.read(size), 'little')
    header = ast.literal_eval(f.read(length).decode('latin1'))
    if header['fortran_order']:
        raise ValueError('Expected row-major fixture array')
    body = f.read(); dtype = header['descr']
    if dtype == '<f8':
        values = [v[0] for v in struct.iter_unpack('<d', body)]
    elif dtype.startswith('<U'):
        width = 4 * int(dtype[2:])
        values = [body[i:i+width].decode('utf-32-le').rstrip('\0') for i in range(0, len(body), width)]
    else:
        raise ValueError('Unsupported fixture dtype; object arrays are never loaded')
    return header['shape'], values


def read_csv(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def fixture_replay(folder):
    with zipfile.ZipFile(folder / '2026_merit_draws.npz') as z:
        _, names = array(z, 'teams')
        (count, n), flat = array(z, 'merit')
    assert n == len(names) and len(flat) == n * count
    columns = [flat[i::n] for i in range(n)]
    means = [sum(c) / count for c in columns]
    p = [[.5] * n for _ in range(n)]
    for i in range(n):
        for j in range(i+1, n):
            greater = equal = 0
            for a, b in zip(columns[i], columns[j]):
                greater += a > b; equal += a == b
            p[i][j] = greater / count + .5 * equal / count
            p[j][i] = 1 - p[i][j]
    roster = {}
    games = []
    for row in read_csv(folder / '2026_FBS_completed_games.csv'):
        for side in ('home', 'away'):
            team = dict(id=int(row[side+'_id']), name=row[side+'_team'], conference=row[side+'_conference'])
            if team['name'] in roster and roster[team['name']] != team:
                raise ValueError('Inconsistent fixture roster')
            roster[team['name']] = team
        games.append(dict(id=int(row['game_id']), season=int(row['season']), season_type=row['season_type'],
            completed=row['completed'] == 'True', eligible=row['completed'] == 'True',
            home_id=int(row['home_id']), away_id=int(row['away_id']),
            home_points=int(float(row['home_points'])), away_points=int(float(row['away_points']))))
    teams = [roster[name] for name in names]
    states = []
    for expected in read_csv(folder / '2026_MOM_v4_SLIDER_SENSITIVITY.csv'):
        spec = replace(CANONICAL, **{k: float(expected[k]) for k in ('merit_protection', 'head_to_head', 'common_opponents')})
        state = prepare_policy(teams, games, means, p, season=2026, specification=spec)
        states.append(state); r = order_policy(state)
        raw = {ident: k for k, ident in enumerate(r['raw_order'])}
        movement = [raw[ident] - k for k, ident in enumerate(r['order'])]
        assert sum(m != 0 for m in movement) == int(expected['n_changes']), expected['case']
        assert max(abs(m) for m in movement) == int(expected['max_rank_movement']), expected['case']
        for kind, key in (('head_to_head', 'n_h2h_accepted'), ('common_opponents', 'n_common_accepted')):
            assert sum(a['type'] == kind and a['status'] == 'accepted' for a in r['audit']) == int(expected[key]), expected['case']
        assert sum(a['status'] == 'blocked_by_conflict' for a in r['audit']) == int(expected['n_conflicts']), expected['case']
        by_id = {t['id']: t['name'] for t in teams}
        assert [by_id[i] for i in r['order'][:25]] == expected['top25'].split(';'), expected['case']
        if expected['case'] == 'default':
            expected_rows = read_csv(folder / '2026_MOM_v4_ALL_TEAMS.csv')
            assert [by_id[i] for i in r['order']] == [t['team'] for t in expected_rows]
    parity(states)
    print(f'Matched all {n} default ranks and all 8 supplied sensitivity scenarios ({count} saved draws; {len(games)} games).')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(RankingTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    states = [case(), case(probabilities={(1, 2): .9}), case(probabilities={(1, 2): .900001}),
        case(probabilities={(1, 2): .85}, merit_protection=.8, head_to_head=.95),
        case(n=4, pairs=((3, 1), (2, 4), (4, 2)), merit_protection=.7,
             probabilities={(1, 2): .71, (2, 3): .73, (1, 3): .65}),
        case(n=3, pairs=((1, 2), (2, 3), (3, 1)), means=[3, 1, 2]),
        case(n=3, pairs=((1, 2), (2, 1), (1, 3), (3, 2))),
        case(n=3, pairs=((2, 1), (1, 3), (3, 2)), probabilities={(1, 2): .7}, head_to_head=.5),
        case(n=3, pairs=((1, 2), (2, 3), (3, 1)), merit_protection=.5,
             probabilities={(1, 2): .6, (2, 3): .6, (3, 1): .6})]
    parity(states)
    if args.fixture:
        fixture_replay(args.fixture)


if __name__ == '__main__':
    main()
