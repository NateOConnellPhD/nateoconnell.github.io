"""Targeted offline tests of the live publisher's failure and reuse boundaries."""
import copy
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from dataclasses import asdict
from unittest.mock import patch

import update_rankings as live
from ranking_policy import order_policy, prepare_policy
from policy_fixtures import probability
from sync_data import ROOT, UTC
from historical_home import CANONICAL as HOME
from model import strength_structure


def fixture(season=2026):
    at = f'{season}-11-20T12:00:00+00:00'
    inputs = {'season': season, 'fit_input_sha256': 'fixture', 'scored_game_indices': [0],
              'home_history': {'input_sha256': 'history-fixture'}, 'venue_corrections_sha256': 'venues-fixture',
              'teams': [{'id': i, 'name': name, 'conference': 'ACC', 'classification':'fbs'} for i, name in ((1, 'A'), (2, 'B'))],
              'games': [{'id': 1, 'week': 12, 'start_date': at, 'home_id': 1, 'away_id': 2,
                         'season': season, 'eligible': True, 'completed': True, 'season_type': 'regular',
                         'home_points': 7, 'away_points': 0}], 'source': {'games': {'retrieved_at': at}}}
    inputs['teams'].append(dict(id=99,name='FCS fixture',conference='Ivy',classification='fcs'))
    inputs['strength_structure'] = strength_structure(inputs['teams'])
    rows = []
    for i, name in enumerate(('A', 'B'), 1):
        rows.append({'id': i, 'name': name, 'conference': 'ACC', 'rank': i, 'raw_merit_rank': i,
                     'status': 'ranked', 'wins': int(i == 1), 'losses': int(i == 2),
                     'wins_fcs': 0, 'losses_fcs': 0, 'wins_fbs': int(i == 1), 'losses_fbs': int(i == 2),
                     'merit_mean': 2-i, 'merit_lo90': 1-i, 'merit_hi90': 3-i,
                     'raw_rank_mean': i, 'raw_rank_lo90': i, 'raw_rank_hi90': i,
                     'sos_mean': .5, 'sos_lo90': .4, 'sos_hi90': .6,
                     'p_raw_merit_top8': 1., 'p_raw_merit_top10': 1., 'p_raw_merit_top25': 1.})
    result = {'season': season, 'games': 1, 'teams': rows, 'order': [1, 2], 'data_cutoff': at,
              'identity': {'inputs': {'fit_input_sha256': 'fixture', 'home_history_sha256': 'history-fixture', 'strength_structure': inputs['strength_structure']}},
              'home_prior': {'years': list(range(season-3, season)), 'history_input_sha256': 'history-fixture',
                             'prior_sha256': 'a'*64, 'specification': asdict(HOME), 'diagnostics': {'converged': True}},
              'sampling_diagnostics': {'sampling_checks_passed': True, 'parameters_checked': ['mu_fcs','tau_division','tau_conf','theta_z','conference_z','conference_effect'], 'max_rank_normalized_rhat': 1.,
                                       'min_bulk_ess': 1000, 'min_tail_ess': 1000, 'divergences': 0,
                                       'tree_depth_limit_hits': 0, 'bfmi_by_chain': [1.]*4},
              'loo_diagnostics': {'unreliable_games': 0, 'psis_unreliable_games': 0,
                                  'exact_refits': 0, 'max_transport_mean_error': .0001}}
    result.update(order_policy(prepare_policy(inputs['teams'][:2], inputs['games'], [1., 0.], probability(2), season=season, opponents=inputs['teams'][2:])))
    return result, inputs


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-live'))
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

    def test_prior_methodology_is_pending_instead_of_a_usable_ranking(self):
        row = self.publish()
        path = self.public / 'index.json'
        index = json.loads(path.read_text())
        index.pop('methodology')
        index['snapshots'][0].pop('methodology')
        path.write_text(json.dumps(index))
        migrated = live.read_index(self.public)
        self.assertEqual(migrated['snapshots'], [])
        self.assertIsNone(migrated['latest'])
        self.assertIsNone(live.matching_snapshot(migrated, 'one', self.public))
        self.assertEqual(migrated['backfill']['status'], 'pending')
        self.assertEqual(migrated['archive'][0]['weeks'], [{'week': 12, 'snapshot': None}])
        self.assertTrue((self.public / row['json']).exists())

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

    def test_proxy_missing_or_changed_historical_home_prior_cannot_publish(self):
        for change in ({'years': [2022, 2023, 2024]}, {'history_input_sha256': 'other'},
                       {'specification': {}}, {'prior_sha256': ''}, {'diagnostics': {'converged': False}}):
            bad = copy.deepcopy(self.result)
            bad['home_prior'].update(change)
            with self.assertRaisesRegex(ValueError, 'three-season home prior'):
                live.publish(bad, self.inputs, 'bad-home', self.now, self.public)
        self.assertFalse(self.public.exists())

    def test_hierarchy_membership_and_latent_diagnostics_are_required(self):
        for mutation in ('membership', 'diagnostics', 'dynamic_trace'):
            bad = copy.deepcopy(self.result)
            if mutation == 'membership':
                bad['identity']['inputs']['strength_structure']['conference'][0] += 1
            elif mutation == 'diagnostics':
                bad['sampling_diagnostics']['parameters_checked'].remove('tau_conf')
            else:
                bad['dynamic_trace'].append({'iteration': 99})
            with self.assertRaises(ValueError):
                live.publish(bad, self.inputs, 'bad-hierarchy', self.now, self.public)
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

    def test_csv_has_lf_endings_and_preserves_empty_fields_and_quoting(self):
        self.result['teams'][0]['name'] = 'A, "Quoted"'
        self.inputs['teams'][0]['name'] = 'A, "Quoted"'
        for ident in (3, 4):
            idle = dict(self.result['teams'][0], id=ident, name=f'Idle {ident}',
                        rank=None, raw_merit_rank=None, status='no_eligible_games',
                        wins=0, losses=0, wins_fcs=0, losses_fcs=0, wins_fbs=0, losses_fbs=0, sos_mean=None,
                        p_raw_merit_top8=None, p_raw_merit_top10=None, p_raw_merit_top25=None)
            self.result['teams'].append(idle)
            self.inputs['teams'].append({'id': ident, 'name': idle['name'], 'conference': 'ACC', 'classification':'fbs'})
        self.result.update(order_policy(prepare_policy([t for t in self.inputs['teams'] if t['classification']=='fbs'], self.inputs['games'],
                           [r['merit_mean'] for r in self.result['teams']], probability(4), season=2026, opponents=[t for t in self.inputs['teams'] if t['classification']=='fcs'])))
        self.result['identity']['inputs']['strength_structure'] = strength_structure(self.inputs['teams'])
        row = self.publish()
        body = (self.public / row['csv']).read_bytes()
        self.assertNotIn(b'\r', body)
        self.assertTrue(body.endswith(b'\n'))
        self.assertFalse(any(line.endswith((b' ', b'\t')) for line in body.split(b'\n')))
        records = list(csv.DictReader(io.StringIO(body.decode('utf-8'), newline='')))
        self.assertEqual(len(records), 4)
        self.assertEqual(records[0]['name'], 'A, "Quoted"')
        for record in records[-2:]:
            self.assertEqual(record['rank'], '')
            self.assertEqual(record['sos_mean'], '')
            self.assertNotIn(None, record)  # No accidental extra CSV columns.

    def test_browser_policy_inputs_and_audit_must_reproduce_official_order(self):
        for field in ('order', 'audit', 'policy_inputs'):
            bad = copy.deepcopy(self.result)
            if field == 'order':
                bad['order'].reverse()
            elif field == 'audit':
                bad['audit'].append({'type': 'invented'})
            else:
                bad['policy_inputs']['games'][0]['home_points'] = 99
            with self.assertRaises(ValueError):
                live.publish(bad, self.inputs, 'bad-policy', self.now, self.public)

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
