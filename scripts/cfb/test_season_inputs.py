"""Offline joint-input boundary checks; no model fits or output files."""
import unittest
from unittest.mock import patch
from season_inputs import load_inputs as production_inputs
from test_sync_data import fixture, NOW


class JointInputTests(unittest.TestCase):
    def sources(self):
        raw = fixture()
        shared = dict(raw['/games'][0], id=102, awayId=8, awayTeam='FCS A', awayClassification='fcs')
        fcs = dict(shared, id=201, homeId=8, awayId=9, homeTeam='FCS A', awayTeam='FCS B', homeClassification='fcs')
        raw['/games'].append(shared)
        payloads = {'teams': raw['/teams/fbs'], 'calendar': raw['/calendar'],
                    'games': raw['/games'], 'games-fcs': [shared, fcs]}
        return {name: {'payload': value, 'retrieved_at': NOW.isoformat(), 'source': 'fixture',
                       'parameters': {}, 'payload_sha256': 'fixture'} for name, value in payloads.items()}

    def test_joint_fit_separates_fbs_reference_and_scored_games(self):
        sources = self.sources()
        with patch('season_inputs.read_saved', side_effect=lambda path, *args: sources[path.stem]):
            result = production_inputs(2026, through_week=1)
        self.assertEqual([t['id'] for t in result['teams']], [1, 2, 3, 8, 9])
        self.assertEqual(result['fbs_indices'], [0, 1, 2])
        self.assertEqual([g['id'] for g in result['games']], [101, 102, 201])
        self.assertEqual(result['scored_game_indices'], [0, 1])
        self.assertEqual(result['statistical_scope'], 'joint_fbs_fcs')
        self.assertEqual(result['cutoff'], '2026-09-01T00:00:00+00:00')

    def test_missing_or_empty_fcs_feed_never_falls_back_to_old_fbs_fit(self):
        for missing in (True, False):
            sources = self.sources()
            sources['games-fcs'] = None if missing else dict(sources['games-fcs'], payload=[])
            with patch('season_inputs.read_saved', side_effect=lambda path, *args: sources[path.stem]):
                with self.assertRaises(ValueError): production_inputs(2026)

    def test_joint_cutoff_uses_the_older_feed_observation(self):
        sources = self.sources()
        sources['games-fcs']['retrieved_at'] = '2026-08-31T00:00:00Z'
        with patch('season_inputs.read_saved', side_effect=lambda path, *args: sources[path.stem]):
            with self.assertRaisesRegex(ValueError, 'not ended'):
                production_inputs(2026, through_week=1)


if __name__ == '__main__':
    unittest.main()
