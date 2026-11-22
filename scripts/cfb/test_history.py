"""Offline checks for temporal cutoffs, archive revisions and queue reuse."""
import datetime as dt
import json
import unittest
from unittest.mock import patch

from historical_rankings import closed_weeks
from test_publication import PublicationTests, references
import update_rankings as live
from sync_data import UTC


class HistoryTests(PublicationTests):
    # Reuse only its fixture lifecycle, not the full publication suite.
    def test_closed_weeks_include_zero_and_exclude_future_and_postseason(self):
        weeks = [{'week': w, 'seasonType': kind, 'endDate': date}
                 for w, kind, date in ((0, 'regular', '2026-08-30T12:00:00Z'),
                                       (1, 'regular', '2026-09-06T12:00:00Z'),
                                       (2, 'regular', '2026-09-13T12:00:00Z'),
                                       (1, 'postseason', '2026-08-30T12:00:00Z'))]
        self.assertEqual(closed_weeks(weeks, dt.datetime(2026, 9, 7, tzinfo=UTC)), [1, 0])

    def test_each_historical_week_can_be_reused_after_later_weeks_publish(self):
        self.inputs['through_week'] = 1
        self.inputs['games'][0]['week'] = 1
        one = self.publish('week-one')
        self.inputs['through_week'] = 2
        two = self.publish('week-two')
        self.assertNotEqual(one['id'], two['id'])
        index = live.read_index(self.public)
        self.assertEqual(live.matching_snapshot(index, 'week-one', self.public, historical=True)['id'], one['id'])
        series = json.loads((self.public / 'seasons/2026/history.json').read_text())
        self.assertEqual([r['week'] for r in series['weeks']], [1, 2])
        self.assertTrue(all(r['kind'] == 'reconstruction' for r in series['weeks']))

    def test_new_revision_supersedes_only_its_week_in_trajectory(self):
        self.inputs['through_week'] = 1
        first = self.publish('original')
        self.now += dt.timedelta(hours=1)
        revised = self.publish('corrected')
        series = json.loads((self.public / 'seasons/2026/history.json').read_text())
        self.assertEqual([r['id'] for r in series['weeks']], [revised['id']])
        self.assertTrue((self.public / first['json']).exists())
        self.assertIsNone(live.matching_snapshot(live.read_index(self.public), 'original', self.public, historical=True))

    def test_backfill_uses_cutoff_in_both_input_loading_and_fit(self):
        self.inputs['through_week'] = 4
        self.inputs['venue_corrections_sha256'] = 'fixture'
        key = live.request_key(self.inputs)
        from pathlib import Path
        import types
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text(json.dumps({'season': 2026, 'key': key, 'through_week': 4}))
        calls = []
        runner = types.SimpleNamespace(run=lambda season, **kw: calls.append((season, kw)) or references(self.result)[kw['reference_rank']])
        with patch.object(live, 'PLAN', plan), patch.object(live, 'load_inputs', return_value=self.inputs) as load, \
             patch.dict('sys.modules', {'fit_saved_season': runner}), patch('posterior_summary.attach'):
            live.complete(self.public)
        load.assert_called_once_with(2026, through_week=4)
        self.assertEqual(calls, [(2026, {'through_week': 4, 'exact_loo': True, 'reference_rank': rank}) for rank in (12, 2, 4, 24)])

    def test_sunday_cutoff_and_completion_evidence_survive_publication(self):
        from pathlib import Path
        import types
        at = '2026-11-22T13:17:00+00:00'
        self.inputs.update(through_week=12, cutoff=at)
        self.inputs['source'] = {name: {'payload_sha256': name, 'retrieved_at': at}
                                for name in ('teams', 'calendar', 'games', 'games-fcs')}
        self.result['data_cutoff'] = at
        proof = {'basis': 'all_scheduled_games_final', 'checked_at': at,
                 'calendar_end': '2026-11-23T07:59:00+00:00', 'game_ids': [1],
                 'source_sha256': {name: name for name in self.inputs['source']}}
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text(json.dumps({'season': 2026, 'key': live.request_key(self.inputs),
                                   'through_week': 12, 'as_of': at, 'week_completion': proof}))
        calls = []
        runner = types.SimpleNamespace(run=lambda season, **kw: calls.append((season, kw)) or references(self.result)[kw['reference_rank']])
        with patch.object(live, 'PLAN', plan), patch.object(live, 'load_inputs', return_value=self.inputs) as load, \
             patch.dict('sys.modules', {'fit_saved_season': runner}), patch('posterior_summary.attach'):
            row = live.complete(self.public)
            load.assert_called_once_with(2026, through_week=12, as_of=at)
            self.assertEqual(calls, [(2026, {'through_week': 12, 'exact_loo': True, 'as_of': at, 'reference_rank': rank}) for rank in (12, 2, 4, 24)])
            self.assertEqual(row['week_completion'], proof)
            self.assertEqual(json.loads((self.public / row['json']).read_text())['week_completion'], proof)
            # A changed pending-game feed must invalidate the completion proof,
            # even when the eligible final-game set and request key are unchanged.
            self.inputs['source']['games-fcs']['payload_sha256'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'completed-week evidence changed'):
                live.complete(self.public)
            self.assertEqual(len(calls), 4)


if __name__ == '__main__':
    names = [n for n in HistoryTests.__dict__ if n.startswith('test_')]
    outcome = unittest.TextTestRunner().run(unittest.TestSuite(HistoryTests(n) for n in names))
    raise SystemExit(not outcome.wasSuccessful())
