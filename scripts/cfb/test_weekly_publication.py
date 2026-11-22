"""Offline calendar and reuse checks; no inference, network, or output files."""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

import weekly_publication as weekly
from sync_data import UTC, instant, digest


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 23, tzinfo=UTC)
        self.calendar = [
            {'season': 2026, 'week': 11, 'seasonType': 'regular', 'startDate': '2026-11-09T08:00:00Z', 'endDate': '2026-11-16T07:59:00Z'},
            {'season': 2026, 'week': 12, 'seasonType': 'regular', 'startDate': '2026-11-16T08:00:00Z', 'endDate': '2026-11-23T07:59:00Z'}]
        from test_sync_data import fixture
        raw = fixture()
        self.teams = raw['/teams/fbs']
        self.games = [dict(raw['/games'][0], id=week, week=week, startDate=f'2026-11-{day}T20:00:00Z')
                      for week, day in ((11, 14), (12, 21))]
        self.fcs_games = [dict(self.games[-1], id=201, homeId=8, awayId=9,
                              homeTeam='FCS A', awayTeam='FCS B', homeClassification='fcs', awayClassification='fcs')]
        self.observed = self.now
        def saved(path, *args):
            payload = {'calendar.json': self.calendar, 'teams.json': self.teams,
                       'games.json': self.games, 'games-fcs.json': self.fcs_games}[path.name]
            return {'payload': payload, 'payload_sha256': digest(payload), 'retrieved_at': self.observed.isoformat()}
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
        plan = weekly.current_plan(2026, instant('2026-11-15T12:59:00Z'))
        self.assertTrue(plan['no_completed_week'])
        self.assertFalse(plan['needs_fit'])
        self.loader.assert_not_called()

    def test_sunday_uses_finished_week_before_monday_calendar_boundary(self):
        self.observed = instant('2026-11-22T13:17:00Z')
        plan = weekly.current_plan(2026, self.observed)
        self.assertEqual(plan['through_week'], 12)
        self.assertEqual(plan['as_of'], self.observed.isoformat())
        self.assertEqual(plan['week_completion']['game_ids'], [12, 201])
        self.loader.assert_called_once_with(2026, through_week=12, root=weekly.DATA, as_of=plan['as_of'])
        row = dict(id='sunday-12', season=2026, week=12, data_cutoff=plan['as_of'],
                   published_at=plan['as_of'], week_completion=plan['week_completion'])
        self.assertEqual(weekly.mark_completed({'snapshots': [row]})['latest'], 'sunday-12')
        row['data_cutoff'] = self.now.isoformat()
        self.assertIsNone(weekly.mark_completed({'snapshots': [row]})['latest'])

    def test_sunday_waits_for_fresh_feeds_and_unfinished_fbs_or_fcs_games(self):
        sunday = instant('2026-11-22T13:17:00Z')
        self.assertEqual(weekly.current_plan(2026, sunday)['through_week'], 11)
        self.observed = sunday
        for game in (self.games[-1], self.fcs_games[-1]):
            game['completed'] = False
            self.assertEqual(weekly.current_plan(2026, sunday)['through_week'], 11)
            game['completed'] = True
        # Explicitly cancelled games do not hold up the whole weekend.
        self.fcs_games[-1].update(completed=False, notes='Cancelled')
        self.assertEqual(weekly.current_plan(2026, sunday)['through_week'], 12)

    def test_sunday_still_waits_for_games_scheduled_later_that_day(self):
        self.observed = instant('2026-11-22T13:17:00Z')
        self.games[-1].update(startDate='2026-11-22T20:00:00Z', completed=False)
        self.assertEqual(weekly.current_plan(2026, self.observed)['through_week'], 11)

    def test_partial_result_is_not_reused_as_a_finished_sunday(self):
        self.observed = instant('2026-11-22T13:17:00Z')
        self.matcher.return_value = {'id': 'partial-12', 'week_complete': False}
        self.assertTrue(weekly.current_plan(2026, self.observed)['needs_fit'])

    def test_no_sunday_promotion_on_saturday_or_before_eight_eastern(self):
        for at in ('2026-11-21T23:00:00Z', '2026-11-22T12:59:00Z'):
            self.observed = instant(at)
            self.assertEqual(weekly.current_plan(2026, self.observed)['through_week'], 11)
        self.assertEqual(weekly.sunday_open(instant('2026-09-07T06:59:00Z')), instant('2026-09-06T12:00:00Z'))

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
