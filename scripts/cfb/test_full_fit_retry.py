"""Full-fit recovery and real cache files with synthetic arrays; never HMC."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np
from full_fit_retry import checked_full_fit, FullFitSamplingError
from sync_data import digest


class FullFitTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ['CFB_TEST_TMP'])
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / 'fits'
        self.identity = {'seed': 123, 'warmup': 1000, 'draws': 1000, 'chains': 4, 'model': 'unchanged-fixture'}
        self.context = {'season': 2026, 'week': 2}
        self.fit, self.emit = Mock(return_value='sampler'), Mock()
        self.predictive = Mock(return_value={'checked': True})

    def run_fit(self, diagnostics):
        describe = Mock(side_effect=[({'theta': np.full((4, 2, 3), i, dtype=float)}, d, {'attempt': i})
                                     for i, d in enumerate(diagnostics)])
        return checked_full_fit(self.identity, self.cache, self.context, self.fit, describe,
                                self.predictive, self.emit)

    def test_initial_success_preserves_cache_identity_and_never_retries(self):
        samples, report, key, reused = self.run_fit([{'sampling_checks_passed': True}])
        self.assertFalse(reused)
        self.assertEqual(key, digest(self.identity))
        self.fit.assert_called_once_with(seed=123, warmup=1000, draws=1000)
        self.assertEqual(len(report['attempts']), 1)
        self.fit.reset_mock()
        again, stored, same_key, reused = self.run_fit([])
        self.fit.assert_not_called()
        self.assertTrue(reused); self.assertEqual(same_key, key); self.assertEqual(stored, report)
        np.testing.assert_array_equal(again['theta'], samples['theta'])

    def test_failed_initial_fit_retries_once_and_reuses_longer_fit_before_sampling(self):
        samples, report, key, reused = self.run_fit([
            {'sampling_checks_passed': False, 'min_bulk_ess': 200},
            {'sampling_checks_passed': True, 'min_bulk_ess': 900}])
        self.assertEqual([c.kwargs for c in self.fit.call_args_list], [
            dict(seed=123, warmup=1000, draws=1000), dict(seed=123, warmup=2000, draws=2000)])
        self.assertEqual(report['identity']['draws'], 2000)
        self.assertEqual(report['identity']['warmup'], 2000)
        self.assertNotEqual(key, digest(self.identity))
        self.assertFalse((self.cache / digest(self.identity)).exists(), 'Failed arrays must never be saved')
        np.testing.assert_array_equal(samples['theta'], np.ones((4, 2, 3)))
        self.assertEqual(self.predictive.call_count, 1)
        self.assertEqual(report['attempts'][0]['diagnostics']['min_bulk_ess'], 200)
        self.fit.reset_mock(); self.run_fit([])
        self.fit.assert_not_called()

    def test_exhausted_attempts_report_actual_diagnostics_and_save_no_arrays(self):
        with self.assertRaisesRegex(FullFitSamplingError, 'season 2026, week 2.*1.04') as caught:
            self.run_fit([{'sampling_checks_passed': False, 'min_bulk_ess': 200},
                          {'sampling_checks_passed': False, 'max_rank_normalized_rhat': 1.04}])
        self.assertEqual(len(caught.exception.details['attempts']), 2)
        self.assertEqual(caught.exception.details['phase'], 'full_fit')
        self.assertEqual(self.fit.call_count, 2)
        self.assertFalse(self.cache.exists())
        self.predictive.assert_not_called()
        events = [c.args[0] for c in self.emit.call_args_list]
        self.assertEqual([e['phase'] for e in events], ['sampling', 'diagnostics', 'sampling', 'diagnostics'])
        self.assertEqual(events[1]['diagnostics']['min_bulk_ess'], 200)

    def test_nonfinite_diagnostics_remain_readable_without_saving_failed_draws(self):
        with self.assertRaises(FullFitSamplingError) as caught:
            self.run_fit([{'sampling_checks_passed': False, 'max_rank_normalized_rhat': float('nan')}] * 2)
        self.assertIn('null', json.dumps(caught.exception.details, allow_nan=False))
        self.assertFalse(self.cache.exists())

    def test_legacy_failed_cache_is_not_accepted_or_resampled(self):
        _, report, key, _ = self.run_fit([{'sampling_checks_passed': True}])
        report['diagnostics'] = {'sampling_checks_passed': False, 'min_tail_ess': 200}
        (self.cache / key / 'report.json').write_text(json.dumps(report))
        self.fit.reset_mock()
        _, accepted, new_key, _ = self.run_fit([{'sampling_checks_passed': True}])
        self.fit.assert_called_once_with(seed=123, warmup=2000, draws=2000)
        self.assertNotEqual(new_key, key)
        self.assertTrue(accepted['attempts'][0]['restored_failure'])

    def test_corrupt_cache_and_unrelated_exceptions_do_not_trigger_retry(self):
        _, _, key, _ = self.run_fit([{'sampling_checks_passed': True}])
        (self.cache / key / 'posterior.npz').write_bytes(b'corrupt')
        self.fit.reset_mock()
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.run_fit([])
        self.fit.assert_not_called()
        self.cache = self.root / 'other'
        self.fit.side_effect = ValueError('invalid game')
        with self.assertRaisesRegex(ValueError, 'invalid game'):
            self.run_fit([])
        self.fit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
