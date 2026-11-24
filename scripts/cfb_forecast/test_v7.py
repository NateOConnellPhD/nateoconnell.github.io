"""Focused frozen-prior, drift, evaluation and cache checks. No HMC or API calls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'cfb'))
from publish import ROOT, source, forecast, export
from cfb_forecast import priors, markets, evaluation


class V7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=json.loads((ROOT/'_cfb_data/forecast_inputs/evidence.json').read_text())

    def test_supplied_model_source_is_unchanged(self):
        import hashlib
        folder=Path(__file__).parent/'reference'
        for name, expected in json.loads((folder/'provenance.json').read_text())['sha256'].items():
            self.assertEqual(hashlib.sha256((folder/name).read_bytes()).hexdigest(),expected,name)

    def test_frozen_2026_prior_replay(self):
        p=priors.build(self.bundle,2026)
        self.assertEqual(p['training_games'],1005)
        self.assertEqual(p['v2_training_teams'],526)
        self.assertAlmostEqual(p['sd'],5.812458336286188)
        self.assertAlmostEqual(p['level_shift'],-2.131431875970749)
        self.assertAlmostEqual(p['coefficients']['prev'],.3725774985993873)
        self.assertAlmostEqual(p['fcs_slope'],.6887218428005305)
        self.assertAlmostEqual(p['fcs_sd'],7.283582576573239)
        self.assertEqual(p['fcs_pairs'],509)
        for k,v in p['mean_by_id'].items():
            self.assertAlmostEqual(v,p['prior_average']+sum(p['team_inputs'][k]['contributions'].values()))

    def test_prior_uses_earlier_seasons_and_handles_missing_inputs(self):
        import copy
        bundle=copy.deepcopy(self.bundle); baseline=priors.build(bundle,2025)
        # All 2025 results are irrelevant to the preseason prior for 2025.
        for g in bundle['early_games']:
            if g['season']==2025:g['margin']=9999.
        for k in bundle['ratings']['2025']['mean']: bundle['ratings']['2025']['mean'][k]=9999.
        p=priors.build(bundle,2025)
        self.assertEqual(p['mean_by_id'],baseline['mean_by_id']);self.assertEqual(p['sd'],baseline['sd'])
        with self.assertRaisesRegex(ValueError,'2023'):priors.build(bundle,2002)
        p26=priors.build(self.bundle,2026)
        for key, team in self.bundle['rosters']['2026'].items():
            if team['name'] in ('North Dakota State','Sacramento State'): self.assertNotIn(key,p26['mean_by_id'])

    def test_saved_priors_match_shared_builder(self):
        for year in range(2023,2027):
            self.assertEqual(source.preseason(year),priors.build(self.bundle,year))

    def test_dynamic_density_and_fcs_scale(self):
        import jax
        import jax.numpy as jnp
        from numpyro.infer.util import log_density
        jax.config.update('jax_enable_x64',True)
        params={'z':jnp.array([1.,0.,1.]),'mu_free':jnp.array([-20.]),'tau':jnp.array([10.,10.]),
            'tau_conf':1.,'w':jnp.zeros(3),'s_prev':6.,'home_z':jnp.zeros(3),
            'eta_sigma':np.log(6.),'eta_nu':np.log(5.),'q':2.,'zw':jnp.array([[1.,2.],[0.,0.],[-1.,-2.]])}
        kw={'n_teams':3,'home':jnp.array([0,0,2]),'away':jnp.array([1,1,1]),'venue':jnp.array([1,0,1]),
            'margin':jnp.array([8.,10.,-5.]),'host':jnp.array([1,1,0]),
            'home_prior':(jnp.array([2.,1.,-1.]),jnp.eye(3)),
            'structure':{'division':[0,0,1],'conference':[0,1,2],'conference_labels':['a','b','c']},
            'has_prior':jnp.ones(3,dtype=bool),'prior_mean':jnp.array([2.,0.,3.]),'prior_sd':6.,'fcs_mean':-20.,
            'fcs_prior':jnp.array([False,False,True]),'fcs_sd':7.,'week':jnp.array([0,1,2]),'n_weeks':3}
        density,trace=log_density(forecast.forecast_model,(),kw,params)
        self.assertTrue(np.isfinite(density))
        np.testing.assert_allclose(trace['theta']['value'],[8.,0.,-10.])
        np.testing.assert_allclose(trace['theta_last']['value'],[14.,0.,-16.])
        from scipy.stats import t
        self.assertAlmostEqual(float(trace['lik']['fn'].log_factor), float(t.logpdf(np.array([8.,10.,-5.]),7.,loc=[11.,10.,-14.],scale=14.).sum()))

    def test_drift_horizon_and_shared_table_draws(self):
        n=1000; z=np.linspace(-2,2,n)
        arrays={'theta_last':np.column_stack([z+8,z]),'drift':np.column_stack([z,-z]),
            'home_values':np.tile([2.,1.,0.],(n,1)), 'sigma':np.full(n,12.),'nu':np.full(n,7.)}
        arrays['theta']=arrays['theta_last']+arrays['drift']
        teams=[{'id':k,'name':k,'division':'fbs','conference':'X'} for k in ('1','2')]
        g={'home':'1','away':'2','neutral':False,'week':13,'id':1,'ahead':1}
        public,draws=export.build(arrays,teams,['national','1','2'],[g,{**g,'id':2,'ahead':4}],{}, {}, {})
        self.assertGreater(public['games'][1]['margin_hi80']-public['games'][1]['margin_lo80'],public['games'][0]['margin_hi80']-public['games'][0]['margin_lo80'])
        # Persisted supplied-scale last + sqrt(ahead)*innovation must be the tabulated forecast.
        from scipy.stats import t
        for row in public['games']:
            loc=np.array(draws['last']['1'])-draws['last']['2']+np.sqrt(row['ahead'])*(np.array(draws['drift']['1'])-draws['drift']['2'])+np.array(draws['home']['national'])+draws['home']['1']
            self.assertAlmostEqual(loc.mean(),row['home_margin'])
            self.assertAlmostEqual(t.cdf(loc/np.array(draws['sigma']),draws['nu']).mean(),row['p_home'])

    def test_weekly_windows_use_only_earlier_games(self):
        inputs,_,_,games,_,_=source.load(2026,forecast_week=12)
        from sync_data import instant
        first=min(instant(g['date']) for g in games)
        self.assertTrue(all(g['week']<12 and instant(g['start_date'])<first for g in inputs['games']))
        inputs,_,_,games,_,_=source.load(2026,forecast_week=1)
        self.assertEqual(inputs['games'],[]);self.assertTrue(games)

    def test_divergent_sampler_cannot_publish_and_constant_walk_is_omitted(self):
        rng=np.random.default_rng(42); shape=(4,1000)
        samples={'theta':rng.normal(size=shape+(2,)), 'q':np.exp(rng.normal(size=shape)),
            'walk':np.concatenate([np.zeros(shape+(2,1)),rng.normal(size=shape+(2,2))],axis=-1)}
        class Sampler:
            def get_samples(self,group_by_chain=False):return samples
            def get_extra_fields(self,group_by_chain=False):
                div=np.zeros(shape,bool);div[0,0]=True;div[1,0]=True
                return {'diverging':div,'energy':rng.normal(size=shape),'num_steps':np.full(shape,31)}
        _,diag,_=forecast.diagnose(Sampler())
        self.assertTrue(np.isfinite(diag['max_rank_normalized_rhat']))
        self.assertEqual(diag['divergences'],2);self.assertFalse(diag['sampling_checks_passed'])

    def test_preseason_gaussian_matches_analytic_game_forecast(self):
        from scipy.stats import norm
        teams=[{'id':1,'classification':'fbs'},{'id':2,'classification':'fcs'}]
        p={'mean_by_id':{'1':8.},'sd':6.,'tau_fbs':10.,'fcs_gap':-20.,'fcs_mean_by_id':{'2':3.},'fcs_sd':7.,'tau_fcs':12.,'sigma':14.}
        home={'mean':[2.,1.],'chol':[[1.,0.],[.5,2.]]}
        arrays=forecast.prior_arrays({'teams':teams},p,home,n=1000)
        roster=[{'id':'1','name':'A','division':'fbs'},{'id':'2','name':'B','division':'fcs'}]
        game={'id':1,'home':'1','away':'2','neutral':False,'week':1}
        public,draws=export.build(arrays,roster,['national','1'],[game],{},p['mean_by_id'],{})
        row=public['games'][0];self.assertEqual(row['home_margin'],28.)
        sd=np.sqrt(6.**2+7.**2+25.+1.+4.25+1.+14.**2)
        self.assertAlmostEqual(row['p_home'],norm.cdf(28./sd))
        self.assertAlmostEqual(row['margin_hi80'],28.+norm.ppf(.9)*sd)

    def test_divergence_context_keeps_chain_positions_and_scale_values(self):
        flags=np.array([[False,True,False],[True,False,False]])
        q=np.arange(6,dtype=float).reshape(2,3)
        result=forecast.transition_details({'q':q}, {'diverging':flags,
            'accept_prob':np.full((2,3),.97),'adapt_state.step_size':np.full((2,3),.04)})
        self.assertEqual(result['divergences_by_chain'],[1,1])
        self.assertEqual(result['divergent_transitions'],[{'chain':1,'draw':2},{'chain':2,'draw':1}])
        self.assertEqual(result['divergence_context']['q']['flagged_states'],[1.,3.])
        np.testing.assert_allclose(result['step_size_by_chain'],[.04,.04])

    def test_line_sign_median_missing_and_cache(self):
        payload=[{'id':1,'lines':[{'provider':'a','spreadOpen':-3.,'spread':-4.},{'provider':'b','spreadOpen':-5.,'spread':None}]}]
        c=markets.consensus(payload)['1'];self.assertEqual(c['open'],-4.);self.assertEqual(c['latest'],-4.)
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as temp:
            calls=[]
            def fetcher(year,key):calls.append(year);return payload
            for i in range(2): markets.sync(2026,'week12','test-key',Path(temp),fetcher)
            self.assertEqual(calls,[2026]);self.assertEqual(markets.read(2026,Path(temp))['games']['1'],c)

    def test_evaluation_replay_and_single_week_uncertainty(self):
        evidence=json.loads((ROOT/'_cfb_data/forecast_inputs/evaluation.json').read_text())
        dev=evaluation.summarize(evidence['development']);hold=evaluation.summarize(evidence['holdout'])
        self.assertEqual(dev['n'],2535);self.assertAlmostEqual(dev['model_mae'],12.200791758982351)
        self.assertAlmostEqual(dev['difference'],.07515073334132664);self.assertAlmostEqual(dev['se'],.08449882526600194)
        self.assertEqual(hold['n'],822);self.assertAlmostEqual(hold['difference'],.4806764756670714)
        self.assertIsNone(evaluation.summarize([r for r in evidence['holdout'] if r['week']==1])['se'])

    def test_model_error_uncertainty_is_not_paired_comparison_uncertainty(self):
        rows=[{'actual':0.,'model':v,'opener':v,'close':v,'cluster':i//2} for i,v in enumerate([1.,3.,5.,7.])]
        result=evaluation.summarize(rows)
        self.assertEqual(result['model_mae'],4.)
        self.assertEqual(result['model_mae_se'],2.)
        self.assertEqual(result['se'],0.)
        self.assertIsNone(evaluation.summarize(rows[:2])['model_mae_se'])

    def test_non_playoff_bowls_excluded(self):
        g={'homeClassification':'fbs','awayClassification':'fbs','notes':'College Football Playoff Quarterfinal'}
        self.assertTrue(source.is_playoff(g));self.assertFalse(source.is_playoff({**g,'notes':'Las Vegas Bowl'}))
        self.assertFalse(source.is_playoff({**g,'homeClassification':'fcs','awayClassification':'fcs','notes':'FCS Playoff'}))


if __name__=='__main__':unittest.main()
