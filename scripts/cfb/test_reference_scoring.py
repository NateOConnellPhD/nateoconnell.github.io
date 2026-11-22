"""Reference math and real cache-path checks with synthetic draws, never HMC."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scipy.special import stdtr
import fit_saved_season as runner
from loo_scoring import game_values, game_values_by_reference, reference_strength, score
from reference_config import REFERENCE_RANKS, exact_quantities_for


class ReferenceScoringTests(unittest.TestCase):
    def test_each_reference_uses_fbs_order_statistic_in_each_draw(self):
        strengths = np.array([list(range(24)) + [1000], list(reversed(range(24))) + [1000]], float)
        flat = {'theta': strengths, 'home_adv': np.array([3., 3.]), 'sigma': np.array([14., 14.]), 'nu': np.array([8., 8.])}
        data = dict(home=[0], away=[1], venue=[1], margin=[7])
        bank = game_values_by_reference(flat, data, 0, reference_indices=list(range(24)))
        for rank in REFERENCE_RANKS:
            expected = 24-rank
            np.testing.assert_allclose(reference_strength(flat, rank, list(range(24))), expected)
            values = exact_quantities_for(bank, rank)
            np.testing.assert_allclose(values['home_cdf'], stdtr(8, (7-(expected-strengths[:, 1]+3))/14))
            np.testing.assert_allclose(values['away_cdf'], stdtr(8, (-7-(expected-strengths[:, 0]-3))/14))
            np.testing.assert_allclose(values['home_sos'], stdtr(8, -(expected-strengths[:, 1]+3)/14))
            np.testing.assert_allclose(values['away_sos'], stdtr(8, -(expected-strengths[:, 0]-3)/14))
        np.testing.assert_allclose(game_values(flat, data, 0, reference_indices=list(range(24)))['home_cdf'], bank['r12_home_cdf'])
        self.assertTrue(np.all(bank['r2_home_sos'] < bank['r24_home_sos']))

    def test_missing_or_wrong_reference_cannot_reuse_an_exact_cache(self):
        with self.assertRaisesRegex(ValueError, 'missing reference'):
            exact_quantities_for({'home_cdf': np.ones(4)}, 12)
        for rank in (25, 0, True, '12'):
            with self.assertRaises(ValueError): exact_quantities_for({}, rank)

    def test_four_references_share_main_fit_and_exact_refit_and_reuse_saved_scores(self):
        base = Path(os.environ['CFB_TEST_TMP'])
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ))
            stack.enter_context(patch.object(runner, 'TASK', Path(temporary)))
            samples = {'theta': np.tile(np.arange(26, dtype=float), (4, 10, 1)),
                       'home_adv': np.full((4, 10), 3.), 'sigma': np.full((4, 10), 14.), 'nu': np.full((4, 10), 8.)}
            data = dict(home=[0, 2], away=[1, 3], venue=[1, 0], margin=[7, -3])
            inputs = {'teams': [dict(id=i, name=str(i), classification='fbs' if i<24 else 'fcs') for i in range(26)],
                      'data': data, 'games': [dict(id=100), dict(id=200)], 'strength_structure': {},
                      'fbs_indices': list(range(24)), 'scored_game_indices': [0, 1],
                      'cutoff': '2026-09-14T00:00:00Z', 'home_history': {'input_sha256': 'history'}}
            prior = dict(years=[2023, 2024, 2025], history_input_sha256='history', specification={}, diagnostics={'converged': True})
            stack.enter_context(patch.object(runner, 'load_inputs', return_value=inputs))
            stack.enter_context(patch('historical_home.load_or_estimate', return_value=prior))
            fitted = stack.enter_context(patch.object(runner, 'fit', return_value='sampler'))
            stack.enter_context(patch('refit_2024.describe', return_value=(samples, {'sampling_checks_passed': True}, {})))
            stack.enter_context(patch('refit_2024.predictive_summary', return_value={}))
            stack.enter_context(patch('loo_scoring.score', side_effect=lambda *a, **kw: score(*a, reff=1., **kw)))
            stack.enter_context(patch('loo_scoring.loo_weights', return_value=(np.full((2, 40), .025), np.array([.8, .1]))))
            stack.enter_context(patch('ranking_policy.rank_merit', side_effect=lambda teams, games, merit, **kw:
                {'teams': [dict(id=t['id'], status='ranked' if i<4 else 'unranked',
                                merit_mean=float(merit[:, i].mean())) for i, t in enumerate(teams[:24])]}))
            results = {}
            with contextlib.redirect_stdout(io.StringIO()):
                for rank in (12, 2, 4, 24):
                    results[rank] = runner.run(2026, through_week=2, exact_loo=True, reference_rank=rank)
                again = runner.run(2026, through_week=2, exact_loo=True)
            self.assertEqual(fitted.call_count, 2, 'Only one main fit and one omitted-game fit across all reference choices')
            self.assertEqual(fitted.call_args_list[0].kwargs['margin'], [7, -3])
            self.assertEqual(fitted.call_args_list[1].kwargs['margin'], [-3], 'The scored game is omitted from the exact fit')
            self.assertEqual(len({r['identity']['fit_key'] for r in results.values()}), 1)
            self.assertEqual(len({r['identity']['score_key'] for r in results.values()}), 4)
            self.assertEqual(results[12], again)
            self.assertEqual([results[r]['reference_rank'] for r in REFERENCE_RANKS], list(REFERENCE_RANKS))
            self.assertLess(results[2]['teams'][0]['merit_mean'], results[24]['teams'][0]['merit_mean'])
            self.assertLess(results[2]['teams'][0]['sos_mean'], results[24]['teams'][0]['sos_mean'])


if __name__ == '__main__':
    unittest.main()
