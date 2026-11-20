"""Offline calendar and reuse checks; no inference, network, or output files."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

import weekly_publication as weekly
from sync_data import UTC, instant


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 23, tzinfo=UTC)
        self.calendar = [
            {'week': 11, 'seasonType': 'regular', 'endDate': '2026-11-16T07:59:00Z'},
            {'week': 12, 'seasonType': 'regular', 'endDate': '2026-11-23T07:59:00Z'}]
        self.observed = self.now
        def saved(path, *args):
            return {'payload': self.calendar} if path.name == 'calendar.json' else {
                'retrieved_at': self.observed.isoformat()}
        self.saved = patch.object(weekly, 'read_saved', side_effect=saved)
        self.load = patch.object(weekly, 'load_inputs', side_effect=lambda year, **kw: {'through_week': kw['through_week']})
        self.key = patch.object(weekly.pipeline, 'request_key', side_effect=lambda inputs: str(inputs['through_week']))
        self.index = patch.object(weekly.pipeline, 'read_index', return_value={'snapshots': []})
        self.match = patch.object(weekly.pipeline, 'matching_snapshot', return_value=None)
        for p in (self.saved, self.load, self.key, self.index, self.match):
            mock = p.start(); self.addCleanup(p.stop)
            if p is self.load: self.loader = mock
            if p is self.match: self.matcher = mock

    def test_friday_uses_week_11_and_reuses_its_completed_snapshot(self):
        self.matcher.return_value = {'id': 'saved-week-11'}
        plan = weekly.current_plan(2026, self.now)
        self.assertEqual(plan['through_week'], 11)
        self.assertFalse(plan['needs_fit'])
        self.loader.assert_called_once_with(2026, through_week=11, root=weekly.DATA)
        self.assertTrue(self.matcher.call_args.kwargs['historical'])

    def test_next_week_requires_both_closed_calendar_and_fresh_data(self):
        monday = instant('2026-11-23T13:17:00Z')
        self.assertEqual(weekly.current_plan(2026, monday)['through_week'], 11)
        self.observed = monday
        self.assertEqual(weekly.current_plan(2026, monday)['through_week'], 12)
        self.assertEqual(weekly.current_plan(2026, self.now)['through_week'], 11)

    def test_no_closed_week_does_not_request_a_fit(self):
        plan = weekly.current_plan(2026, instant('2026-11-15T23:00:00Z'))
        self.assertTrue(plan['no_completed_week'])
        self.assertFalse(plan['needs_fit'])
        self.loader.assert_not_called()

    def test_week_zero_is_supported_and_postseason_is_ignored(self):
        self.calendar = [{'week': 0, 'seasonType': 'regular', 'endDate': '2026-08-31T07:59:00Z'},
                         {'week': 1, 'seasonType': 'postseason', 'endDate': '2026-08-31T07:59:00Z'}]
        self.assertEqual(weekly.current_plan(2026, self.now)['through_week'], 0)

    def test_empty_fbs_week_preserves_previous_completed_week(self):
        self.observed = instant('2026-11-23T13:17:00Z')
        def inputs(year, through_week, **kw):
            if through_week == 12:
                raise ValueError('No eligible completed games at the selected cutoff')
            return {'through_week': through_week}
        self.loader.side_effect = inputs
        self.assertEqual(weekly.current_plan(2026, self.observed)['through_week'], 11)

    def test_partial_snapshot_never_becomes_a_completed_week(self):
        partial = {'id': 'partial-12', 'season': 2026, 'week': 12,
                   'data_cutoff': self.now.isoformat(), 'published_at': self.now.isoformat()}
        complete = {**partial, 'id': 'complete-11', 'week': 11, 'data_cutoff': '2026-11-16T07:59:00Z'}
        index = {'snapshots': [partial, complete], 'latest': partial['id']}
        originals = copy.deepcopy(index['snapshots'])
        weekly.mark_completed(index)
        self.assertEqual(index['latest'], 'complete-11')
        self.assertEqual([r['week_complete'] for r in index['snapshots']], [False, True])
        self.assertEqual([{k: v for k, v in r.items() if k != 'week_complete'}
                          for r in index['snapshots']], originals)
        full12 = {**partial, 'id': 'complete-12', 'data_cutoff': '2026-11-23T07:59:00Z'}
        index['snapshots'].insert(0, full12)
        weekly.mark_completed(index)
        self.assertEqual(index['latest'], 'complete-12')
        self.assertFalse(partial['week_complete'])


if __name__ == '__main__':
    unittest.main()
