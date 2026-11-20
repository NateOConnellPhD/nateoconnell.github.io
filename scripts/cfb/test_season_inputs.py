"""Offline checks against the committed 2024 source data; no output files."""
import copy
import json
import unittest

from season_inputs import CORRECTIONS, DATA, instant, load_inputs, prepare


class InputTests(unittest.TestCase):
    def test_full_season_and_separate_correction_audit(self):
        before = {p.name: p.read_bytes() for p in (DATA / '2024').glob('*.json')}
        result = load_inputs(2024)
        self.assertEqual(len(result['teams']), 134)
        self.assertEqual(len(result['games']), 752)
        self.assertEqual(len(result['venue_corrections']), 16)
        self.assertTrue(all(g['changed'] for g in result['venue_corrections']))
        self.assertEqual(before, {p.name: p.read_bytes() for p in (DATA / '2024').glob('*.json')})

    def test_corrections_only_change_reviewed_venue_flags(self):
        result = load_inputs(2024)
        source = json.loads((DATA / '2024' / 'normalized.json').read_text())
        original = {g['id']: g for g in source['games'] if g['eligible']}
        corrected = {g['game_id'] for g in result['venue_corrections']}
        for game in result['games']:
            expected = dict(original[game['id']])
            if game['id'] in corrected:
                expected['neutral_site'] = False
            self.assertEqual(game, expected)
        self.assertNotEqual(result['fit_input_sha256'], source['model_input_sha256'])

    def test_week_filter_preserves_championships_and_later_army_navy(self):
        week15 = load_inputs(2024, through_week=15)
        week16 = load_inputs(2024, through_week=16)
        self.assertNotIn(401645383, [g['id'] for g in week15['games']])
        self.assertIn(401645383, [g['id'] for g in week16['games']])
        self.assertIn(401673464, [g['id'] for g in week15['games']])  # Big Ten championship
        self.assertTrue(all(g['season_type'] == 'regular' for g in week16['games']))

    def test_as_of_keeps_full_roster_without_future_results(self):
        result = load_inputs(2024, as_of='2024-08-24T23:59:59Z')
        self.assertEqual(len(result['teams']), 134)
        self.assertEqual([g['id'] for g in result['games']], [401635525])
        self.assertFalse(result['venue_corrections'])
        boundary = load_inputs(2024, as_of='2024-08-25T00:00:00Z')
        self.assertIn(401643696, [g['id'] for g in boundary['games']])

    def test_invalid_cutoffs_fail(self):
        for kwargs in ({'through_week': 99}, {'through_week': True},
                       {'as_of': '2099-01-01T00:00:00Z'}, {'as_of': '2024-01-01T00:00:00Z'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                load_inputs(2024, **kwargs)

    def test_stale_correction_cannot_silently_change_a_game(self):
        normalized = json.loads((DATA / '2024' / 'normalized.json').read_text())
        source = json.loads((DATA / '2024' / 'games.json').read_text())
        corrections = json.loads(CORRECTIONS.read_text())
        corrections['games'][0]['expected']['homeId'] = -1
        with self.assertRaisesRegex(ValueError, 'stale venue correction'):
            prepare(normalized, source['payload'], corrections,
                    cutoff=instant(source['retrieved_at']))

    def test_duplicate_correction_is_rejected(self):
        normalized = json.loads((DATA / '2024' / 'normalized.json').read_text())
        source = json.loads((DATA / '2024' / 'games.json').read_text())
        corrections = json.loads(CORRECTIONS.read_text())
        corrections['games'].append(copy.deepcopy(corrections['games'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate venue correction'):
            prepare(normalized, source['payload'], corrections,
                    cutoff=instant(source['retrieved_at']))


if __name__ == '__main__':
    unittest.main()
