"""Focused score likelihood, cutoff, cache and Python/JS parity checks.

No HMC, live network, browser or dependency download. Fixtures use TMPDIR.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/cfb'))
from cfb_forecast import scores, export, publish
import numpy as np
from scipy.optimize._numdiff import approx_derivative
from scipy.stats import truncnorm


class ScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(71)
        cls.rows = []
        cls.teams = ['1', '2', '3', '4']
        for year in range(2023, 2027):
            for game in range(100):
                h, a = rng.choice(cls.teams, 2, replace=False)
                margin = int(rng.integers(-40, 41))
                mu = 20 - 4 * (abs(margin) - 14) / 14 + (int(h) + int(a) - 5)
                lower = int(np.rint(truncnorm.rvs(-mu / 8, np.inf, loc=mu, scale=8, random_state=rng)))
                cls.rows.append({'season': year, 'id': game, 'home': h, 'away': a,
                                 'hp': lower + max(margin, 0), 'ap': lower + max(-margin, 0)})
        cls.fitted = scores.fit(cls.rows, 2026, cls.teams + ['unseen'])

    def test_truncated_likelihood_gradient_and_observed_hessian(self):
        rows = self.rows[:20]
        x, y, center, precision, _ = scores.design(rows, 2026, self.teams)
        value = center.copy(); value[0] = -8.; value[1] = -6.
        mu = x @ value[:-1]; scale = np.exp(value[-1])
        expected = -truncnorm.logpdf(y, -mu / scale, np.inf, loc=mu, scale=scale).sum()
        expected += .5 * np.sum(precision * (value - center) ** 2)
        loss, gradient = scores.objective(value, x, y, center, precision)
        self.assertAlmostEqual(loss + len(y) * .5 * np.log(2 * np.pi), expected, places=8)
        numerical = approx_derivative(lambda v: scores.objective(v, x, y, center, precision)[0], value).ravel()
        np.testing.assert_allclose(gradient, numerical, rtol=2e-6, atol=2e-6)
        curvature = approx_derivative(lambda v: scores.objective(v, x, y, center, precision)[1], value)
        np.testing.assert_allclose(scores.objective(value, x, y, center, precision, True), curvature, rtol=1e-5, atol=1e-5)

    def test_fit_recovers_scoring_pattern_and_keeps_unseen_team_uncertainty(self):
        report = self.fitted['report']; values = self.fitted['mean']
        self.assertTrue(report['checks_passed']); self.assertLess(report['max_gradient'], 1e-5)
        self.assertLess(abs(values[0] - 20), 4.)
        self.assertLess(abs(values[1] + 4), 2.)
        self.assertLess(abs(np.exp(values[2]) - 8), 2.)
        self.assertAlmostEqual(values[-1], 0.)
        self.assertAlmostEqual(self.fitted['covariance'][-1][-1], 25.)

    def test_input_selection_and_score_only_corrections(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            root = Path(tmp); history = []
            for year in (2023, 2024, 2025):
                (root / str(year)).mkdir()
                raw = {'id': year, 'homeId': 1, 'awayId': 2, 'homePoints': 31, 'awayPoints': 21}
                # A cancelled/unselected raw result must not join the fit.
                (root / str(year) / 'games.json').write_text(json.dumps({'payload': [raw, {**raw, 'id': 99}]}))
                history.append({'season': year, 'id': year, 'home_id': 1, 'away_id': 2, 'margin': 10})
            inputs = {'season': 2026, 'home_history': {'years': [2023, 2024, 2025], 'games': history},
                      'games': [{'id': 5, 'home_id': 1, 'away_id': 2, 'home_points': 14, 'away_points': 7}]}
            rows = scores.load_rows(inputs, root)
            self.assertEqual(len(rows), 4); self.assertEqual(rows[-1]['id'], 5)
            inputs['games'][0].update(home_points=21, away_points=14)
            changed = scores.load_rows(inputs, root)
            self.assertNotEqual(scores.digest(rows), scores.digest(changed))
            self.assertEqual(rows[-1]['hp'] - rows[-1]['ap'], changed[-1]['hp'] - changed[-1]['ap'])
            inputs['home_history']['years'] = [2024, 2025, 2026]
            with self.assertRaisesRegex(ValueError, 'precede'): scores.load_rows(inputs, root)

    def test_cache_reuse_and_publication_identity_without_margin_refit(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            with patch.object(scores, 'fit', return_value=self.fitted) as fit:
                _, key, reused = scores.load_or_fit(self.rows, 2026, self.teams, tmp)
                self.assertFalse(reused)
                _, key2, reused = scores.load_or_fit(self.rows, 2026, self.teams, tmp)
                self.assertEqual(key, key2); self.assertTrue(reused); self.assertEqual(fit.call_count, 1)
                changed = copy.deepcopy(self.rows); changed[-1]['hp'] += 7; changed[-1]['ap'] += 7
                _, key3, reused = scores.load_or_fit(changed, 2026, self.teams, tmp)
                self.assertNotEqual(key, key3); self.assertEqual(fit.call_count, 2)
                self.assertEqual(len(list(Path(tmp).glob('*.json'))), 1)
        inputs = {'season': 2026}
        with patch.object(publish.source, 'load', return_value=(inputs, {}, [], [], 'now', 'same margin key')), \
             patch.object(publish.qb_data, 'identity', return_value={}), \
             patch.object(scores, 'load_rows', side_effect=[self.rows, changed]):
            a = publish.request(2026); b = publish.request(2026)
            self.assertEqual(a[-2], b[-2]); self.assertNotEqual(a[-1], b[-1])

    def test_score_pairs_preserve_margin_and_reversal_including_extreme_draws(self):
        d = scores.browser_draws(self.fitted, 100)
        margins = np.linspace(-10000, 10000, 200).reshape(100, 2)
        h, a = scores.predict(d, '1', '2', margins)
        rh, ra = scores.predict(d, '2', '1', -margins)
        self.assertTrue((h >= 0).all() and (a >= 0).all())
        np.testing.assert_allclose(h - a, margins.ravel(), atol=1e-12)
        np.testing.assert_allclose(h, ra); np.testing.assert_allclose(a, rh)
        np.testing.assert_array_equal(h > a, margins.ravel() > 0)

    def test_export_and_javascript_match_scheduled_and_qb_scenario_scores(self):
        n = 300
        arrays = {'theta': np.tile([8., 0., -5., 3., 1.], (n, 1)),
                  'home_values': np.tile([2., 1.], (n, 1)), 'sigma': np.full(n, 12.),
                  'nu': np.full(n, 8.), 'lam': np.linspace(.5, 1.5, n)}
        teams = [{'id': t, 'name': t, 'division': 'fbs', 'conference': 'X'} for t in self.fitted['teams']]
        games = [{'id': 1, 'home': '1', 'away': '2', 'neutral': False, 'qb_x_home': -4., 'qb_x_away': 1.}]
        public, browser = export.build(arrays, teams, ['national', '1'], games, {}, {}, {})
        before = copy.deepcopy(public)
        scores.attach(public, browser, self.fitted)
        self.assertEqual(before['ratings'], public['ratings'])
        for key in ('p_home', 'home_margin', 'margin_lo95', 'margin_hi95'):
            self.assertEqual(before['games'][0][key], public['games'][0][key])
        browser['quarterbacks'] = {'1': {'x': -4., 'options': {'backup': 4.}}, '2': {'x': 1., 'options': {}}}
        script = """
const api=require('./assets/js/cfb-projections.js');
let input='';process.stdin.on('data',x=>input+=x);process.stdin.on('end',()=>{
 const d=api.validateDraws(JSON.parse(input));
 const result=api.matchup(d,'1','2',false);
 const scenario=api.matchup(d,'1','2',false,1,{home:'backup'});
 const old=structuredClone(d);delete old.scores;
 const unchanged=api.matchup(old,'1','2',false);
 if(unchanged.pHome!==result.pHome||unchanged.margin!==result.margin)throw Error('Changed margin model');
 const broken=structuredClone(d);broken.scores.scale.pop();
 let rejected=false;try{api.validateDraws(broken);}catch(e){rejected=true;}if(!rejected)throw Error('Accepted misaligned scores');
 process.stdout.write(JSON.stringify({result,scenario,legacyHasScores:!!unchanged.scores}));
});"""
        process = subprocess.run([os.environ.get('NODE_BINARY', 'node'), '-e', script], cwd=ROOT,
                                 input=json.dumps(browser), text=True, capture_output=True, check=True)
        js = json.loads(process.stdout); self.assertFalse(js['legacyHasScores'])
        for side in ('home', 'away'):
            for key, val in public['games'][0]['scores'][side].items():
                self.assertAlmostEqual(val, js['result']['scores'][side][key], delta=2e-5)
        self.assertGreater(js['scenario']['pHome'], js['result']['pHome'])
        self.assertGreater(js['scenario']['scores']['home']['mean'], js['result']['scores']['home']['mean'])
        self.assertNotEqual(js['scenario']['scores']['away']['mean'], js['result']['scores']['away']['mean'])

    def test_dynamic_horizon_and_extreme_tail_agree_across_languages(self):
        d = scores.browser_draws(self.fitted, 100)
        margins = np.linspace(-10000, 10000, 200).reshape(100, 2)
        hp, ap = scores.predict(d, '1', '2', margins)
        script = """
const api=require('./assets/js/cfb-projections.js');let text='';
process.stdin.on('data',x=>text+=x);process.stdin.on('end',()=>{
 const v=JSON.parse(text);const result=api.scoreOutcomes(v.scores,'1','2',v.margins);
 const ones=Array(100).fill(1),zeros=ones.map(()=>0);
 const d=api.validateDraws({schema:'cfb-projections-v1',last:{'1':ones,'2':zeros},
  drift:{'1':ones,'2':zeros},home:{national:zeros},noise:[zeros,zeros],sigma:ones,nu:ones.map(()=>7),scores:v.scores});
 const near=api.matchup(d,'1','2',true,1),far=api.matchup(d,'1','2',true,4);
 if(near.margin!==2||far.margin!==3||far.scores.home.mean===near.scores.home.mean)throw Error('Horizon did not change paired scores');
 process.stdout.write(JSON.stringify(result));
});"""
        run = subprocess.run([os.environ.get('NODE_BINARY', 'node'), '-e', script], cwd=ROOT,
                             input=json.dumps({'scores': d, 'margins': margins.ravel().tolist()}),
                             text=True, capture_output=True, check=True)
        js = json.loads(run.stdout)
        np.testing.assert_allclose(js['homeDraws'], hp, atol=2e-5, rtol=0)
        np.testing.assert_allclose(js['awayDraws'], ap, atol=2e-5, rtol=0)

    def test_invalid_rows_fail(self):
        for change in ({'hp': None}, {'hp': -1}, {'ap': float('nan')}, {'season': 2027}, {'home': '2', 'away': '2'}):
            with self.assertRaises(ValueError): scores.validate_rows([{**self.rows[0], **change}], 2026)
        with self.assertRaises(ValueError): scores.validate_rows([self.rows[0], self.rows[0]], 2026)


if __name__ == '__main__': unittest.main()
