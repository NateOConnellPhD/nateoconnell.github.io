"""Offline v6 window, membership, provenance and cache checks. No model fits."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import home_history_inputs as history
from season_inputs import load_fit_inputs
from sync_data import ROOT, UTC, encoded, envelope
from test_sync_data import fixture
import test_season_inputs

NOW = dt.datetime(2026, 11, 21, tzinfo=UTC)


def historical_fixture(year):
    raw = json.loads(json.dumps(fixture()).replace('2026', str(year)))
    first = raw['/games'][0]
    raw['/games'] = [dict(first, id=year*1000+i, neutralSite=i == 0) for i in range(100)]
    # Neither postseason nor FBS/FCS results may anchor structural home effects.
    raw['/games'] += [dict(first, id=year*1000+101, seasonType='postseason'),
                     dict(first, id=year*1000+102, awayId=999, awayTeam='FCS', awayClassification='fcs')]
    return raw


class HomeHistoryInputTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-v6-review'))
        created = not self.base.exists()
        self.base.mkdir(parents=True, exist_ok=True)
        if created: self.addCleanup(self.base.rmdir)
        self.temporary = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.calls = []

    def fetch(self, path, params, key):
        self.calls.append((path, params))
        return copy.deepcopy(historical_fixture(params['year'])[path])

    def save(self, year, observed=NOW):
        raw = historical_fixture(year)
        folder = self.root / str(year)
        folder.mkdir(exist_ok=True)
        for name, (endpoint, params) in history.endpoints(year).items():
            (folder / (name+'.json')).write_bytes(encoded(envelope(year, endpoint, params, raw[endpoint], observed.isoformat())))

    def test_exact_previous_three_seasons_and_earliest_archive_window(self):
        self.assertEqual(history.years_for(2026), [2023, 2024, 2025])
        self.assertEqual(history.years_for(2002), [1999, 2000, 2001])
        for season in (2001, True, '2026'):
            with self.assertRaises(ValueError): history.years_for(season)

    def test_missing_history_is_fetched_once_then_reused_across_weeks(self):
        self.assertEqual(history.ensure_history(2026, 'fixture', root=self.root, fetcher=self.fetch, now=NOW), 6)
        loaded = history.load_history(2026, root=self.root)
        self.assertEqual(loaded['years'], [2023, 2024, 2025])
        self.assertEqual(len(loaded['games']), 300)
        self.assertTrue(history.history_available(2026, root=self.root))
        self.assertEqual(history.ensure_history(2026, 'fixture', root=self.root, fetcher=self.fetch, now=NOW), 0)
        self.assertEqual(loaded, history.load_history(2026, root=self.root))
        self.assertTrue(all(g['home_id'] != 999 and g['away_id'] != 999 for g in loaded['games']))
        self.assertEqual(sum(g['venue'] == 0 for g in loaded['games']), 3)
        self.assertEqual({p['year'] for _, p in self.calls}, {2023, 2024, 2025})

    def test_proxy_window_cannot_substitute_for_missing_prior_year(self):
        for year in (2022, 2023, 2024): self.save(year)
        self.assertFalse(history.history_available(2026, root=self.root))
        with self.assertRaisesRegex(ValueError, '2025'):
            history.load_history(2026, root=self.root)

    def test_2002_home_window_needs_no_pre_2002_weekly_calendars(self):
        history.ensure_history(2002, 'fixture', root=self.root, fetcher=self.fetch, now=NOW)
        self.assertEqual(history.load_history(2002, root=self.root)['years'], [1999, 2000, 2001])
        self.assertFalse(any(path == '/calendar' for path, _ in self.calls))

    def test_future_dates_and_current_season_cannot_enter_historical_window(self):
        self.save(2025)
        sources = history.read_sources(2025, self.root)
        bad = copy.deepcopy(sources)
        bad['games']['payload'][0]['startDate'] = '2026-09-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'outside season'):
            history.season_history(2025, 2026, bad, {'schema': 'reviewed-venues-v1', 'games': []})
        with self.assertRaisesRegex(ValueError, 'not complete before'):
            history.season_history(2025, 2025, sources, {'schema': 'reviewed-venues-v1', 'games': []})

    def test_stale_prior_season_scores_are_refreshed_once(self):
        for year in (2023, 2024): self.save(year)
        self.save(2025, dt.datetime(2025, 11, 20, tzinfo=UTC))
        self.assertFalse(history.history_available(2026, root=self.root))
        self.assertEqual(history.ensure_history(2026, 'fixture', root=self.root, fetcher=self.fetch, now=NOW), 1)
        self.assertEqual(self.calls, [('/games', {'year': 2025, 'seasonType': 'both', 'classification': 'fbs'})])
        self.assertTrue(history.history_available(2026, root=self.root))

    def test_failed_window_validation_writes_nothing(self):
        def sparse(path, params, key):
            value = self.fetch(path, params, key)
            return value[:1] if path == '/games' and params['year'] == 2025 else value
        with self.assertRaisesRegex(ValueError, 'only 1 confirmed'):
            history.ensure_history(2026, 'fixture', root=self.root, fetcher=sparse, now=NOW)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_score_corrections_change_identity_retrieval_time_does_not(self):
        for year in (2023, 2024, 2025): self.save(year)
        before = history.load_history(2026, root=self.root)['input_sha256']
        self.save(2025, NOW+dt.timedelta(days=1))
        self.assertEqual(before, history.load_history(2026, root=self.root)['input_sha256'])
        path = self.root / '2025/games.json'
        saved = json.loads(path.read_text())
        saved['payload'][0]['homePoints'] += 1
        path.write_bytes(encoded(envelope(2025, '/games', saved['parameters'], saved['payload'], NOW.isoformat())))
        self.assertNotEqual(before, history.load_history(2026, root=self.root)['input_sha256'])

    def test_neutral_correction_is_applied_before_historical_fit(self):
        for year in (2023, 2024, 2025): self.save(year)
        original = history.load_history(2026, root=self.root)
        correction = {'schema': 'reviewed-venues-v1', 'games': [{
            'season': 2025, 'game_id': 2025000, 'neutral_site': False,
            'expected': {'homeId': 1, 'awayId': 2, 'homePoints': 27, 'awayPoints': 21, 'venue': None},
            'reason': 'Synthetic venue correction', 'sources': ['fixture']}]}
        path = self.root / 'corrections.json'
        path.write_text(json.dumps(correction))
        corrected = history.load_history(2026, root=self.root, corrections_path=path)
        self.assertEqual(next(g for g in corrected['games'] if g['id'] == 2025000)['venue'], 1)
        self.assertNotEqual(original['input_sha256'], corrected['input_sha256'])

    def test_current_game_host_slots_use_school_identity_not_visiting_team(self):
        sources = test_season_inputs.JointInputTests().sources()
        with patch('season_inputs.read_saved', side_effect=lambda path, *args: sources[path.stem]), \
             patch.object(history, 'load_history', return_value={'years': [2023, 2024, 2025]}) as read:
            result = load_fit_inputs(2026, through_week=1)
        self.assertEqual(result['data']['host'], [1, 1, 0])
        self.assertEqual(result['data']['venue'], [0, 0, 0])
        self.assertEqual(read.call_args.args, (2026,))


if __name__ == '__main__':
    unittest.main()
