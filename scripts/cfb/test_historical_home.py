"""Focused numerical v6 checks on synthetic scores; no API or production fit."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import t

from historical_home import design, estimate, load_or_estimate, validate
from loo_scoring import game_values, log_likelihood, venue_effect
from model import margin_model, strength_structure
from sync_data import ROOT, digest


def history_fixture():
    games = []
    for season in (2023, 2024, 2025):
        for home in (1, 2, 3):
            for away in (1, 2, 3):
                if home == away: continue
                for repeat in range(4):
                    neutral = repeat == 0
                    # Each season has a different strength ordering.
                    theta = {1: season-2023., 2: 2025.-season, 3: -2.}
                    margin = theta[home]-theta[away] + (0 if neutral else 3+home*.5) + (repeat-2)*2
                    games.append({'season': season, 'id': len(games)+1, 'home_id': home,
                                  'away_id': away, 'venue': int(not neutral), 'margin': margin})
    value = {'years': [2023, 2024, 2025], 'games': games}
    return {**value, 'input_sha256': digest(value)}


class HistoricalHomeTests(unittest.TestCase):
    def test_design_keeps_season_strengths_separate_and_neutral_home_zero(self):
        history = history_fixture()
        X, strengths, hosts = design(history['games'])
        self.assertEqual(len(strengths), 9)
        self.assertEqual(hosts, [1, 2, 3])
        self.assertNotEqual(strengths.index((2023, 1)), strengths.index((2024, 1)))
        neutral = [i for i, g in enumerate(history['games']) if not g['venue']]
        np.testing.assert_array_equal(X[neutral, len(strengths):].toarray(), 0)

    def test_covariance_marginalizes_strengths_and_preserves_home_correlations(self):
        history = history_fixture()
        prior = estimate(history, [1, 2, 3, 4])
        validate(prior, 2026, [1, 2, 3, 4], history['input_sha256'])
        self.assertNotIn('theta', prior)
        self.assertEqual(prior['diagnostics']['historical_team_season_parameters'], 9)
        self.assertEqual(prior['mean'][4], 0)
        C = np.array(prior['covariance'])
        self.assertAlmostEqual(C[4, 4], 2**2 + .75**2, places=6)
        self.assertTrue(np.all(C[4, :4] == 0))
        self.assertLess(C[0, 1], 0)  # National and school effects are not independent.
        X, strengths, hosts = design(history['games'])
        X = X.toarray()
        n = len(strengths)
        mean = np.r_[np.zeros(n), 2., np.zeros(len(hosts))]
        sd = np.r_[np.full(n, 14.), 2.5, np.full(len(hosts), 2.)]
        precision = (14/sd)**2
        y = np.array([g['margin'] for g in history['games']])
        b = mean.copy()
        for _ in range(100):
            w = 13/(12+((y-X@b)/14)**2)
            H = X.T @ (w[:, None]*X) + np.diag(precision)
            b = np.linalg.solve(H, X.T@(w*y)+precision*mean)
        w = 13/(12+((y-X@b)/14)**2)
        H = X.T @ (w[:, None]*X) + np.diag(precision)
        expected = 14**2 * np.linalg.inv(H)[n:, n:]
        expected += np.diag([.25**2, .75**2, .75**2, .75**2])
        np.testing.assert_allclose(C[:4, :4], expected, atol=2e-8, rtol=1e-9)
        conditional = 14**2 * np.linalg.inv(H[n:, n:])
        self.assertGreater(expected[0, 0]-.25**2, conditional[0, 0])

    def test_prior_is_cached_across_weeks_but_not_history_corrections(self):
        base = Path(os.environ.get('CFB_TEST_TMP', ROOT / '.codex-tmp' / 'cfb-v6-review'))
        created = not base.exists()
        base.mkdir(parents=True, exist_ok=True)
        if created: self.addCleanup(base.rmdir)
        with tempfile.TemporaryDirectory(dir=base) as temporary:
            inputs = {'season': 2026, 'teams': [{'id': i} for i in (1, 2, 3, 4)],
                      'fbs_indices': list(range(4)), 'home_history': history_fixture()}
            with patch('historical_home.estimate', wraps=estimate) as estimator:
                first = load_or_estimate(inputs, temporary)
                inputs['data'] = {'margin': [100]}  # Target-year evidence cannot refit historical prior.
                self.assertEqual(first, load_or_estimate(inputs, temporary))
                self.assertEqual(estimator.call_count, 1)
                inputs['home_history']['games'][0]['margin'] += 1
                inputs['home_history']['input_sha256'] = digest(inputs['home_history']['games'])
                second = load_or_estimate(inputs, temporary)
                self.assertEqual(estimator.call_count, 2)
                self.assertNotEqual(first['mean'], second['mean'])
            for change in ({'years': [2022, 2023, 2024]}, {'fbs_ids': [4, 3, 2, 1]}):
                with self.assertRaises(ValueError):
                    validate({**second, **change}, 2026, [1, 2, 3, 4], inputs['home_history']['input_sha256'])


class HostScoringTests(unittest.TestCase):
    def setUp(self):
        self.flat = {'theta': np.array([[5., 1., -4.], [6., 0., -3.]]),
                     'home_effect': np.array([[3., 2., -1.], [4., 1., -2.]]),
                     'home_adv': np.array([3., 4.]), 'sigma': np.array([14., 15.]), 'nu': np.array([8., 9.])}
        self.data = {'home': [0, 1, 2], 'away': [1, 0, 0], 'host': [1, 2, 0],
                     'venue': [1, 0, 1], 'margin': [7., -3., -10.]}

    def test_host_offset_neutral_and_fcs_host_in_likelihood(self):
        effect = venue_effect(self.flat, self.data)
        np.testing.assert_array_equal(effect, [[5., 0., 3.], [5., 0., 4.]])
        mu = self.flat['theta'][:, self.data['home']]-self.flat['theta'][:, self.data['away']]+effect
        expected = t.logpdf(np.array(self.data['margin']), self.flat['nu'][:, None], loc=mu, scale=self.flat['sigma'][:, None])
        np.testing.assert_allclose(log_likelihood(self.flat, self.data), expected)
        with self.assertRaises(ValueError):
            venue_effect({k: v for k, v in self.flat.items() if k != 'home_effect'}, self.data)

    def test_reference_cdf_adds_actual_host_for_home_subtracts_for_visitor(self):
        reference = np.array([1., 2.])
        values = game_values(self.flat, self.data, 0, reference_rank=2, reference=reference)
        home_mu = reference-self.flat['theta'][:, 1]+5
        away_mu = reference-self.flat['theta'][:, 0]-5
        np.testing.assert_allclose(values['home_cdf'], t.cdf(7., self.flat['nu'], loc=home_mu, scale=self.flat['sigma']))
        np.testing.assert_allclose(values['away_cdf'], t.cdf(-7., self.flat['nu'], loc=away_mu, scale=self.flat['sigma']))
        changed = copy.deepcopy(self.flat)
        changed['home_effect'][:, 2] += 100  # Visitor's own home effect has no role.
        again = game_values(changed, self.data, 0, reference_rank=2, reference=reference)
        for key in values: np.testing.assert_array_equal(values[key], again[key])

    def test_current_model_uses_correlated_home_prior_and_fresh_strengths(self):
        import jax
        import jax.numpy as jnp
        from numpyro.handlers import seed, substitute, trace
        jax.config.update('jax_enable_x64', True)
        mean = jnp.array([3., 2., -1.])
        chol = jnp.array([[1., 0., 0.], [-.5, 1., 0.], [-.25, .1, 1.]])
        z = jnp.array([1., 2., 3.])
        structure = strength_structure([dict(id=i+1, name=str(i), classification='fbs' if i<2 else 'fcs',
                                             conference='Example') for i in range(3)])
        conditioned = substitute(margin_model, data={'home_z': z, 'theta_z': jnp.array([.5, .1, 1.6]),
            'mu_fcs': -20., 'tau_division': jnp.array([10.,10.]), 'tau_conf': 5., 'conference_z': jnp.zeros(2)})
        traced = trace(seed(conditioned, rng_seed=42)).get_trace(
            3, jnp.array(self.data['home']), jnp.array(self.data['away']),
            jnp.array(self.data['venue']), jnp.array(self.data['margin']),
            host=jnp.array(self.data['host']), home_prior=(mean, chol), structure=structure)
        effects = np.asarray(mean+chol@z)
        np.testing.assert_allclose(traced['home_effect']['value'], effects)
        self.assertEqual(traced['theta']['type'], 'deterministic')
        np.testing.assert_allclose(traced['theta']['value'], [5.,1.,-4.])
        np.testing.assert_allclose(traced['margin']['fn'].loc, [4+effects[0]+effects[1], -4., -9+effects[0]])
        self.assertGreater(float(traced['sigma']['value']), 8.)

    def test_school_total_summary_retains_national_offset_covariance(self):
        from posterior_summary import summarize
        offset = self.flat['home_effect'][:, 1]
        total = self.flat['home_adv'] + offset
        # Here national and school draws move oppositely; total is constant.
        self.assertGreater(summarize(offset)['sd'], 0)
        self.assertGreater(summarize(self.flat['home_adv'])['sd'], 0)
        self.assertEqual(summarize(total)['sd'], 0)


if __name__ == '__main__':
    unittest.main()
