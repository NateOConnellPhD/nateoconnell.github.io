"""Targeted offline tests of the live publisher's failure and reuse boundaries."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import update_rankings as live
from sync_data import ROOT, UTC


def fixture(season=2026):
    at = f'{season}-11-20T12:00:00+00:00'
    inputs = {'season': season, 'fit_input_sha256': 'fixture', 'teams': [{'id': 1}, {'id': 2}],
              'games': [{'id': 1, 'week': 12, 'start_date': at, 'home_id': 1, 'away_id': 2,
                         'home_points': 7, 'away_points': 0}], 'source': {'games': {'retrieved_at': at}}}
    rows = []
    for i, name in enumerate(('A', 'B'), 1):
        rows.append({'id': i, 'name': name, 'conference': 'ACC', 'rank': i, 'raw_merit_rank': i,
                     'status': 'ranked', 'wins_fbs': int(i == 1), 'losses_fbs': int(i == 2),
                     'merit_mean': 2-i, 'merit_lo90': 1-i, 'merit_hi90': 3-i,
                     'raw_rank_mean': i, 'raw_rank_lo90': i, 'raw_rank_hi90': i,
                     'sos_mean': .5, 'sos_lo90': .4, 'sos_hi90': .6,
                     'p_raw_merit_top8': 1., 'p_raw_merit_top10': 1., 'p_raw_merit_top25': 1.})
    result = {'season': season, 'games': 1, 'teams': rows, 'order': [1, 2], 'data_cutoff': at,
              'identity': {'inputs': {'fit_input_sha256': 'fixture'}},
              'sampling_diagnostics': {'sampling_checks_passed': True, 'max_rank_normalized_rhat': 1.,
                                       'min_bulk_ess': 1000, 'min_tail_ess': 1000, 'divergences': 0,
                                       'tree_depth_limit_hits': 0, 'bfmi_by_chain': [1.]*4},
              'loo_diagnostics': {'unreliable_games': 0, 'psis_unreliable_games': 0,
                                  'exact_refits': 0, 'max_transport_mean_error': .0001}}
    return result, inputs


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / '.codex-tmp' / 'cfb-live'
        cls.created_base = not cls.base.exists()
        cls.base.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.created_base:
            cls.base.rmdir()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.public = Path(self.temp.name) / 'public'
        self.now = dt.datetime(2026, 11, 20, 13, tzinfo=UTC)
        self.result, self.inputs = fixture()

    def publish(self, key='one'):
        return live.publish(self.result, self.inputs, key, self.now, self.public)

    def test_bad_candidate_cannot_change_last_good_files(self):
        self.publish()
        original = {p: p.read_bytes() for p in self.public.rglob('*') if p.is_file()}
        for field, value in (('divergences', 1), ('min_tail_ess', 5), ('max_rank_normalized_rhat', 1.1)):
            bad = copy.deepcopy(self.result)
            bad['sampling_diagnostics'][field] = value
            with self.assertRaises(ValueError):
                live.publish(bad, self.inputs, 'bad', self.now, self.public)
            self.assertEqual(original, {p:p.read_bytes() for p in self.public.rglob('*') if p.is_file()})

    def test_uncertain_loo_cannot_publish(self):
        self.result['loo_diagnostics']['psis_unreliable_games'] = 1
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(self.public.exists())

    def test_records_probabilities_and_input_identity_are_checked(self):
        for mutation in ('record', 'probability', 'inputs'):
            bad = copy.deepcopy(self.result)
            if mutation == 'record':
                bad['teams'][0]['wins_fbs'] = 3
            elif mutation == 'probability':
                bad['teams'][0]['p_raw_merit_top8'] = .5
            else:
                bad['identity']['inputs']['fit_input_sha256'] = 'different'
            with self.assertRaises(ValueError):
                live.publish(bad, self.inputs, 'bad', self.now, self.public)

    def test_revisions_keep_original_snapshot_and_csv(self):
        first = self.publish()
        original = (self.public / first['json']).read_bytes()
        self.now += dt.timedelta(hours=1)
        second = self.publish('revised-inputs')
        self.assertNotEqual(first['json'], second['json'])
        self.assertEqual(original, (self.public / first['json']).read_bytes())
        index = live.read_index(self.public)
        self.assertEqual(len(index['snapshots']), 2)
        self.assertEqual(index['latest'], second['id'])
        self.assertTrue((self.public / first['csv']).exists())

    def test_backfill_does_not_replace_current_season(self):
        current = self.publish()
        old, inputs = fixture(2024)
        live.publish(old, inputs, 'old', self.now + dt.timedelta(hours=1), self.public)
        self.assertEqual(live.read_index(self.public)['latest'], current['id'])

    def test_unchanged_update_skips_numerical_runner_even_without_cache(self):
        first = self.publish()
        plan = Path(self.temp.name) / 'plan.json'
        plan.write_text(json.dumps({'season': 2026, 'key': 'one'}))
        runner = types.SimpleNamespace(run=lambda *a, **kw: self.fail('Unnecessary model fit'))
        with patch.object(live, 'PLAN', plan), patch.object(live, 'load_inputs', return_value=self.inputs), \
             patch.object(live, 'request_key', return_value='one'), patch.dict('sys.modules', {'fit_saved_season': runner}):
            self.assertEqual(live.complete(self.public)['id'], first['id'])
        self.assertEqual(live.read_index(self.public)['last_attempt']['status'], 'unchanged')

    def test_tampered_snapshot_is_not_reused(self):
        row = self.publish()
        path = self.public / row['json']
        changed = json.loads(path.read_text())
        changed['teams'][0]['rank'] = 2
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            live.matching_snapshot(live.read_index(self.public), 'one', self.public)

    def test_restored_older_inputs_cannot_leave_the_wrong_latest_result(self):
        self.publish('original')
        self.now += dt.timedelta(hours=1)
        self.publish('changed')
        index = live.read_index(self.public)
        self.assertIsNone(live.matching_snapshot(index, 'original', self.public))
        self.assertIsNotNone(live.matching_snapshot(index, 'changed', self.public))

    def test_failure_status_preserves_existing_current_result(self):
        row = self.publish()
        content = (self.public / row['json']).read_bytes()
        live.record_failure(2026, self.public)
        index = live.read_index(self.public)
        self.assertEqual(index['latest'], row['id'])
        self.assertEqual(index['last_attempt']['status'], 'failed')
        self.assertEqual(content, (self.public / row['json']).read_bytes())

    def test_season_rollover_keeps_last_season_until_august(self):
        for month, expected in ((1, 2026), (7, 2026), (8, 2027), (11, 2027)):
            self.assertEqual(live.current_season(dt.datetime(2027, month, 1, tzinfo=UTC)), expected)


if __name__ == '__main__':
    unittest.main()
