"""Joint conference comparisons with deterministic draws; no HMC or network."""
import copy
import unittest

import numpy as np
from conference_summary import build, validate
from model import strength_structure


def fixture():
    teams = [dict(id=i+1, name=f'Team {i+1}', conference=c, classification='fcs' if i==5 else 'fbs')
             for i,c in enumerate(('SEC','SEC','Big Ten','Big Ten','FBS Independents','Ivy'))]
    inputs = dict(teams=teams, strength_structure=strength_structure(teams),
                  games=[dict(home_id=1,away_id=3),dict(home_id=2,away_id=6)])
    # A large common shift makes marginal intervals overlap, but cancels exactly
    # in paired differences. A strong independent/FCS team must not win a league rank.
    theta = np.array([[10,6,4,2,100,1000],[110,106,104,102,100,1000],
                      [210,206,204,202,100,1000],[310,306,304,302,100,1000]],float)
    labels=inputs['strength_structure']['conference_labels']
    gamma=np.zeros((4,len(labels)))
    gamma[:,labels.index('fbs:SEC')]=[2,102,202,302]
    gamma[:,labels.index('fbs:Big Ten')]=[4,104,204,304]
    return dict(theta=theta,conference_effect=gamma),inputs


class ConferenceTests(unittest.TestCase):
    def test_pairwise_gap_uses_joint_draws_and_actual_roster_equal_weights(self):
        flat,inputs=fixture(); value=build(flat,inputs)
        rows={r['name']:r for r in value['conferences']}
        self.assertEqual(set(rows),{'SEC','Big Ten'})
        self.assertEqual(value['independent_team_ids'],[5])
        self.assertEqual(rows['Big Ten']['teams_with_games'],1)
        self.assertEqual(rows['Big Ten']['teams'],2)
        pair=value['comparisons']['roster']['SEC']['Big Ten']
        self.assertEqual(pair['difference']['mean'],5.)
        self.assertEqual(pair['difference']['sd'],0.)
        self.assertEqual(pair['difference']['q05'],5.)
        self.assertEqual(pair['p_greater'],1.)
        self.assertEqual(rows['SEC']['metrics']['roster']['p_best'],1.)
        # Overall reference includes independents, but excludes the FCS roster.
        self.assertAlmostEqual(rows['SEC']['metrics']['roster']['strength']['mean'],13.6)
        self.assertLess(rows['SEC']['metrics']['roster']['strength']['q05'],rows['Big Ten']['metrics']['roster']['strength']['q95'])
        # Model conference baselines need not rank the actual roster averages alike.
        self.assertEqual(value['comparisons']['baseline']['SEC']['Big Ten']['difference']['mean'],-2.)
        self.assertEqual(rows['Big Ten']['metrics']['baseline']['point_rank'],1)

    def test_paired_uncertainty_probabilities_and_ties(self):
        flat,inputs=fixture()
        flat['theta'][:,:4]=[[4,4,0,0],[0,0,2,2],[2,2,2,2],[8,8,0,0]]
        value=build(flat,inputs)
        pair=value['comparisons']['roster']['SEC']['Big Ten']
        self.assertEqual(pair['p_greater'],.5)
        self.assertEqual(pair['p_equal'],.25)
        self.assertAlmostEqual(pair['difference']['mean'],2.5)
        self.assertAlmostEqual(pair['difference']['q05'],-1.7)
        self.assertAlmostEqual(pair['difference']['q95'],7.4)
        rows={r['name']:r['metrics']['roster'] for r in value['conferences']}
        self.assertEqual(rows['SEC']['p_best'],.625)
        self.assertEqual(rows['SEC']['rank']['mean'],1.375)

    def test_season_membership_and_merit_reference_do_not_mix(self):
        flat,inputs=fixture(); original=build(flat,inputs)
        inputs['reference_rank']=2
        self.assertEqual(build(flat,inputs),original)
        # A different season's realignment must use its own roster and clusters.
        inputs['teams'][1]['conference']='Big Ten'
        inputs['strength_structure']=strength_structure(inputs['teams'])
        changed=build(flat,inputs)
        rows={r['name']:r for r in changed['conferences']}
        self.assertEqual(rows['SEC']['team_ids'],[1])
        self.assertEqual(rows['Big Ten']['team_ids'],[2,3,4])
        self.assertAlmostEqual(changed['comparisons']['roster']['SEC']['Big Ten']['difference']['mean'],6.)
        validate(changed,list(reversed(inputs['teams'][:5])))

    def test_bad_draws_membership_and_corrupt_probabilities_are_rejected(self):
        flat,inputs=fixture(); value=build(flat,inputs)
        bad=copy.deepcopy(value)
        bad['comparisons']['roster']['SEC']['Big Ten']['p_greater']=.8
        with self.assertRaisesRegex(ValueError,'pair probability'): validate(bad,inputs['teams'][:5])
        bad=copy.deepcopy(value);bad['conferences'][0]['team_ids']=[99]
        with self.assertRaisesRegex(ValueError,'membership'): validate(bad,inputs['teams'][:5])
        flat['theta'][0,0]=np.nan
        with self.assertRaisesRegex(ValueError,'aligned joint'): build(flat,inputs)


if __name__=='__main__':
    unittest.main()
