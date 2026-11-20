"""Offline poll parsing/cache checks. No API calls, model imports or fits."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from sync_data import ROOT, UTC, encoded, envelope
from sync_polls import normalize, sync_polls

TEAMS = [{'id': 1, 'school': 'Alpha'}, {'id': 2, 'school': 'Beta'}, {'id': 3, 'school': 'Gamma'}]
NOW = dt.datetime(2026, 11, 20, tzinfo=UTC)


def polls(season=2026):
    return [{'season': season, 'seasonType': 'regular', 'week': 12, 'polls': [
        {'poll': 'AP Top 25', 'ranks': [{'rank': 1, 'teamId': 1, 'school': 'Alpha'},
                                     {'rank': 2, 'teamId': 2, 'school': 'Beta'},
                                     {'rank': 2, 'teamId': 3, 'school': 'Gamma'}]},
        {'poll': 'Playoff Committee Rankings', 'isFinal': False,
         'ranks': [{'rank': 1, 'teamId': 2, 'school': 'Beta'}]},
        {'poll': 'Coaches Poll', 'ranks': []}]}]


class PollTests(unittest.TestCase):
    def test_editions_ids_ties_and_legacy_names(self):
        payload = polls()
        payload[0]['polls'][0]['ranks'][0].pop('teamId')
        final = copy.deepcopy(payload[0]['polls'][1])
        final['isFinal'] = True
        payload[0]['polls'].append(final)
        payload.append({'season': 2026, 'seasonType': 'postseason', 'week': 1,
                        'polls': [payload[0]['polls'][0]]})
        result = normalize(2026, payload, TEAMS)
        self.assertEqual([r['rank'] for r in result[0]['ranks']], [1, 2, 2])
        self.assertEqual({r['id'] for r in result}, {'ap-regular-12', 'cfp-regular-12',
                         'cfp-regular-12-final', 'ap-postseason-1'})
        self.assertEqual(result[0]['ranks'][0]['id'], 1)

    def test_reject_wrong_season_duplicate_unknown_and_invalid_rank(self):
        for mutation in ('season', 'duplicate', 'unknown', 'rank', 'ambiguous'):
            with self.subTest(mutation=mutation):
                payload = polls()
                if mutation == 'season':
                    payload[0]['season'] = 2025
                elif mutation == 'duplicate':
                    payload[0]['polls'][0]['ranks'].append(payload[0]['polls'][0]['ranks'][0])
                elif mutation == 'unknown':
                    payload[0]['polls'][0]['ranks'][0]['teamId'] = 999
                elif mutation == 'rank':
                    payload[0]['polls'][0]['ranks'][0]['rank'] = 0
                else:
                    other = copy.deepcopy(payload[0])
                    other['polls'][0]['ranks'][1]['rank'] = 3
                    payload.append(other)
                with self.assertRaises(ValueError):
                    normalize(2026, payload, TEAMS)

    def test_empty_poll_is_unavailable(self):
        self.assertEqual(normalize(2026, [], TEAMS), [])
        self.assertEqual(normalize(2026, [{'season': 2026, 'seasonType': 'regular', 'week': 1,
                         'polls': [{'poll': 'AP Top 25', 'ranks': []}]}], TEAMS), [])

    def test_cache_refresh_provenance_and_failure_preservation(self):
        # Less than 100 KB, contained in the project and removed even on failure.
        parent = ROOT / '.codex-tmp' / 'cfb-polls-review'
        parent.mkdir(parents=True, exist_ok=False)
        try:
            with tempfile.TemporaryDirectory(dir=parent) as temporary:
                data, public = Path(temporary) / 'source', Path(temporary) / 'public'
                for season in (2024, 2026):
                    folder = data / str(season)
                    folder.mkdir(parents=True)
                    (folder / 'teams.json').write_bytes(encoded(envelope(season, '/teams/fbs',
                        {'year': season}, TEAMS, NOW.isoformat())))
                calls = []
                def fetcher(path, parameters, key):
                    calls.append((path, parameters))
                    return polls(parameters['year'])
                def sync(season=2026, **kwargs):
                    return sync_polls(season, 'fixture-key', destination=data, public=public,
                                      fetcher=fetcher, **kwargs)
                self.assertEqual(sync(now=NOW)['requests'], 1)
                before = (public / '2026/polls.json').read_bytes()
                result = json.loads(before)
                self.assertEqual(result['editions'][0]['week'], 12)
                self.assertEqual(sync(now=NOW + dt.timedelta(hours=1))['requests'], 0)
                self.assertEqual((public / '2026/polls.json').read_bytes(), before)
                self.assertEqual(sync(now=NOW + dt.timedelta(hours=7))['requests'], 1)
                self.assertEqual(calls[0], ('/rankings', {'year': 2026, 'seasonType': 'both'}))
                self.assertEqual(sync(2024, now=NOW)['requests'], 1)
                self.assertEqual(sync(2024, now=NOW + dt.timedelta(days=30))['requests'], 0)
                before = (public / '2026/polls.json').read_bytes()
                source_before = (data / '2026/polls.json').read_bytes()
                with self.assertRaisesRegex(ValueError, 'disappeared'):
                    sync_polls(2026, 'fixture-key', destination=data, public=public,
                               now=NOW + dt.timedelta(days=1), fetcher=lambda *args: [])
                self.assertEqual((public / '2026/polls.json').read_bytes(), before)
                self.assertEqual((data / '2026/polls.json').read_bytes(), source_before)
                stored = json.loads(source_before)
                stored['payload_sha256'] = 'corrupted'
                (data / '2026/polls.json').write_bytes(encoded(stored))
                with self.assertRaisesRegex(ValueError, 'provenance'):
                    sync(now=NOW + dt.timedelta(days=1))
        finally:
            parent.rmdir()


if __name__ == '__main__':
    unittest.main()
