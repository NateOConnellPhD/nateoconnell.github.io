"""Numerical LOO fallback checks; no HMC, credentials, or network calls."""
import unittest
from unittest.mock import patch
import numpy as np
from loo_scoring import score


class ExactScoringTests(unittest.TestCase):
    def setUp(self):
        self.samples = {'theta': np.zeros((4, 10, 25)), 'home_adv': np.zeros((4, 10)),
                        'sigma': np.full((4, 10), 14.), 'nu': np.full((4, 10), 10.)}
        self.data = {'home': [0, 1], 'away': [1, 2], 'venue': [0, 0], 'margin': [7, -3]}

    def test_unreliable_game_requires_checked_exact_callback(self):
        with patch('loo_scoring.loo_weights', return_value=(np.full((2, 40), .025), np.array([.8, .2]))):
            with self.assertRaisesRegex(ValueError, 'Exact LOO'):
                score(self.samples, self.data, reff=1.)

    def test_only_unreliable_marginal_is_replaced_and_scored(self):
        calls = []
        def exact(game):
            calls.append(game)
            return {k: np.full(40, v) for k, v in
                    (('home_cdf', .8), ('away_cdf', .3), ('home_sos', .4), ('away_sos', .6))}
        with patch('loo_scoring.loo_weights', return_value=(np.full((2, 40), .025), np.array([np.inf, .2]))):
            result = score(self.samples, self.data, reff=1., exact_refitter=exact)
        self.assertEqual(calls, [0])
        np.testing.assert_allclose(result['merit'][:, 0], .8)
        self.assertAlmostEqual(result['audit'][0]['away_credit'], -.7)
        self.assertIsNone(result['audit'][0]['pareto_k'])
        self.assertEqual(result['audit'][0]['method'], 'exact_loo')
        self.assertEqual(result['audit'][1]['method'], 'psis_loo')
        self.assertEqual(result['diagnostics']['unreliable_games'], 0)
        self.assertEqual(result['diagnostics']['exact_refits'], 1)

    def test_failed_exact_refit_cannot_produce_rankings(self):
        def failed(game):
            raise ValueError('Failed MCMC')
        with patch('loo_scoring.loo_weights', return_value=(np.full((2, 40), .025), np.array([.8, .2]))):
            with self.assertRaisesRegex(ValueError, 'Failed MCMC'):
                score(self.samples, self.data, reff=1., exact_refitter=failed)


if __name__ == '__main__':
    unittest.main()
