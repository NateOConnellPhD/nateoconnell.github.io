"""Focused offline ingestion checks; no dependency downloads or API requests."""
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from sync_data import ROOT, UTC, fetch, normalize, sync, reviewed_game_statuses

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


class ReviewedStatusTests(unittest.TestCase):
    def setUp(self):
        raw = fixture()
        self.teams = raw['/teams/fbs']
        self.calendar = [dict(season=2024, seasonType='regular', week=3,
                              startDate='2024-09-09T00:00:00Z', endDate='2024-09-16T00:00:00Z')]
        self.played = dict(raw['/games'][0], season=2024, week=3, startDate='2024-09-14T17:00:00Z')
        self.cancelled = dict(self.played, id=401637161, startDate='2024-09-14T20:00:00.000Z',
                              homeId=2502, awayId=233, homeTeam='Portland State', awayTeam='South Dakota',
                              homePoints=0, awayPoints=0, homeClassification='fcs', awayClassification='fcs',
                              status=None, notes=None)

    def normalized(self, row=None):
        return normalize(2024, self.teams, self.calendar, [self.played, row or self.cancelled], NOW, include_fcs=True)

    def test_verified_cancellation_is_excluded_with_sources_without_mutating_raw(self):
        before = copy.deepcopy(self.cancelled)
        result = self.normalized()
        game = next(g for g in result['games'] if g['id'] == 401637161)
        self.assertFalse(game['eligible'])
        self.assertEqual(game['exclusions'], ['cancelled'])
        self.assertEqual(game['home_points'], 0, 'Keep the provider value visible in the audit')
        self.assertTrue(game['completed'], 'Retain the provider flag rather than rewriting the source')
        self.assertEqual(game['non_played_evidence']['reviewed_correction'], reviewed_game_statuses()[401637161])
        self.assertEqual(result['summary']['eligible_completed_games'], 1)
        self.assertEqual(self.cancelled, before)

    def test_unrelated_ties_and_stale_corrections_still_stop(self):
        for change in ({'id': 401637162}, {'homePoints': 21, 'awayPoints': 21},
                       {'homePoints': 7}, {'homeId': 2503}, {'awayTeam': 'Different team'},
                       {'startDate': '2024-09-15T20:00:00Z'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.normalized(dict(self.cancelled, **change))

    def test_provider_cancellation_updates_and_equivalent_timestamp_remain_compatible(self):
        for change in ({'status': 'STATUS_CANCELED'}, {'completed': False},
                       {'homePoints': None, 'awayPoints': None}, {'startDate': '2024-09-14T20:00:00+00:00'}):
            with self.subTest(change=change):
                game = next(g for g in self.normalized(dict(self.cancelled, **change))['games'] if g['id'] == 401637161)
                self.assertFalse(game['eligible'])
                self.assertIn('cancelled', game['exclusions'])

    def test_historical_sync_then_saved_model_inputs_exclude_cancelled_game(self):
        from season_inputs import load_inputs
        parent = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-data-review'))
        created = not parent.exists()
        parent.mkdir(parents=True, exist_ok=True)
        if created: self.addCleanup(parent.rmdir)
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            root = Path(temporary)
            def request(endpoint, parameters, key):
                self.assertEqual(parameters['year'], 2024)
                return copy.deepcopy(self.teams if endpoint == '/teams/fbs' else self.calendar if endpoint == '/calendar'
                                     else [self.cancelled] if parameters['classification'] == 'fcs' else [self.played])
            result = sync(2024, 'fixture-key', destination=root, fetcher=request, now=NOW)
            self.assertEqual(result['requests'], 4)
            self.assertEqual(result['eligible_completed_games'], 1)
            source = root/'2024/games-fcs.json'
            before = source.read_bytes()
            self.assertEqual(json.loads(before)['payload'], [self.cancelled])
            fit = load_inputs(2024, through_week=3, root=root)
            self.assertEqual([g['id'] for g in fit['games']], [self.played['id']])
            self.assertEqual(fit['data']['margin'], [6])
            self.assertEqual(source.read_bytes(), before)
            # A legacy normalized file may have admitted this placeholder.
            path = root/'2024/normalized.json'
            old = json.loads(path.read_text())
            next(g for g in old['games'] if g['id'] == 401637161)['eligible'] = True
            path.write_text(json.dumps(old))
            self.assertEqual(sync(2024, 'fixture-key', destination=root, fetcher=request, now=NOW)['eligible_completed_games'], 1)


class DataTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-data-review'))
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

    def test_unclassified_opponents_are_audited_without_blocking_joint_sync(self):
        before = self.run_sync()
        fcs = self.raw['/games-fcs'][0]
        self.raw['/games-fcs'] += [
            dict(fcs, id=202, awayId=90, awayTeam='Unclassified visitor', awayClassification=None),
            dict(fcs, id=203, homeId=91, homeTeam='Unclassified host', homeClassification=None),
            dict(fcs, id=204, awayId=92, awayTeam='Division II visitor', awayClassification='ii'),
        ]
        after = self.run_sync()
        self.assertEqual(after['requests'], 2)
        self.assertEqual(after['eligible_completed_games'], 2)
        self.assertEqual(after['fcs_teams'], 2)
        self.assertEqual(after['model_input_sha256'], before['model_input_sha256'])
        self.assertEqual(after['exclusion_counts'], {'unclassified_team': 2, 'outside_division_i': 1})
        saved = json.loads((self.destination / '2026' / 'normalized.json').read_text())
        games = {g['id']: g for g in saved['games']}
        for ident, side in ((202, 'away'), (203, 'home')):
            self.assertFalse(games[ident]['eligible'])
            self.assertEqual(games[ident]['exclusions'], ['unclassified_team'])
            self.assertEqual(games[ident]['unclassified_sides'], [side])
        self.assertEqual({g['id'] for g in saved['games'] if g['eligible']}, {101, 201})
        raw = json.loads((self.destination / '2026' / 'games-fcs.json').read_text())['payload']
        self.assertIsNone(next(g for g in raw if g['id'] == 202)['awayClassification'])

    def test_missing_labels_reuse_established_membership_before_excluding_games(self):
        self.raw['/games'][0]['homeClassification'] = None
        # FCS membership comes from game 201, which is processed after game 102.
        self.raw['/games'].append(dict(self.raw['/games'][0], id=102,
            awayId=8, awayTeam='FCS A', awayClassification=None))
        result = self.run_sync()
        self.assertEqual(result['eligible_completed_games'], 3)
        self.assertEqual(result['exclusion_counts'], {})
        saved = json.loads((self.destination / '2026' / 'normalized.json').read_text())
        games = {g['id']: g for g in saved['games']}
        self.assertTrue(games[102]['eligible'])
        self.assertEqual(games[101]['inferred_classifications'], {'home': 'fbs'})
        self.assertEqual(games[102]['inferred_classifications'], {'home': 'fbs', 'away': 'fcs'})

    def test_unexpected_classification_reports_the_game_and_preserves_saved_data(self):
        self.run_sync()
        before = self.saved()
        self.raw['/games-fcs'][0]['awayClassification'] = 'unexpected'
        with self.assertRaisesRegex(ValueError, "Unknown game team classification: season 2026, game 201, away team 'FCS B' .*unexpected"):
            self.run_sync()
        self.assertEqual(before, self.saved())

    def test_conflicting_fcs_classification_still_blocks_sync(self):
        self.run_sync()
        before = self.saved()
        self.raw['/games-fcs'].append(dict(self.raw['/games-fcs'][0], id=202, awayClassification='ii'))
        with self.assertRaisesRegex(ValueError, "disagrees with season membership: season 2026, game 202, away team 'FCS B'"):
            self.run_sync()
        self.assertEqual(before, self.saved())

    def test_newly_missing_membership_cannot_silently_drop_saved_final_games(self):
        self.run_sync()
        before = self.saved()
        self.raw['/games-fcs'][0].update(homeClassification=None, awayClassification=None)
        with self.assertRaisesRegex(ValueError, 'Previously eligible final games disappeared'):
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

    def test_unexplained_zero_and_nonzero_ties_identify_game_and_preserve_saved_data(self):
        self.run_sync()
        before = self.saved()
        for score in (0, 21):
            self.raw['/games-fcs'][0].update(homePoints=score, awayPoints=score)
            with self.assertRaisesRegex(ValueError, f"season 2026, week 1, game 201, 'FCS B' {score} at 'FCS A' {score}"):
                self.run_sync()
            self.assertEqual(before, self.saved())

    def test_explicit_non_games_are_retained_for_audit_and_excluded_from_fit(self):
        before = self.run_sync()
        for evidence in ({'notes': 'Canceled due to weather'}, {'status': 'STATUS_CANCELED'},
                         {'notes': 'Game cancelled'}, {'notes': 'No contest'}):
            with self.subTest(evidence=evidence):
                self.raw['/games-fcs'] = [self.raw['/games-fcs'][0],
                    dict(self.raw['/games-fcs'][0], id=202, homePoints=0, awayPoints=0, **evidence),
                    dict(self.raw['/games-fcs'][0], id=203, homePoints=None, awayPoints=None, **evidence)]
                after = self.run_sync()
                self.assertEqual(before['model_input_sha256'], after['model_input_sha256'])
                saved = json.loads((self.destination / '2026/normalized.json').read_text())
                excluded = [g for g in saved['games'] if g['id'] in (202, 203)]
                self.assertEqual(len(excluded), 2)
                self.assertTrue(all(not g['eligible'] and g['non_played_evidence'] == evidence for g in excluded))

    def test_notes_about_another_cancelled_game_do_not_exclude_a_result(self):
        self.raw['/games'][0]['notes'] = 'Rescheduled after a cancelled game last week'
        self.assertTrue(self.normalized()['games'][0]['eligible'])

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
