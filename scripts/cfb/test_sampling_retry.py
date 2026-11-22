"""Offline control-flow checks; no HMC runs, numerical imports or output files."""
import json
import unittest
from unittest.mock import Mock

from sampling_retry import checked_exact_refit, ExactLOOSamplingError


class SamplingRetryTests(unittest.TestCase):
    def run_attempts(self, diagnostics):
        fit = Mock(return_value='sampler')
        describe = Mock(side_effect=[({'draws': i}, d, {}) for i, d in enumerate(diagnostics)])
        emit = Mock()
        return fit, describe, emit

    def test_passing_initial_fit_never_requests_extra_sampling(self):
        fit, describe, emit = self.run_attempts([{'sampling_checks_passed': True}])
        samples, diagnostics, attempts = checked_exact_refit(401862705, 123, fit, describe, emit)
        self.assertEqual(samples, {'draws': 0})
        fit.assert_called_once_with(seed=123, warmup=1000, draws=1000)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(emit.call_args.args[0]['diagnostics'], diagnostics)

    def test_failed_initial_fit_uses_only_checked_longer_posterior(self):
        fit, describe, emit = self.run_attempts([
            {'sampling_checks_passed': False, 'min_bulk_ess': 300},
            {'sampling_checks_passed': True, 'min_bulk_ess': 800}])
        samples, diagnostics, attempts = checked_exact_refit(401862705, 123, fit, describe, emit)
        self.assertEqual(samples, {'draws': 1})
        self.assertEqual(diagnostics['min_bulk_ess'], 800)
        self.assertEqual([call.kwargs for call in fit.call_args_list], [
            dict(seed=123, warmup=1000, draws=1000), dict(seed=123, warmup=2000, draws=2000)])
        self.assertEqual(attempts[0]['diagnostics']['min_bulk_ess'], 300)

    def test_two_failures_stop_with_game_and_actual_diagnostics(self):
        fit, describe, emit = self.run_attempts([
            {'sampling_checks_passed': False, 'min_tail_ess': 220},
            {'sampling_checks_passed': False, 'max_rank_normalized_rhat': 1.04}])
        with self.assertRaisesRegex(ExactLOOSamplingError, '401862705.*1.04') as caught:
            checked_exact_refit(401862705, 123, fit, describe, emit)
        self.assertEqual(fit.call_count, 2)
        self.assertEqual(caught.exception.details['attempts'][0]['diagnostics']['min_tail_ess'], 220)

    def test_nonfinite_failure_is_serializable_and_not_an_accepted_fit(self):
        fit, describe, emit = self.run_attempts([{'sampling_checks_passed': False,
            'max_rank_normalized_rhat': float('nan'), 'bfmi_by_chain': [float('inf')]}] * 2)
        with self.assertRaises(ExactLOOSamplingError) as caught:
            checked_exact_refit(1, 123, fit, describe, emit)
        self.assertIn('null', json.dumps(caught.exception.details, allow_nan=False))

    def test_unrelated_exceptions_are_not_retried_or_treated_as_diagnostic_failures(self):
        fit = Mock(side_effect=ValueError('bad game input'))
        with self.assertRaisesRegex(ValueError, 'bad game input'):
            checked_exact_refit(1, 123, fit, Mock(), Mock())
        self.assertEqual(fit.call_count, 1)


if __name__ == '__main__':
    unittest.main()
