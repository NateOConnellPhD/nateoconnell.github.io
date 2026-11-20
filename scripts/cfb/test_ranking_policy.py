"""Focused v4 decision checks: no model fits, downloads, network, or files."""
from dataclasses import asdict, replace
import unittest

from ranking_policy import CANONICAL, PolicyConflict, order_policy, prepare_policy


def teams(n):
    return [{'id': i + 1, 'name': chr(65 + i), 'conference': 'American Athletic'} for i in range(n)]


def games(pairs):
    return [{'id': k + 1, 'season': 2024, 'season_type': 'regular', 'eligible': True, 'completed': True,
             'home_id': w, 'away_id': l, 'home_points': 24, 'away_points': 21}
            for k, (w, l) in enumerate(pairs)]


def probability(n, pairs=None):
    p = [[.5] * n for _ in range(n)]
    for (i, j), value in (pairs or {}).items():
        p[i - 1][j - 1], p[j - 1][i - 1] = value, 1 - value
    return p


def case(n=2, pairs=((2, 1),), means=None, probabilities=None, **settings):
    spec = replace(CANONICAL, equal_records_only=False, undefeated_p4_protection=False, **settings)
    state = prepare_policy(teams(n), games(pairs), list(range(n, 0, -1)) if means is None else means,
                           probability(n, probabilities), season=2024, specification=spec)
    return state


class RankingTests(unittest.TestCase):
    def result(self, **kwargs):
        return order_policy(case(**kwargs))

    def test_threshold_is_inclusive_and_protection_is_strict(self):
        for p, expected in ((.9, [2, 1]), (.900001, [1, 2])):
            self.assertEqual(self.result(probabilities={(1, 2): p})['order'], expected)

    def test_independent_merit_protection_overrides_higher_h2h_threshold(self):
        r = self.result(probabilities={(1, 2): .85}, merit_protection=.8, head_to_head=.95)
        self.assertEqual(r['order'], [1, 2])
        blocked = next(a for a in r['audit'] if a['type'] == 'head_to_head')
        self.assertEqual(blocked['conflict_path'], [1, 2])

    def test_intervening_team_is_not_position_swapped(self):
        r = self.result(n=4, pairs=((3, 1), (2, 4), (4, 2)))
        self.assertEqual(r['order'], [2, 3, 1, 4])

    def test_full_protected_path_blocks_direct_rule(self):
        r = self.result(n=4, pairs=((3, 1), (2, 4), (4, 2)), merit_protection=.7,
                        probabilities={(1, 2): .71, (2, 3): .73, (1, 3): .65})
        blocked = next(a for a in r['audit'] if a['type'] == 'head_to_head')
        self.assertEqual(blocked['conflict_path'], [1, 2, 3])
        self.assertEqual([a['type'] for a in blocked['conflict_requirements']], ['merit_protection'] * 2)
        self.assertEqual(r['order'], [1, 2, 3, 4])

    def test_large_rank_gap_is_eligible(self):
        pairs = [(8, 1)] + [(a, b) for i in range(2, 8) for a, b in ((i, 8), (8, i))]
        r = self.result(n=8, pairs=pairs, probabilities={(1, 8): .7})
        self.assertEqual(r['order'], [2, 3, 4, 5, 6, 7, 8, 1])

    def test_adjacent_confident_pair_is_protected(self):
        self.assertEqual(self.result(probabilities={(1, 2): .99})['order'], [1, 2])

    def test_alphabetical_conflict_priority_not_rank_distance(self):
        r = self.result(n=3, pairs=((1, 2), (2, 3), (3, 1)), means=[3, 1, 2])
        self.assertEqual(r['order'], [1, 2, 3])
        blocked = [a for a in r['audit'] if a['status'] == 'blocked_by_conflict']
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]['conflict_path'], [1, 2, 3])

    def test_common_threshold_crossing(self):
        for threshold, before in ((.7, True), (.699, False)):
            r = self.result(n=3, pairs=((1, 3), (3, 2)), means=[2, 3, 1],
                            probabilities={(2, 1): .7, (1, 3): .99, (2, 3): .99}, common_opponents=threshold)
            self.assertEqual(r['order'].index(1) < r['order'].index(2), before)

    def test_direct_split_never_falls_back_to_common(self):
        r = self.result(n=3, pairs=((1, 2), (2, 1), (1, 3), (3, 2)))
        self.assertFalse(any({a['winner_id'], a['loser_id']} == {1, 2} for a in r['audit']))

    def test_threshold_blocked_direct_never_falls_back_to_common(self):
        r = self.result(n=3, pairs=((2, 1), (1, 3), (3, 2)),
                        probabilities={(1, 2): .7}, head_to_head=.5, common_opponents=.99)
        pair = [a for a in r['audit'] if {a['winner_id'], a['loser_id']} == {1, 2}]
        self.assertEqual([(a['type'], a['status']) for a in pair], [('head_to_head', 'blocked_by_threshold')])

    def test_equal_record_toggle(self):
        state = case()
        state['specification']['equal_records_only'] = True
        self.assertEqual(order_policy(state)['order'], [1, 2])
        self.assertEqual(self.result()['order'], [2, 1])

    def test_p4_override_and_toggle(self):
        roster = teams(2); roster[0]['conference'] = 'ACC'
        for enabled, expected in ((True, [1, 2]), (False, [2, 1])):
            r = order_policy(prepare_policy(roster, games([(1, 2)] * 8), [0, 1],
                probability(2, {(2, 1): .99}), season=2024,
                specification=replace(CANONICAL, undefeated_p4_protection=enabled)))
            self.assertEqual(r['order'], expected)
            self.assertEqual(len(r['protection_exceptions']), int(enabled))

    def test_p4_does_not_remove_intermediary_locks(self):
        roster = teams(4); roster[0]['conference'] = 'ACC'
        with self.assertRaises(PolicyConflict) as error:
            order_policy(prepare_policy(roster, games([(1, 2)] * 2 + [(1, 4)] * 6 + [(3, 2), (4, 3)]),
                [2, 4, 3, 1], probability(4, {(2, 3): .95, (3, 1): .95, (2, 1): .95}), season=2024))
        self.assertGreater(len(error.exception.decision['conflict_path']), 1)

    def test_hard_majority_cycle_fails_with_audit(self):
        with self.assertRaises(PolicyConflict) as error:
            self.result(n=3, pairs=((1, 2), (2, 3), (3, 1)), merit_protection=.5,
                        probabilities={(1, 2): .6, (2, 3): .6, (3, 1): .6})
        self.assertEqual(error.exception.decision['status'], 'blocked_by_conflict')

    def test_ties_no_game_teams_and_stable_names(self):
        r = self.result(n=3, pairs=((1, 2), (2, 1)), means=[0, 0, 100])
        self.assertEqual(r['order'], [1, 2])
        self.assertEqual(r['unranked'], [3])
        self.assertEqual(r['confidence_lock_count'], 0)

    def test_only_declared_controls(self):
        self.assertEqual(set(asdict(CANONICAL)) - {'version'},
            {'merit_protection', 'head_to_head', 'common_opponents', 'equal_records_only', 'undefeated_p4_protection'})
        for value in (.49, 1., float('nan'), True):
            with self.assertRaises(ValueError):
                replace(CANONICAL, head_to_head=value)

    def test_invalid_probability_or_missing_conference_fails(self):
        p = probability(2); p[0][1] = .9
        with self.assertRaises(ValueError):
            prepare_policy(teams(2), games([(1, 2)]), [1, 0], p, season=2024)
        roster = teams(2); roster[0]['conference'] = None
        with self.assertRaisesRegex(ValueError, 'Missing season conference'):
            prepare_policy(roster, games([(1, 2)] * 8), [1, 0], probability(2), season=2024)


if __name__ == '__main__':
    unittest.main()
