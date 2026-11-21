"""Focused offline ingestion checks; no dependency downloads or API requests."""
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from sync_data import ROOT, UTC, fetch, normalize, sync

NOW = dt.datetime(2026, 11, 20, 12, tzinfo=UTC)


def fixture():
    teams = [{'id': i, 'school': f'Team {i}', 'classification': 'fbs', 'conference': 'Example'} for i in (1, 2, 3)]
    calendar = [{'season': 2026, 'seasonType': kind, 'week': week,
                 'startDate': start, 'endDate': end}
                for kind, week, start, end in (
                    ('regular', 1, '2026-08-24T00:00:00Z', '2026-09-01T00:00:00Z'),
                    ('regular', 14, '2026-11-23T00:00:00Z', '2026-12-01T00:00:00Z'),
                    ('postseason', 1, '2026-12-01T00:00:00Z', '2027-02-01T00:00:00Z'))]
    game = {'id': 101, 'season': 2026, 'week': 1, 'seasonType': 'regular',
            'startDate': '2026-08-29T23:30:00Z', 'completed': True, 'neutralSite': True,
            'homeId': 1, 'awayId': 2, 'homeTeam': 'Team 1', 'awayTeam': 'Team 2',
            'homePoints': 27, 'awayPoints': 21, 'homeClassification': 'fbs',
            'awayClassification': 'fbs', 'homeConference': 'Example', 'awayConference': 'Example'}
    return {'/teams/fbs': teams, '/calendar': calendar, '/games': [game]}


class DataTests(unittest.TestCase):
    def setUp(self):
        self.parent = ROOT / '.codex-tmp' / 'cfb-data-review'
        created = not self.parent.exists()
        self.parent.mkdir(parents=True, exist_ok=True)
        if created: self.addCleanup(self.parent.rmdir)
        self.temp = tempfile.TemporaryDirectory(dir=self.parent)
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name)
        self.raw, self.calls = fixture(), []
        self.raw['/games-fcs'] = [dict(self.raw['/games'][0], id=201, homeId=8, awayId=9,
            homeTeam='FCS A', awayTeam='FCS B', homeClassification='fcs', awayClassification='fcs')]

    def request(self, path, parameters, key):
        self.calls.append((path, parameters))
        self.assertEqual(key, 'test-only-key')
        self.assertEqual(parameters['year'], 2026)
        return copy.deepcopy(self.raw.get('/games-fcs', []) if parameters.get('classification') == 'fcs' else self.raw[path])

    def run_sync(self, **kwargs):
        return sync(2026, 'test-only-key', destination=self.destination,
                    fetcher=self.request, now=NOW, **kwargs)

    def normalized(self):
        return normalize(2026, self.raw['/teams/fbs'], self.raw['/calendar'], self.raw['/games'], NOW)

    def saved(self):
        return {p.name: p.read_bytes() for p in (self.destination / '2026').glob('*.json')}

    def test_first_sync_then_two_request_no_op(self):
        result = self.run_sync()
        self.assertEqual(result['requests'], 4)
        self.assertEqual(result['eligible_completed_games'], 2)
        self.assertEqual(result['teams_without_fbs_games'], [3])
        before = self.saved()
        result = self.run_sync()
        self.assertEqual(result['requests'], 2)
        self.assertFalse(result['changed_files'])
        self.assertFalse(result['model_inputs_changed'])
        self.assertEqual(self.saved(), before)
        self.assertEqual(self.calls[-1], ('/games', {'year': 2026, 'seasonType': 'both', 'classification': 'fcs'}))

    def test_joint_feed_counts_shared_game_once_and_rejects_disagreement(self):
        shared = dict(self.raw['/games'][0], id=102, awayId=8, awayTeam='FCS A', awayClassification='fcs')
        self.raw['/games'].append(shared)
        self.raw['/games-fcs'].append(copy.deepcopy(shared))
        result = self.run_sync()
        self.assertEqual(result['eligible_completed_games'], 3)
        self.assertEqual(result['fbs_teams'], 3)
        self.assertEqual(result['fcs_teams'], 2)
        before = self.saved()
        self.raw['/games-fcs'][-1]['homePoints'] += 1
        with self.assertRaisesRegex(ValueError, 'disagree'):
            self.run_sync()
        self.assertEqual(before, self.saved())

    def test_correction_changes_inputs_without_duplicate_games(self):
        before = self.run_sync()
        self.raw['/games'][0]['homePoints'] = 30
        after = self.run_sync()
        self.assertTrue(after['model_inputs_changed'])
        self.assertNotEqual(before['model_input_sha256'], after['model_input_sha256'])
        self.assertEqual(after['eligible_completed_games'], 2)
        self.assertEqual(after['requests'], 2)

    def test_failure_preserves_every_saved_file(self):
        self.run_sync()
        before = self.saved()
        self.raw['/games'][0]['homePoints'] = None
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(before, self.saved())

    def test_removed_final_is_not_silently_deleted(self):
        self.run_sync()
        before = self.saved()
        self.raw['/games'][0]['id'] = 999
        with self.assertRaisesRegex(ValueError, 'disappeared'):
            self.run_sync()
        self.assertEqual(before, self.saved())

    def test_first_failure_does_not_create_season_files(self):
        self.raw['/games'] = []
        self.raw['/games-fcs'] = []
        with self.assertRaises(ValueError):
            self.run_sync()
        self.assertFalse((self.destination / '2026').exists())

    def test_neutral_fbs_game_and_zero_game_team_preserved(self):
        result = self.normalized()
        self.assertTrue(result['games'][0]['neutral_site'])
        self.assertTrue(result['games'][0]['eligible'])
        self.assertEqual(len(result['teams']), 3)
        self.assertFalse(result['summary']['publication_ready'])

    def test_fcs_and_postseason_retained_but_excluded(self):
        fcs = dict(self.raw['/games'][0], id=102, awayId=999, awayClassification='fcs')
        bowl = dict(self.raw['/games'][0], id=103, seasonType='postseason')
        self.raw['/games'] += [fcs, bowl]
        result = self.normalized()
        self.assertEqual(result['summary']['eligible_completed_games'], 1)
        reasons = {g['id']: g['exclusions'] for g in result['games']}
        self.assertIn('not_fbs_vs_fbs', reasons[102])
        self.assertIn('postseason_not_in_scope', reasons[103])

    def test_future_or_partial_scores_never_enter_model_hash(self):
        future = dict(self.raw['/games'][0], id=102, week=14, completed=False,
                      startDate='2026-11-28T20:00:00Z', homePoints=10, awayPoints=7)
        before = self.normalized()['model_input_sha256']
        self.raw['/games'].append(future)
        result = self.normalized()
        self.assertEqual(before, result['model_input_sha256'])
        self.assertIsNone(result['games'][1]['home_points'])
        self.assertIn('future_game', result['games'][1]['exclusions'])
        future['completed'] = True
        with self.assertRaisesRegex(ValueError, 'future game'):
            self.normalized()

    def test_bad_ids_season_classification_and_ties_rejected(self):
        cases = ({'season': 2025}, {'id': True}, {'homeId': 2},
                 {'awayClassification': 'fcs'}, {'homePoints': 21}, {'neutralSite': None})
        for change in cases:
            with self.subTest(change=change):
                self.raw = fixture()
                self.raw['/games'][0].update(change)
                with self.assertRaises(ValueError):
                    self.normalized()

    def test_duplicate_game_and_missing_calendar_week_rejected(self):
        self.raw['/games'] *= 2
        with self.assertRaisesRegex(ValueError, 'Duplicate game'):
            self.normalized()
        self.raw = fixture()
        self.raw['/games'][0]['week'] = 5
        with self.assertRaisesRegex(ValueError, 'calendar'):
            self.normalized()

    def test_metadata_refresh_is_explicit_and_integrity_checked(self):
        self.run_sync()
        self.assertEqual(self.run_sync(refresh_metadata=True)['requests'], 4)
        path = self.destination / '2026' / 'teams.json'
        value = json.loads(path.read_text())
        value['payload'][0]['id'] = 999
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.run_sync()

    def test_missing_key_rejected_before_network(self):
        with self.assertRaises(ValueError):
            sync(2026, '', destination=self.destination, fetcher=self.request, now=NOW)
        self.assertFalse(self.calls)

    def test_http_errors_do_not_print_response_or_key(self):
        error = urllib.error.HTTPError('https://api.collegefootballdata.com/games', 401, 'no', {},
                                       io.BytesIO(b'private-value-do-not-log'))
        with patch('sync_data.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(ValueError) as caught:
                fetch('/games', {'year': 2026}, 'private-value-do-not-log')
        self.assertIn('401', str(caught.exception))
        self.assertNotIn('private-value', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
