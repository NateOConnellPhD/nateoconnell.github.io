"""Focused offline v5 acceptance checks; no data fetch, sampling or files."""
from dataclasses import replace
from itertools import permutations
import random
import unittest

from exact_order import exact_order, objective, UnsolvedOrder
from ranking_policy_v5 import CANONICAL, prepare_policy, order_policy


def fixture(n=4, *, games=(), probabilities=None, means=None, opponents=(), spec=CANONICAL):
    teams = [dict(id=i+1, name=f'Team {i+1}', conference='SEC') for i in range(n)]
    # Independent FCS opponents keep records equal without inventing FBS evidence.
    other = [dict(id=1000+i, name=f'FCS {i}', classification='fcs') for i in range(n)] + list(opponents)
    rows = [dict(id=k+1, season=2026, season_type='regular', eligible=True, completed=True,
                 home_id=h, away_id=a, home_points=hp, away_points=ap) for k, (h,a,hp,ap) in enumerate(games)]
    for i in range(n):
        rows.append(dict(id=1000+i, season=2026, season_type='regular', eligible=True, completed=True,
                         home_id=i+1, away_id=1000+i, home_points=21, away_points=7))
    p = [[0 if i == j else .99 if i < j else .01 for j in range(n)] for i in range(n)]
    for i,j,x in probabilities or ():
        p[i-1][j-1]=x; p[j-1][i-1]=1-x
    return prepare_policy(teams, rows, means or list(range(n,0,-1)), p, season=2026,
        specification=spec, opponents=other)


def undefeated_fixture(conference='SEC'):
    # A is 8–0 against FBS; B lost to A and an FCS opponent, but has more merit.
    state = fixture(n=9, games=[(1,i,20,10) for i in range(2,10)] + [(1001,2,20,10)],
                    means=[0,5]+[-5]*7, probabilities=[(1,2,.01)])
    payload = state['payload']
    for team in payload['teams']: team['conference'] = conference
    return prepare_policy(payload['teams'], [g for g in payload['games'] if g['id'] < 1000],
        payload['means'], payload['probabilities'], season=2026, opponents=payload['opponents'])


class V5Tests(unittest.TestCase):
    def result(self, **kwargs):
        return order_policy(fixture(**kwargs))

    def evidence(self, result, kind='head_to_head'):
        return [r for r in result['audit'] if r['type']==kind]

    def test_or_window_thresholds(self):
        spec=replace(CANONICAL,equal_records_only=False)
        for gap, probability, eligible, route in ((1,.99,True,'proximity'),(2,.99,True,'proximity'),
                (3,.99,False,'neither'),(3,.85,True,'probability'),(3,.95,False,'neither'),(1,.95,True,'proximity')):
            with self.subTest(gap=gap, probability=probability):
                r=self.result(games=[(gap+1,1,20,10)], probabilities=[(1,gap+1,probability)],spec=spec)
                row=self.evidence(r)[0]
                self.assertEqual((row['eligible'],row['qualification']),(eligible,route))
                if probability>=.9:
                    self.assertTrue(any(x['winner_id']==1 and x['loser_id']==gap+1 for x in self.evidence(r,'merit_protection')))

    def test_overall_records_and_split_no_fallback(self):
        r=self.result(games=[(2,1,20,10)])
        self.assertEqual(self.evidence(r),[])  # 2-0 vs 1-1 with FCS wins counted.
        r=self.result(games=[(2,1,20,10),(1,2,20,10),(1,3,20,10),(3,2,20,10)],
                      spec=replace(CANONICAL,equal_records_only=False))
        self.assertFalse(any({x['winner_id'],x['loser_id']}=={1,2} for x in
                             self.evidence(r)+self.evidence(r,'common_opponents')))

    def test_common_or_and_mixed(self):
        spec=replace(CANONICAL,equal_records_only=False)
        r=self.result(games=[(2,3,20,10),(3,1,20,10)],spec=spec)
        row=next(x for x in self.evidence(r,'common_opponents') if {x['winner_id'],x['loser_id']}=={1,2})
        self.assertEqual((row['winner_id'],row['qualification']),(2,'proximity'))
        r=self.result(games=[(2,3,20,10),(3,1,20,10),(1,4,20,10),(4,2,20,10)],spec=spec)
        self.assertFalse(any({x['winner_id'],x['loser_id']}=={1,2} for x in self.evidence(r,'common_opponents')))

    def test_triangle_global_overrides_merit(self):
        # IDs: Alabama, Tennessee, Texas; actual chain Texas > Tennessee > Alabama.
        r=self.result(n=3,games=[(3,2,20,17),(2,1,26,10)],spec=replace(CANONICAL,equal_records_only=False))
        self.assertEqual(r['order'],[3,2,1])
        row=next(x for x in self.evidence(r,'merit_protection') if x['winner_id']==1 and x['loser_id']==3)
        self.assertEqual(row['status'],'overridden_by_global_objective')
        self.assertEqual(row['conflict_path'],[3,2,1])
        self.assertEqual(r['optimization']['head_to_head'],2)
        self.assertEqual(row['raw_rank_gap'],2)

    def test_genuine_cycle_and_stable_input(self):
        state=fixture(n=3,games=[(1,2,10,0),(2,3,10,0),(3,1,10,0)])
        r=order_policy(state)
        self.assertEqual(r['optimization']['head_to_head'],2)
        self.assertEqual(sum(x['status']=='overridden_by_global_objective' for x in self.evidence(r)),1)
        payload=state['payload']
        reverse=prepare_policy(list(reversed(payload['teams'])),list(reversed(payload['games'])),list(reversed(payload['means'])),
            [list(reversed(row)) for row in reversed(payload['probabilities'])],season=2026,opponents=payload['opponents'])
        s=order_policy(reverse)
        for k in ('order','raw_order','audit','optimization'): self.assertEqual(r[k],s[k])

    def test_exact_bruteforce(self):
        rng=random.Random(5)
        for n in range(2,8):
            for repeat in range(5):
                ids=rng.sample(range(1,100),n)
                rows=[dict(before=a,after=b,priority=rng.randrange(1,4)) for a in range(n) for b in range(n)
                      if a!=b and rng.random()<.25]
                if repeat==0: rows += [dict(before=0,after=n-1,priority=0)]
                feasible=[]
                for order in permutations(range(n)):
                    try: score=objective(order,rows)
                    except UnsolvedOrder: continue
                    feasible.append((score,tuple(-ids[i] for i in order),order))
                expected=max(feasible)[2]
                actual,certificate=exact_order(ids,rows)
                self.assertEqual(tuple(actual),expected)
                self.assertTrue(certificate['optimal'])

    def test_javascript_parity(self):
        import json, os, subprocess
        from pathlib import Path
        states=[fixture(n=3,games=[(3,2,20,17),(2,1,26,10)],spec=replace(CANONICAL,equal_records_only=False)),
                fixture(n=3,games=[(1,2,10,0),(2,3,10,0),(3,1,10,0)]),
                fixture(games=[(2,3,20,10),(3,1,20,10)],spec=replace(CANONICAL,equal_records_only=False)),
                fixture(n=6,games=[(4,5,24,21),(5,2,24,21),(4,6,24,21),(6,2,24,21)],
                        probabilities=[(2,5,.93)],spec=replace(CANONICAL,head_to_head=.9,equal_records_only=False)),
                undefeated_fixture(), undefeated_fixture(None)]
        node=os.environ.get('NODE')
        if not node: self.skipTest('Set NODE for JavaScript parity')
        output=subprocess.run([node,str(Path(__file__).with_name('check_policy_v5.cjs'))],
            input=json.dumps([dict(input=s['payload'],settings=s['specification']) for s in states]),
            text=True,capture_output=True,check=True,timeout=60)
        for state,actual in zip(states,json.loads(output.stdout)):
            expected=order_policy(state)
            for key in actual: self.assertEqual(actual[key],expected[key],key)

    def test_hard_cycle(self):
        with self.assertRaises(UnsolvedOrder):
            exact_order([1,2,3],[dict(before=a,after=b,priority=0) for a,b in ((0,1),(1,2),(2,0))])

    def test_dynamic_admission_uses_current_not_raw_ranks(self):
        result = self.result(n=6, games=[(4,5,24,21),(5,2,24,21),(4,6,24,21),(6,2,24,21)],
            probabilities=[(2,5,.93)], spec=replace(CANONICAL,head_to_head=.9,equal_records_only=False))
        self.assertEqual(result['order'], [1,3,4,5,6,2])
        self.assertEqual([(r['winner_id'],r['loser_id'],r['iteration']) for r in result['dynamic_trace']],
                         [(5,2,1),(6,2,1)])
        self.assertEqual([r['raw_rank_gap'] for r in result['dynamic_trace']], [3,4])
        self.assertTrue(all(r['rank_gap'] <= 2 for r in result['dynamic_trace']))
        self.assertTrue(all(r['eligible'] for r in self.evidence(result) if r.get('admission_iteration')))

    def test_unconstrained_indiana_fills_by_global_merit_inversions(self):
        # Raw: Alabama, Indiana, Texas, Tennessee. Fix Texas > Tennessee > Alabama.
        order, proof = exact_order([1,2,3,4], [dict(before=2,after=3,priority=1),
                                             dict(before=3,after=0,priority=1)])
        self.assertEqual(order, [1,2,3,0])  # Indiana goes ahead of the constrained chain.
        self.assertEqual(proof['raw_inversions'], 3)

    def test_frozen_ties_and_no_posterior_mutation(self):
        s=fixture(means=[2,2,1,0],games=[(2,1,21,20)],spec=replace(CANONICAL,equal_records_only=False))
        import json
        before=json.dumps(s['payload'],sort_keys=True)
        r=order_policy(s)
        self.assertEqual(r['raw_order'],[1,2,3,4])
        self.assertEqual(json.dumps(s['payload'],sort_keys=True),before)

    def test_undefeated_team_has_no_conference_protection(self):
        expected = order_policy(undefeated_fixture())
        self.assertEqual(expected['order'][:2], [2,1])
        self.assertNotIn('protected_team_ids', expected)
        self.assertNotIn('undefeated_p4_protection', expected['specification'])
        self.assertFalse(any(r['type']=='undefeated_p4' for r in expected['audit']))
        for conference in ('ACC','Big Ten','Big 12','SEC','Sun Belt','Independent',None):
            with self.subTest(conference=conference):
                state = undefeated_fixture(conference)
                self.assertEqual((state['wins'][0],state['losses'][0],state['wins_fbs'][0]), (8,0,8))
                self.assertEqual(state['losses'][1], 2)
                actual = order_policy(state)
                for key in ('order','audit','optimization','dynamic_trace'):
                    self.assertEqual(actual[key],expected[key])

    def test_removed_rule_cannot_be_enabled(self):
        with self.assertRaises(TypeError):
            replace(CANONICAL,undefeated_p4_protection=True)


if __name__=='__main__': unittest.main()
