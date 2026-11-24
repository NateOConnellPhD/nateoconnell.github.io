"""Lookback provenance and result joins; standard library, no network or fitting."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import export
import lookback as lb

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / '.codex-tmp/cfb-lookback-review'


def raw_game():
    return {'id': 1, 'season': 2026, 'week': 12, 'seasonType': 'regular',
            'startDate': '2026-11-21T18:00:00Z', 'homeId': 10, 'awayId': 20,
            'homeTeam': 'Home', 'awayTeam': 'Away', 'neutralSite': False,
            'completed': True, 'homePoints': 28, 'awayPoints': 21}


class LookbackTests(unittest.TestCase):
    def test_timing_requires_real_save_time_and_no_later_inputs(self):
        meta = {'observed_at': '2026-11-20T12:00:00Z', 'through_date': '2026-11-15T12:00:00Z'}
        kickoff = '2026-11-21T18:00:00Z'
        self.assertEqual(lb.timing(meta, kickoff), 'unverified')
        meta['saved_at'] = '2026-11-21T16:00:00Z'
        self.assertEqual(lb.timing(meta, kickoff), 'pregame')
        meta['historical_reconstruction'] = True
        self.assertEqual(lb.timing(meta, kickoff), 'reconstruction')
        meta.pop('historical_reconstruction')
        meta['input_observations'] = {'talent': {'observed_at': '2026-11-20T16:00:00Z'},
                                      'portal': {'observed_at': None}}
        self.assertEqual(lb.timing(meta, kickoff), 'pregame')
        meta['input_observations']['talent']['observed_at'] = '2026-11-22T16:00:00Z'
        self.assertEqual(lb.timing(meta, kickoff), 'unverified')
        meta['saved_at'] = kickoff
        self.assertEqual(lb.timing(meta, kickoff), 'after_kickoff')

    def test_only_verified_played_finals_have_scores(self):
        game = raw_game(); checked = '2026-11-23T00:00:00Z'
        self.assertEqual(lb.game_row(game, checked, {})['result'], {'home': 28, 'away': 21})
        for changes in ({'completed': False}, {'homePoints': None}, {'homePoints': 0, 'awayPoints': 0},
                        {'startDate': '2026-12-01T00:00:00Z'}, {'homePoints': 1.5}):
            self.assertIsNone(lb.game_row({**game, **changes}, checked, {})['result'])
        cancelled = {**game, 'homePoints': 0, 'awayPoints': 0, 'status': 'cancelled'}
        self.assertEqual(lb.game_row(cancelled, checked, {})['status'], 'cancelled')
        self.assertIsNone(lb.game_row(cancelled, checked, {})['result'])

    def test_actuals_update_without_mutating_or_recomputing_predictions(self):
        ident = '0' * 16; game = raw_game()
        forecast = {'id': 1, 'home': '10', 'away': '20', 'date': game['startDate'],
                    'home_margin': 4.25, 'p_home': .61, 'margin_lo80': -8., 'margin_hi80': 17.}
        meta = {'season': 2026, 'saved_at': '2026-11-21T16:00:00Z',
                'observed_at': '2026-11-20T00:00:00Z', 'through_date': '2026-11-15T12:00:00Z'}
        snapshot = {'meta': meta, 'games': [forecast]}
        index = {'snapshots': [{'season': 2026, 'id': ident, 'file': f'forecast-{ident}.json'}]}
        def read(path): return copy.deepcopy(index if path.name == 'index.json' else snapshot)
        with patch.object(lb, 'read', side_effect=read), patch.object(lb, 'saved_games', return_value=({1: game}, '2026-11-23T00:00:00Z')):
            first = lb.build(evidence={})[2026]
            game['homePoints'] = 31
            second = lb.build(evidence={})[2026]
            self.assertEqual(first['games'][0]['predictions'], second['games'][0]['predictions'])
            self.assertNotEqual(first['games'][0]['result'], second['games'][0]['result'])
            self.assertEqual(second['games'][0]['predictions'][0]['home_margin'], 4.25)
            # A schedule correction cannot legitimize a prediction created after
            # the kickoff recorded in the original snapshot.
            meta['saved_at'] = '2026-11-22T00:00:00Z'; game['startDate'] = '2026-11-24T00:00:00Z'
            self.assertEqual(lb.build(evidence={})[2026]['games'][0]['predictions'][0]['timing'], 'after_kickoff')
            forecast['home'] = '99'
            with self.assertRaisesRegex(ValueError, 'mismatched teams'): lb.build(evidence={})

    def test_saved_history_reconciles_without_market_fields_or_invented_uncertainty(self):
        reports = lb.build()
        evidence = lb.read(ROOT / '_cfb_data/forecast_inputs/evaluation.json')
        for rows in evidence.values():
            for row in rows:
                game = next(g for g in reports[row['season']]['games'] if g['id'] == row['game_id'])
                p = next(p for p in game['predictions'] if p['edition'].startswith('earlier-'))
                self.assertEqual(p['home_margin'], row['model'])
                self.assertEqual(game['result']['home'] - game['result']['away'], row['actual'])
                self.assertEqual(set(p), {'edition', 'timing', 'home_margin'})
        for report in reports.values():
            for game in report['games']:
                for p in game['predictions']:
                    self.assertNotIn('opener', p)
                    self.assertNotIn('close', p)
                    self.assertNotIn('home_line', p)
                    if p['timing'] == 'pregame':
                        self.assertLess(lb.instant(report['editions'][p['edition']]['saved_at']), lb.instant(game['date']))

    def test_export_records_real_creation_time_including_retrospective_fits(self):
        TASK.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TASK) as directory:
            meta = {'season': 2026, 'week': 1, 'input_key': 'test', 'through_date': '2026-08-20T00:00:00Z',
                    'observed_at': '2026-08-21T00:00:00Z', 'historical_reconstruction': True,
                    'saved_at': '2026-08-21T00:00:00Z'}
            before = dt.datetime.now(dt.timezone.utc)
            row = export.write({'meta': meta}, {}, directory)
            written = lb.read(Path(directory) / row['file'])
            self.assertGreaterEqual(lb.instant(written['meta']['saved_at']), before)
            self.assertEqual(meta['saved_at'], '2026-08-21T00:00:00Z')
            self.assertEqual(lb.timing(written['meta'], '2026-08-25T00:00:00Z'), 'reconstruction')

    def test_new_timestamp_accepts_the_real_production_metadata_shape(self):
        index = lb.read(lb.PUBLIC / 'index.json')
        row = next(r for r in index['snapshots'] if r['id'] == index['latest'])
        snapshot = lb.read(lb.PUBLIC / row['file'])
        meta = snapshot['meta']
        stamps = [meta['observed_at'], meta['through_date']]
        stamps += [v.get('observed_at') if isinstance(v, dict) else v for v in meta.get('input_observations', {}).values()]
        stamps += [meta.get('quarterbacks', {}).get(k) for k in ('observed_at', 'availability_observed_at')]
        saved = max(lb.instant(v) for v in stamps if v) + dt.timedelta(days=1)
        meta.update(saved_at=saved.isoformat(), historical_reconstruction=False)
        self.assertEqual(lb.timing(meta, (saved + dt.timedelta(days=1)).isoformat()), 'pregame')


if __name__ == '__main__': unittest.main()
