"""Focused stdlib checks of v2 ordering; no fitting, network, or files."""
from dataclasses import replace
import itertools
import math
import unittest

from ranking_policy import CANONICAL, objective, optimize, prepare_policy


def teams(n):
    return [{'id': i + 1, 'name': chr(65 + i), 'conference': 'American Athletic'} for i in range(n)]


def games(pairs):
    return [{'id': k + 1, 'season': 2024, 'season_type': 'regular', 'eligible': True, 'completed': True,
             'home_id': w, 'away_id': l, 'home_points': 24, 'away_points': 21}
            for k, (w, l) in enumerate(pairs)]


def probability(n, pairs=None):
    p = [[0 if i == j else .5 for j in range(n)] for i in range(n)]
    for (i, j), value in (pairs or {}).items():
        p[i - 1][j - 1], p[j - 1][i - 1] = value, 1 - value
    return p


class RankingTests(unittest.TestCase):
    def make(self, roster=None, g=None, means=None, p=None, **opts):
        roster = teams(4) if roster is None else roster
        g = games([(1, 2), (3, 1), (2, 4)]) if g is None else g  # A,B both 1-1
        means = [2, 4, 3, 1] if means is None else means  # B,C,A,D
        p = probability(4, {(2, 1): .7, (2, 3): .8, (3, 1): .8}) if p is None else p
        return prepare_policy(roster, g, means, p, season=2024, **opts)

    def test_all_intermediate_crossing_costs_are_paid(self):
        state = self.make()
        result = optimize(state)
        self.assertEqual(result['order'], [2, 3, 1, 4])  # endpoint cost .44 < .5, total 1.08 > .5
        stronger = self.make(specification=replace(CANONICAL, h2h_bonus=1.5))
        moved = optimize(stronger)
        self.assertEqual(len(moved['moves']), 1)
        self.assertEqual(len(moved['moves'][0]['crossed_team_ids']), 2)
        self.assertAlmostEqual(moved['moves'][0]['objective_change'], -0.42)

    def test_intermediate_confidence_locks_block_large_bonus(self):
        state = self.make(p=probability(4, {(2, 1): .9, (2, 3): .95, (3, 1): .95}),
                          specification=replace(CANONICAL, h2h_bonus=100))
        result = optimize(state)
        self.assertEqual(result['order'], [2, 3, 1, 4])
        self.assertFalse(result['moves'])

    def test_exact_ninety_is_eligible_but_above_ninety_is_locked(self):
        for p_value, allowed in ((.90, True), (.900001, False)):
            state = self.make(p=probability(4, {(2, 1): p_value}),
                              specification=replace(CANONICAL, h2h_bonus=100))
            result = optimize(state)
            self.assertEqual(result['order'].index(1) < result['order'].index(2), allowed)

    def test_zero_bonuses_keep_mean_order_without_hard_conflicts(self):
        state = self.make(specification=replace(CANONICAL, h2h_bonus=0, common_bonus=0))
        result = optimize(state)
        self.assertEqual(result['order'], result['raw_order'])
        self.assertFalse(result['moves'])

    def test_unequal_records_do_not_get_direct_preference(self):
        state = self.make(teams(2), games([(1, 2)]), [0, 1], probability(2))
        self.assertFalse(state['evidence'])
        self.assertEqual(optimize(state)['order'], [2, 1])

    def test_split_direct_results_do_not_create_direct_preference(self):
        state = self.make(teams(2), games([(1, 2), (2, 1)]), [0, 1], probability(2))
        self.assertFalse(state['evidence'])

    def test_common_opponent_dominance_and_mixed_results(self):
        g = games([(1, 3), (4, 1), (3, 2), (2, 5)])
        state = self.make(teams(5), g, [1, 2, 0, 3, -1], probability(5))
        self.assertTrue(any(e['winner_id'] == 1 and e['loser_id'] == 2
                            and e['type'] == 'common_opponents' for e in state['evidence']))
        g = games([(1, 3), (4, 1), (3, 2), (2, 4)])
        state = self.make(teams(4), g, [1, 2, 0, 3], probability(4))
        self.assertFalse(any({e['winner_id'], e['loser_id']} == {1, 2} for e in state['evidence']))

    def test_soft_h2h_cycles_are_not_hard_constraints(self):
        state = self.make(teams(3), games([(1, 2), (2, 3), (3, 1)]), [3, 2, 1], probability(3))
        result = optimize(state)
        self.assertEqual(sorted(result['order']), [1, 2, 3])
        self.assertEqual(len(result['evidence']), 3)
        self.assertFalse(all(e['honored'] for e in result['evidence']))

    def test_confidence_lock_also_applies_against_the_mean_order(self):
        state = self.make(teams(2), games([(1, 2), (2, 1)]), [2, 1], probability(2, {(2, 1): .95}))
        result = optimize(state)
        self.assertEqual(result['raw_order'], [1, 2])
        self.assertEqual(result['order'], [2, 1])
        self.assertNotEqual(result['initial_feasible_order'], result['raw_order'])

    def test_equal_draws_do_not_create_reverse_certainty(self):
        state = self.make(teams(2), games([(1, 2), (2, 1)]), [0, 0], [[0, 0], [0, 0]])
        self.assertFalse(state['locks'])
        self.assertEqual(optimize(state)['order'], [1, 2])

    def test_no_game_teams_are_unranked(self):
        state = self.make(teams(3), games([(1, 2)]), [1, -1, 0], probability(3))
        result = optimize(state)
        self.assertEqual(result['order'], [1, 2])
        self.assertEqual(result['unranked'], [3])

    def test_p4_exception_is_explicit_and_does_not_protect_independents(self):
        roster = teams(2)
        roster[0]['conference'] = 'ACC'
        g = games([(1, 2)] * 8)
        p = probability(2, {(2, 1): .99})
        result = optimize(self.make(roster, g, [0, 1], p))
        self.assertEqual(result['order'], [1, 2])
        self.assertEqual(result['protected_team_ids'], [1])
        self.assertEqual(len(result['protection_exceptions']), 1)
        roster[0]['conference'] = 'FBS Independents'
        self.assertEqual(optimize(self.make(roster, g, [0, 1], p))['order'], [2, 1])
        roster[0]['conference'] = None
        with self.assertRaisesRegex(ValueError, 'Missing season conference'):
            self.make(roster, g, [0, 1], p)

    def test_p4_does_not_silently_remove_an_intermediate_lock(self):
        roster = teams(4)
        roster[0]['conference'] = 'ACC'
        g = games([(1, 2)] * 2 + [(1, 4)] * 6 + [(3, 2), (4, 3)])
        p = probability(4, {(2, 3): .95, (3, 1): .95, (2, 1): .95})
        with self.assertRaisesRegex(ValueError, 'constraints conflict'):
            optimize(self.make(roster, g, [2, 4, 3, 1], p))

    def test_unknown_historical_policy_and_bad_probabilities_fail(self):
        with self.assertRaisesRegex(ValueError, 'historical policy'):
            prepare_policy(teams(2), games([(1, 2)]), [1, 0], probability(2), season=2023)
        for p in ([[0, .9], [.9, 0]], [[0, math.nan], [.5, 0]]):
            with self.assertRaises(ValueError):
                self.make(teams(2), games([(1, 2)]), [1, 0], p)

    def test_reproducible_local_optimum_checked_by_independent_permutations(self):
        state = self.make(specification=replace(CANONICAL, h2h_bonus=1.5))
        result = optimize(state)
        self.assertEqual(result, optimize(state))
        order = [state['ids'].index(i) for i in result['order']]
        # Exhaustive four-team enumeration is an independent oracle for this fixture.
        self.assertAlmostEqual(result['objective'], min(objective(state['cost'], p)
                               for p in itertools.permutations(range(4))))
        for start in range(4):
            for end in range(4):
                candidate = list(order)
                candidate.insert(end, candidate.pop(start))
                self.assertGreaterEqual(objective(state['cost'], candidate), result['objective'] - 1e-9)


if __name__ == '__main__':
    unittest.main()
