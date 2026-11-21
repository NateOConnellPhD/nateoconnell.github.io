"""Targeted NumPy bridge checks; run only in the approved model environment."""
import unittest
import numpy as np

from ranking_policy import rank_merit
from policy_fixtures import teams, games


class DrawTests(unittest.TestCase):
    def test_tied_draws_have_no_false_lock_or_arbitrary_probability(self):
        result = rank_merit(teams(9), games([(i, i % 9 + 1) for i in range(1, 10)]),
                            np.zeros((20, 9)), season=2024)
        self.assertEqual(result['confidence_lock_count'], 0)
        for row in result['teams']:
            self.assertAlmostEqual(row['p_raw_merit_top8'], 8 / 9)
            self.assertEqual(row['raw_rank_mean'], 5)

    def test_rank_uncertainty_is_raw_merit_not_official_policy(self):
        # A and B are both 1–1. A's direct win qualifies by proximity even
        # though B has greater merit in every draw. C and D have other records.
        result = rank_merit(teams(4), games([(1, 2), (3, 1), (2, 4)]),
                            np.tile([1., 2., -1., -2.], (20, 1)), season=2024)
        a = next(r for r in result['teams'] if r['id'] == 1)
        self.assertEqual(a['rank'], 1)
        self.assertEqual(a['raw_merit_rank'], 2)
        self.assertEqual(a['raw_rank_mean'], 2)
        self.assertTrue(any(r['type'] == 'head_to_head' and r['winner_id'] == 1 and
                            r['loser_id'] == 2 and r['status'] == 'accepted' for r in result['audit']))
        self.assertTrue(any(r['type'] == 'merit_protection' and r['winner_id'] == 2 and r['loser_id'] == 1 and
                            r['status'] == 'overridden_by_global_objective' for r in result['audit']))

    def test_undefeated_p4_team_has_no_automatic_promotion(self):
        roster = teams(2)
        roster[0]['conference'] = 'ACC'
        result = rank_merit(roster, games([(1, 2)] * 8), np.tile([1., 2.], (20, 1)), season=2024)
        a = next(r for r in result['teams'] if r['id'] == 1)
        self.assertEqual((a['wins_fbs'], a['losses']), (8, 0))
        self.assertEqual((a['rank'], a['raw_merit_rank'], a['raw_rank_mean']), (2, 2, 2))
        self.assertEqual(result['order'], [2, 1])
        self.assertTrue(all(r['type'] == 'merit_protection' and r['status'] == 'accepted'
                            for r in result['audit']))

    def test_no_game_teams_get_null_probabilities(self):
        result = rank_merit(teams(3), games([(1, 2)]), np.tile([1., -1., 0.], (20, 1)), season=2024)
        idle = next(r for r in result['teams'] if r['id'] == 3)
        self.assertIsNone(idle['rank'])
        self.assertIsNone(idle['p_raw_merit_top8'])
        self.assertEqual(idle['status'], 'no_eligible_games')

    def test_bad_draw_dimensions_or_nan_rejected(self):
        for draws in (np.zeros((4, 3)), np.zeros((1, 2)), np.full((4, 2), np.nan)):
            with self.subTest(shape=draws.shape), self.assertRaises(ValueError):
                rank_merit(teams(2), games([(1, 2)]), draws, season=2024)


if __name__ == '__main__':
    unittest.main()
