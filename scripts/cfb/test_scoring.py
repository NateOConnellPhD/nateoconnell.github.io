"""Focused mathematical and policy checks; no files or network requests."""
import itertools
import unittest

import numpy as np
from scipy.stats import norm
from loo_scoring import game_values, loo_weights, transport, reference_strength, aggregate_credits
from reference_policy import ReferencePolicy, components


def games(rows):
    return {name: [r[i] for r in rows] for i, name in enumerate(('home', 'away', 'venue', 'margin'))}


class PolicyTests(unittest.TestCase):
    def test_h2h_overrides_score_only_within_equal_record_slots(self):
        policy = ReferencePolicy(list('ABCD'), games([(0,1,1,7), (2,0,1,7), (1,3,1,7)]))
        self.assertIn((0,1), policy.edges)
        self.assertEqual(policy.order([1,5,4,0], [0,0,0,0]).tolist(), [0,2,1,3])

    def test_different_records_do_not_get_h2h_override(self):
        policy = ReferencePolicy(list('AB'), games([(0,1,1,7)]))
        self.assertFalse(policy.edges)
        self.assertEqual(policy.order([0,1], [0,0]).tolist(), [1,0])

    def test_common_opponent_dominance(self):
        policy = ReferencePolicy(list('ABCDE'), games([(0,2,1,7), (3,0,1,7), (2,1,1,7), (1,4,1,7)]))
        self.assertTrue(any(e['winner']=='A' and e['loser']=='B' and e['rule']=='common_opponent' and e['applied'] for e in policy.audit))

    def test_split_pair_is_not_decisive_and_counts_as_one_comparison(self):
        policy = ReferencePolicy(list('AB'), games([(0,1,1,7), (1,0,1,7)]))
        self.assertFalse(policy.edges)
        sample = {'theta':np.zeros((3,2)), 'sigma':np.full(3,14.), 'nu':np.full(3,10.)}
        np.testing.assert_allclose(policy.completed(sample), .5)

    def test_h2h_cycle_released_and_audited(self):
        policy = ReferencePolicy(list('ABC'), games([(0,1,1,7), (1,2,1,7), (2,0,1,7)]))
        self.assertFalse(policy.edges)
        self.assertEqual(sum(not e['applied'] for e in policy.audit), 3)
        point, draws = policy.ranks(np.array([[1,2,3],[2,1,3.]]), np.zeros((2,3)))
        np.testing.assert_array_equal(np.sort(draws,axis=1), [[1,2,3],[1,2,3]])

    def test_all_three_node_directed_graphs_have_correct_components(self):
        nodes = range(3)
        possible = list(itertools.permutations(nodes,2))
        for mask in range(2**len(possible)):
            edges = {e for i,e in enumerate(possible) if mask & (1<<i)}
            reach = {(i,i) for i in nodes} | edges
            for k in nodes:
                for i in nodes:
                    for j in nodes:
                        if (i,k) in reach and (k,j) in reach:
                            reach.add((i,j))
            parts = components(nodes,edges)
            self.assertEqual(sorted(n for c in parts for n in c), list(nodes))
            for i,j in possible:
                self.assertEqual(any(i in c and j in c for c in parts), (i,j) in reach and (j,i) in reach)

    def test_protection_requires_eight_wins_and_no_losses(self):
        with self.assertRaises(ValueError):
            ReferencePolicy(list('AB'), games([(0,1,1,7)]), protected={0})


class CreditTests(unittest.TestCase):
    def test_loo_recovers_known_omitted_normal_posterior(self):
        # Prior N(0,1), 10 unit-variance observations summing to 3, omit y=2.
        # Full posterior N(3/11,1/11), exact LOO N(1/10,1/10).
        rng = np.random.default_rng(485)
        theta = rng.normal(3/11, np.sqrt(1/11), 100000)
        weights, k = loo_weights(norm.logpdf(2, loc=theta)[:,None])
        self.assertLess(k[0], .7)
        mean = weights[0] @ theta
        self.assertAlmostEqual(mean, .1, delta=.004)
        self.assertAlmostEqual(weights[0] @ (theta-mean)**2, .1, delta=.004)

    def sample(self):
        return {'theta':np.zeros((4,25)), 'home_adv':np.full(4,3.), 'sigma':np.full(4,14.), 'nu':np.full(4,10.)}

    def test_fcs_strength_informs_opponents_but_not_reference_or_extra_merit(self):
        sample = self.sample()
        sample['theta'] = np.column_stack([sample['theta'], np.full((4, 2), 100.)])
        np.testing.assert_allclose(reference_strength(sample, 25, list(range(25))), 0.)
        data = games([(0, 25, 0, 7), (25, 26, 0, 14)])
        weights = np.full((2, 4), .25)
        result = aggregate_credits(sample, data, weights, reference_indices=list(range(25)), scored_indices=[0])
        expected = game_values(sample, data, 0, reference_indices=list(range(25)))['home_cdf']
        np.testing.assert_allclose(result['merit'][:, 0], expected)
        self.assertEqual([r['game'] for r in result['audit']], [0])
        self.assertTrue(np.all(result['merit'][:, 26] == 0.))

    def test_neutral_site_ignores_home_advantage_and_has_expected_signs(self):
        data = games([(0,1,0,7)])
        sample = self.sample()
        a = game_values(sample,data,0)
        sample['home_adv'][:] = 100
        b = game_values(sample,data,0)
        np.testing.assert_allclose(a['home_cdf'], b['home_cdf'])
        np.testing.assert_allclose(a['home_cdf'], -(a['away_cdf']-1))
        self.assertTrue(np.all(a['home_cdf'] > .5))

    def test_away_win_gets_more_credit_for_same_margin_and_opponent(self):
        sample = self.sample()
        home = game_values(sample,games([(0,1,1,7)]),0)['home_cdf']
        away = game_values(sample,games([(0,1,1,-7)]),0)['away_cdf']
        self.assertTrue(np.all(away > home))

    def test_credit_increases_with_margin_and_stays_bounded(self):
        values = [game_values(self.sample(), games([(0,1,1,m)]),0)['home_cdf'] for m in (1,7,21,42,100)]
        self.assertTrue(np.all(np.diff(values,axis=0) > 0))
        self.assertTrue(np.all((np.asarray(values)>0) & (np.asarray(values)<1)))

    def test_uniform_transport_preserves_draw_values(self):
        values = np.array([.2,.8,.1,.4])
        np.testing.assert_allclose(transport(values,np.full(4,.25)),values)


if __name__ == '__main__':
    unittest.main()
