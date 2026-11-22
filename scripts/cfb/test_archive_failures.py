"""Offline archive recovery checks with simulated diagnosed failures only."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import historical_rankings as history
import update_rankings as pipeline
import weekly_publication as weekly
from sampling_retry import ExactLOOSamplingError
from full_fit_retry import FullFitSamplingError
from sync_data import ROOT


class ArchiveFailureTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp/cfb-loo-review'))
        if not base.exists():
            base.mkdir(parents=True)
            self.addCleanup(base.rmdir)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.plan, self.output = root / 'plan.json', root / 'outputs'
        self.index = {'latest': 'last-good', 'snapshots': [{'id': 'last-good'}]}
        self.saved, self.revision = set(), 'original'
        data = root / 'data'
        for season in (2025, 2026):
            folder = data / str(season)
            folder.mkdir(parents=True)
            calendar = [{'week': w, 'seasonType': 'regular', 'endDate': f'{season}-09-{w*7:02d}T12:00:00Z'} for w in (1, 2)]
            for name in ('teams', 'games', 'games-fcs', 'calendar'):
                (folder / f'{name}.json').write_text(json.dumps({
                    'payload': calendar if name == 'calendar' else [], 'retrieved_at': '2026-11-22T12:00:00Z'}))
        def write(value, *args):
            self.index = copy.deepcopy(value)
        patches = [patch.object(history, 'DATA', data), patch.object(history, 'FIRST_SEASON', 2025),
            patch.object(history, 'history_available', return_value=True),
            patch.object(history, 'load_inputs', side_effect=lambda season, through_week: {'season': season, 'week': through_week}),
            patch.object(pipeline, 'current_season', return_value=2026), patch.object(pipeline, 'TASK', root),
            patch.object(pipeline, 'PLAN', self.plan), patch.object(pipeline, 'PUBLIC', root / 'public'),
            patch.object(pipeline, 'read_index', side_effect=lambda *a: copy.deepcopy(self.index)),
            patch.object(pipeline, 'write_index', side_effect=write),
            patch.object(pipeline, 'request_key', side_effect=lambda i: f"{i['season']}-{i['week']}-{self.revision}"),
            patch.object(pipeline, 'matching_snapshot', side_effect=lambda index, key, *a, **kw: {'id': key} if key in self.saved else None),
            patch.dict(os.environ, {'GITHUB_OUTPUT': str(self.output)})]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.error = ExactLOOSamplingError(401862705, [
            {'settings': {'warmup': 1000, 'draws': 1000}, 'diagnostics': {'sampling_checks_passed': False, 'min_bulk_ess': 200}},
            {'settings': {'warmup': 2000, 'draws': 2000}, 'diagnostics': {'sampling_checks_passed': False, 'min_bulk_ess': 350}}])

    def prepare(self, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            history.prepare_history(**kw)
        return json.loads(self.plan.read_text())

    def fail_latest(self):
        plan = self.prepare()
        history.record_sampling_failure(plan, self.error)
        return plan

    def test_failed_week_does_not_block_earlier_weeks_or_years(self):
        failed = self.fail_latest()
        self.assertEqual((failed['season'], failed['through_week']), (2026, 2))
        plan = self.prepare()
        self.assertEqual((plan['season'], plan['through_week']), (2026, 1))
        self.saved.add(plan['key'])
        plan = self.prepare()
        self.assertEqual((plan['season'], plan['through_week']), (2025, 2))
        self.assertEqual(self.index['latest'], 'last-good')
        self.assertEqual(self.index['snapshots'], [{'id': 'last-good'}])
        week2 = self.index['archive'][0]['weeks'][1]
        self.assertEqual(week2['status'], 'needs_attention')
        self.assertIsNone(week2['snapshot'])

    def test_exhausted_queue_stops_instead_of_looping_over_failed_week(self):
        self.fail_latest()
        self.saved.update(f'{season}-{week}-original' for season, week in ((2026, 1), (2025, 1), (2025, 2)))
        plan = self.prepare()
        self.assertTrue(plan['history_done'])
        self.assertFalse(plan['needs_fit'])
        self.assertEqual(plan['failed_weeks'], 1)
        self.assertEqual(self.index['backfill']['status'], 'needs_attention')
        self.assertTrue(self.output.read_text().endswith('continue_history=false\n'))

    def test_explicit_retry_or_changed_inputs_make_failed_week_eligible(self):
        original = self.fail_latest()
        self.assertEqual(self.prepare(retry_failed=True)['key'], original['key'])
        self.assertEqual(self.index['fit_failures'], [])
        self.fail_latest()
        self.revision = 'corrected'
        plan = self.prepare()
        self.assertEqual(plan['through_week'], 2)
        self.assertNotEqual(plan['key'], original['key'])
        self.assertEqual(self.index['fit_failures'], [])

    def test_success_clears_failure_and_unrelated_errors_cannot_skip_weeks(self):
        plan = self.fail_latest()
        self.saved.add(plan['key'])
        self.prepare()
        self.assertEqual(self.index['fit_failures'], [])
        with self.assertRaises(TypeError):
            history.record_sampling_failure(plan, ValueError('bad input'))

    def test_failed_job_records_diagnostics_and_requests_safe_continuation(self):
        self.prepare()
        with patch.object(pipeline, 'complete', side_effect=self.error), \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'complete']):
            with self.assertRaises(ExactLOOSamplingError): weekly.main()
        self.assertIn('sampling_failed=true\ncontinue_history=true\n', self.output.read_text())
        self.assertEqual(self.index['fit_failures'][0]['details']['game_id'], 401862705)
        with patch.object(pipeline, 'record_failure') as generic, \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'failed']):
            weekly.main()
        generic.assert_not_called()
        self.assertEqual(self.index['backfill']['status'], 'pending')

    def test_current_failure_preserves_rankings_and_does_not_dispatch_archive(self):
        plan = self.prepare(); plan['mode'] = 'current'
        self.plan.write_text(json.dumps(plan)); self.output.write_text('')
        with patch.object(pipeline, 'complete', side_effect=self.error), \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'complete']):
            with self.assertRaises(ExactLOOSamplingError): weekly.main()
        self.assertEqual(self.output.read_text(), 'sampling_failed=true\n')
        self.assertEqual(self.index['latest'], 'last-good')
        self.assertIn('401862705', self.index['last_attempt']['reason'])
        self.assertEqual(self.index['fit_failures'], [])

    def test_main_fit_failure_records_attempts_and_advances_historical_queue(self):
        self.error = FullFitSamplingError({'season': 2026, 'week': 2}, self.error.details['attempts'])
        self.prepare()
        with patch.object(pipeline, 'complete', side_effect=self.error), \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'complete']):
            with self.assertRaises(FullFitSamplingError): weekly.main()
        self.assertEqual(self.index['fit_failures'][0]['details']['phase'], 'full_fit')
        self.assertEqual(len(self.index['fit_failures'][0]['details']['attempts']), 2)
        self.assertIn('sampling_failed=true\ncontinue_history=true\n', self.output.read_text())
        self.assertEqual(self.prepare()['through_week'], 1)
        self.assertEqual(self.index['latest'], 'last-good')

    def test_current_main_fit_failure_keeps_details_without_publishing_or_dispatch(self):
        self.error = FullFitSamplingError({'season': 2026, 'week': 2}, self.error.details['attempts'])
        plan = self.prepare(); plan['mode'] = 'current'
        self.plan.write_text(json.dumps(plan)); self.output.write_text('')
        with patch.object(pipeline, 'complete', side_effect=self.error), \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'complete']):
            with self.assertRaises(FullFitSamplingError): weekly.main()
        self.assertEqual(self.output.read_text(), 'sampling_failed=true\n')
        self.assertEqual(self.index['latest'], 'last-good')
        self.assertEqual(self.index['last_attempt']['details'], self.error.details)
        with patch.object(pipeline, 'record_failure') as generic, \
             patch.object(weekly, 'refresh_index'), patch('sys.argv', ['weekly_publication.py', 'failed']):
            weekly.main()
        generic.assert_not_called()


if __name__ == '__main__':
    unittest.main()
