"""Focused numerical/export tests; no sampler, API, or browser is started."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'cfb'))
from publish import ROOT, source, forecast, export
import publish
import numpy as np
from scipy.stats import t


class ForecastTests(unittest.TestCase):
    def fixture(self):
        n = 1000; shared = np.linspace(-5, 5, n)
        arrays = {'theta': np.column_stack([shared + 8, shared, shared - 12]),
                  'home_values': np.column_stack([np.full(n, 2.), np.full(n, 1.), np.full(n, -1.)]),
                  'sigma': np.full(n, 12.), 'nu': np.full(n, 7.)}
        teams = [{'id': k, 'name': k, 'division': 'fbs' if k != 'c' else 'fcs', 'conference': 'X'} for k in ('a', 'b', 'c')]
        game = {'id': 1, 'home': 'a', 'away': 'b', 'neutral': False, 'week': 1, 'date': '2026-09-01', 'season_type': 'regular'}
        return arrays, teams, game

    def test_joint_covariance_and_line_convention(self):
        arrays, teams, g = self.fixture()
        public, draws = export.build(arrays, teams, ['national', 'a', 'b'], [g], {}, {}, {})
        row = public['games'][0]
        self.assertEqual(row['home_margin'], 11.)
        self.assertEqual(row['home_line'], -11.)
        self.assertAlmostEqual(row['p_home'], t.cdf(11 / 12, 7))
        self.assertAlmostEqual(public['ratings'][0]['mean'], 8.)
        self.assertAlmostEqual(public['ratings'][0]['lo95'], float(np.quantile(arrays['theta'][:,0],.025)))
        self.assertEqual(len(draws['sigma']), 1000)
        self.assertTrue(np.allclose(np.array(draws['teams']['a']) - draws['teams']['b'], 8.))

    def test_neutral_reversal_and_fcs_host(self):
        arrays, teams, g = self.fixture()
        rows, _ = export.build(arrays, teams, ['national', 'a', 'b'],
            [{**g, 'neutral': True}, {**g, 'id': 2, 'neutral': True, 'home': 'b', 'away': 'a'},
             {**g, 'id': 3, 'home': 'c', 'away': 'b'}], {}, {}, {})
        a, b, c = rows['games']
        self.assertAlmostEqual(a['p_home'] + b['p_home'], 1.)
        self.assertEqual(a['home_margin'], -b['home_margin'])
        self.assertEqual(c['home_margin'], -10.)
        self.assertEqual(len(rows['ratings']), 2)

    def test_bad_draws_fail(self):
        arrays, teams, g = self.fixture(); arrays['nu'][1] = 2.
        with self.assertRaisesRegex(ValueError, 'posterior'): export.build(arrays, teams, ['national', 'a', 'b'], [g], {}, {}, {})

    def test_model_density_and_venue_shape_without_sampling(self):
        import jax
        import jax.numpy as jnp
        from numpyro.infer.util import log_density
        jax.config.update('jax_enable_x64', True)
        values = {'z': jnp.array([1., 0., -1.]), 'mu_free': jnp.array([-15.]), 'tau': jnp.array([10., 10.]),
                  'tau_conf': 5., 'w': jnp.zeros(3), 's_prev': 6., 'home_z': jnp.zeros(3),
                  'eta_sigma': np.log(6.), 'eta_nu': np.log(5.)}
        kwargs = {'n_teams': 3, 'home': jnp.array([0, 1, 2]), 'away': jnp.array([1, 0, 0]),
            'venue': jnp.array([1, 0, 1]), 'margin': jnp.array([11., -8., -20.]), 'host': jnp.array([1, 2, 0]),
            'home_prior': (jnp.array([2., 1., -1.]), jnp.eye(3)),
            'structure': {'division': [0, 0, 1], 'conference': [0, 1, 2], 'conference_labels': ['a', 'b', 'c']},
            'has_prior': jnp.array([True, True, False]), 'prior_mean': jnp.array([2., 0., 0.]),
            'prior_sd': 6., 'fcs_mean': -15.}
        density, trace = log_density(forecast.forecast_model, (), kwargs, values)
        self.assertTrue(np.isfinite(density))
        self.assertTrue(np.allclose(trace['theta']['value'], [8., 0., -25.]))
        self.assertAlmostEqual(float(trace['lik']['fn'].log_factor), float(t.logpdf(np.array([11.,-8.,-20.]),7.,loc=[11.,-8.,-31.],scale=14.).sum()))
        self.assertEqual(float(trace['sigma']['value']), 14.)

    def test_efficiency_blend_training_only_missing_fallback(self):
        y = [8., 3., -4., 17.]; p = [.8, .65, .2, None]
        target, scale, count = forecast.efficiency_target(y, p)
        logit = np.log(np.array(p[:3], float) / (1 - np.array(p[:3], float)))
        self.assertEqual(count, 3)
        self.assertEqual(scale, 4.5)  # frozen sparse-window fallback
        self.assertTrue(np.allclose(target[:3], .75 * np.array(y[:3]) + .25 * scale * logit))
        self.assertEqual(target[3], y[3])

    def test_schedule_excludes_final_past_cancelled_and_non_di(self):
        from sync_data import instant
        teams = [{'id': 1, 'classification': 'fbs'}, {'id': 2, 'classification': 'fcs'}]
        g = {'id': 1, 'homeId': 1, 'awayId': 2, 'completed': False, 'neutralSite': False,
             'startDate': '2026-11-28T12:00:00Z', 'week': 13, 'seasonType': 'regular'}
        raw = [g, {**g, 'id': 2, 'completed': True}, {**g, 'id': 3, 'status': 'cancelled'},
               {**g, 'id': 4, 'startDate': '2026-11-20T12:00:00Z'}, {**g, 'id': 5, 'awayId': 3}]
        rows = source.schedule_rows(raw, teams, instant('2026-11-22T00:00:00Z'))
        self.assertEqual([r['id'] for r in rows], [1])

    def test_saved_public_data_integrity(self):
        folder = ROOT / 'assets/data/cfb/projections'
        index = json.loads((folder / 'index.json').read_text())
        row = next(r for r in index['snapshots'] if r['id'] == index['latest'])
        doc = json.loads((folder / row['file']).read_text())
        draws = json.loads((folder / doc['draws_file']).read_text())
        self.assertEqual(len(doc['ratings']), sum(t['division'] == 'fbs' for t in doc['teams']))
        self.assertGreaterEqual(doc['meta']['draws'], 4000)
        self.assertTrue(all(len(x) == 1000 for x in draws.get('teams',draws.get('last')).values()))
        self.assertNotIn('meta', draws)
        self.assertTrue(all(0 <= r['p_home'] <= 1 for r in doc['games']))
        self.assertTrue(all(r['home_line'] == -r['home_margin'] for r in doc['games']))

    def test_publication_is_idempotent_and_schedule_changes_reuse_fit(self):
        teams = [{'id': i, 'name': str(i), 'classification': 'fbs' if i < 3 else 'fcs', 'conference': 'X'} for i in (1, 2, 3)]
        inputs = {'season': 2026, 'teams': teams, 'data': {'home': [0, 1, 2], 'away': [1, 0, 0],
            'venue': [1, 0, 1], 'host': [1, 2, 0], 'margin': [8., 3., -4.]},
            'games': [{'id': i, 'week': 1, 'home_id': h, 'away_id': a, 'home_points': hp, 'away_points': ap,
                       'start_date': '2026-09-01T00:00:00Z'} for i, h, a, hp, ap in [(1, 1, 2, 18, 10), (2, 2, 1, 13, 10), (3, 3, 1, 6, 10)]]}
        prior = {'mean_by_id': {'1': 3., '2': 0.}, 'sd': 6., 'training_seasons': [2025], 'caveat': '', 'fcs_mean_by_id': {'3':0.}, 'fcs_gap':-20., 'fcs_sd':7.3}
        home = {'mean': [2., 1., -1.], 'chol': np.eye(3).tolist(), 'fbs_ids': [1, 2], 'years': [2023, 2024, 2025]}
        future = [{'id': 4, 'week': 2, 'season_type': 'regular', 'date': '2026-09-08T00:00:00Z', 'home': '1', 'away': '2', 'neutral': False}]
        state = {'key': 'initial', 'observed': '2026-09-02T00:00:00Z'}
        def load(_, **kwargs): return inputs, prior, [.8, .65, .2], future, state['observed'], state['key']
        shape = (4, 1000)
        samples = {'theta': np.tile([8., 0., -12.], shape + (1,)), 'home_effect': np.tile([2., 1., -1.], shape + (1,)),
                   'sigma': np.full(shape, 12.), 'nu': np.full(shape, 7.), 's_prev': np.full(shape, 6.)}
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            with patch.object(publish, 'TASK', Path(tmp) / 'task'), patch.object(publish, 'PUBLIC', Path(tmp) / 'public'), \
                 patch.object(source, 'load', side_effect=load), \
                 patch('cfb_forecast.home.load_or_estimate', return_value=home), \
                 patch.object(forecast, 'fit', return_value=None) as fitter, \
                 patch.object(forecast, 'diagnose', return_value=(samples, {'sampling_checks_passed': True}, {})):
                publish.complete(2026); self.assertEqual(fitter.call_count, 1)
                publish.complete(2026); self.assertEqual(fitter.call_count, 1)
                state['observed'] = '2026-09-03T00:00:00Z'
                publish.complete(2026); self.assertEqual(fitter.call_count, 1)
                future[0]['neutral'] = True
                publish.complete(2026); self.assertEqual(fitter.call_count, 1, 'A schedule-only update must reuse the posterior')
                state['key'] = 'new results'
                publish.complete(2026); self.assertEqual(fitter.call_count, 2)
                self.assertEqual(len(list((publish.TASK / 'forecast-fits').iterdir())), 1)


if __name__ == '__main__': unittest.main()
