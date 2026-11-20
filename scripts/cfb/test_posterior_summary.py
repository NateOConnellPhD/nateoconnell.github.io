"""Distribution export checks without numerical dependencies or inference."""
import math
import unittest
from posterior_summary import summarize


class SummaryTests(unittest.TestCase):
    def test_skewed_sample_distinguishes_mean_and_median_and_retains_tail(self):
        s = summarize([0, 0, 0, 0, 100])
        self.assertEqual(s['mean'], 20)
        self.assertEqual(s['median'], 0)
        self.assertEqual(sum(s['distribution']['counts']), 5)
        self.assertEqual(s['distribution']['counts'][-1], 1)
        self.assertEqual(s['distribution']['edges'][-1], 100)
        self.assertAlmostEqual(s['q95'], 80)

    def test_constant_and_half_rank_draws_are_empirical_masses(self):
        for values in ([2.5] * 10, [1, 1.5, 2, 2]):
            s = summarize(values, discrete=True)
            self.assertEqual(s['distribution']['kind'], 'mass')
            self.assertEqual(sum(s['distribution']['counts']), len(values))
            self.assertEqual(s['distribution']['x'], sorted(set(values)))
        self.assertEqual(summarize([0, 0])['sd'], 0)

    def test_empty_singleton_and_nonfinite_rejected(self):
        for values in ([], [1], [1, math.inf], [1, math.nan]):
            with self.assertRaises(ValueError):
                summarize(values)


if __name__ == '__main__':
    unittest.main()
