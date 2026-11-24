"""Focused QB data, likelihood, export and cutoff checks; no sampling or network."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import datetime as dt
import gzip

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cfb'))
from cfb_forecast import qb, qb_data, export, model
from cfb_forecast.qb_extract import dropbacks
import numpy as np
import pandas as pd
from scipy.stats import t


class QBTests(unittest.TestCase):
    def test_extraction_identity_sacks_and_garbage_time(self):
        base={'pass':1.,'EPA':1.,'completion_player_id':None,'incompletion_player_id':None,
            'interception_thrown_player_id':None,'sack_taken_player_id':None,'pos_team':'A','def_pos_team':'B',
            'game_id':1,'home':'A','away':'B','week':1,'season_type':'regular','pos_score_diff_start':0.,'period':1}
        rows=[{**base,'incompletion_player_id':10,'game_play_number':1},
              {**base,'sack_taken_player_id':10,'EPA':-2.,'game_play_number':2},
              {**base,'completion_player_id':99,'game_play_number':3},
              {**base,'completion_player_id':10,'game_play_number':4,'period':4,'pos_score_diff_start':23.},
              {**base,'completion_player_id':10,'game_play_number':5,'period':4,'pos_score_diff_start':22.}]
        frame,_=dropbacks(pd.DataFrame(rows),2026); qb_data.validate(frame,2026)
        self.assertEqual(frame.passer_id.tolist(),[10]); self.assertEqual(frame.n.tolist(),[4])
        self.assertEqual(frame.epa_sum.tolist(),[1.]); self.assertEqual(frame.epa2_sum.tolist(),[7.])
        self.assertEqual(frame.first_play.tolist(),[1])

    def test_missing_season_labels_use_game_schedule_before_grouping(self):
        base={'pass':1.,'EPA':1.,'completion_player_id':None,'incompletion_player_id':10,
            'interception_thrown_player_id':None,'sack_taken_player_id':None,'pos_team':'A','def_pos_team':'B',
            'game_id':1,'home':'A','away':'B','week':1,'season_type':'regular','pos_score_diff_start':0.,'period':1}
        plays=pd.DataFrame([{**base,'game_play_number':1},
            {**base,'game_play_number':2,'season_type':None,'EPA':-2.},
            {**base,'game_id':2,'game_play_number':1,'season_type':None},
            {**base,'game_id':3,'game_play_number':1,'season_type':'postseason'}])
        # RDS factors can be categorical, including an entirely missing label.
        plays['season_type']=pd.Categorical(plays.season_type)
        frame,_=dropbacks(plays,2026,{1:'regular',2:'postseason'})
        qb_data.validate(frame,2026)
        by=frame.set_index('game_id')
        self.assertEqual(by.season_type.to_dict(),{1:'regular',2:'postseason',3:'postseason'})
        self.assertEqual(by.n.to_dict(),{1:2,2:1,3:1})
        self.assertEqual(by.epa_sum.to_dict(),{1:-1.,2:1.,3:1.})
        self.assertEqual(by.epa2_sum.to_dict(),{1:5.,2:1.,3:1.})
        self.assertEqual(by.first_play.to_dict(),{1:1,2:1,3:1})
        # The original records are not mutated; unknown games aren't guessed.
        self.assertEqual(int(plays.season_type.isna().sum()),2)
        unresolved,_=dropbacks(plays,2026,{1:'regular'})
        with self.assertRaisesRegex(ValueError,r'missing season_type; game IDs 2 \(1 rows\)'):
            qb_data.validate(unresolved,2026)
        for field in ('first_play','def_pos_team'):
            broken=frame.copy();broken[field]=None
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'missing '+field):
                qb_data.validate(broken,2026)

    def test_export_preserves_mix_ratings_and_joint_qb_draws(self):
        n=400; lam=np.linspace(.5,1.5,n)
        arrays={'theta':np.tile([8.,0.],(n,1)), 'home_values':np.zeros((n,1)),
                'sigma':np.full(n,12.),'nu':np.full(n,8.),'lam':lam}
        teams=[{'id':x,'name':x,'division':'fbs','conference':'X'} for x in ('a','b')]
        game={'id':1,'home':'a','away':'b','neutral':True,'qb_x_home':-4.,'qb_x_away':1.}
        public,draws=export.build(arrays,teams,['national'],[game],{}, {},{},thin=n)
        self.assertEqual(public['ratings'][0]['mean'],8.)
        self.assertAlmostEqual(public['games'][0]['home_margin'],3.)
        self.assertAlmostEqual(public['games'][0]['p_home'],t.cdf((8.-5*lam)/12.,8.).mean())
        self.assertTrue(np.allclose(draws['lam'],lam,atol=1e-5))
        _,thin=export.build(arrays,teams,['national'],[game],{}, {},{},thin=200)
        self.assertEqual(len(thin['lam']),len(thin['sigma']))
        self.assertEqual(len(thin['lam']),200)
        self.assertAlmostEqual(thin['lambda_mean'],float(lam.mean()))

    def test_qbterm_uses_starter_not_weighted_in_game_mix(self):
        q=qb.term_class().__new__(qb.term_class()); q.week=3; q.season=2026
        q.S=pd.DataFrame([{'game_id':1,'week':1,'pos_team':'A','passer_id':10,'n':30,'first_play':1},
            {'game_id':2,'week':2,'pos_team':'A','passer_id':20,'n':5,'first_play':1},
            {'game_id':2,'week':2,'pos_team':'A','passer_id':10,'n':25,'first_play':5}])
        q.value=lambda p,before_week=None:{10:.2,20:-.1}[p]
        frame=pd.DataFrame([{'game_id':2,'week':2,'home_team':'A','away_team':'B'}])
        self.assertAlmostEqual(q.x_training(frame)[0],((30+81)/4)*(-.3))
        # Incumbent is the most recent game's first passer, not its busiest passer.
        value,pid=q.x_for('A'); self.assertEqual(pid,20)
        self.assertAlmostEqual(value,((60+81)/5)*(-.1-(55*.2+5*(-.1))/60))

    def test_saved_data_identity_ignores_check_dates_but_sees_status(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            for y in range(2021,2027):
                (directory/f'{y}.json').write_text(json.dumps({'input_key':str(y),'names':{}}))
            before=qb_data.identity(2026,directory)
            (directory/'refresh.json').write_text('{"checked_at":"later"}')
            self.assertEqual(before,qb_data.identity(2026,directory))
            (directory/'status').mkdir();(directory/'status/2026.csv').write_text('team,passer_id,note\nA,42,Starter\n')
            after=qb_data.identity(2026,directory)
            self.assertEqual(before['data'],after['data']);self.assertNotEqual(before['status'],after['status'])
            self.assertEqual(before,qb_data.identity(2026,directory,historical=True))

    def test_preflight_requires_current_qb_data_only_after_games(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            for y in range(2021,2026):
                (directory/f'{y}.json').write_text(json.dumps({'input_key':str(y)}))
            (directory/'refresh.json').write_text(json.dumps({'seasons':{'2026':{
                'error':'Incomplete QB dropback rows for 2026: missing season_type; game IDs 123'}}}))
            self.assertIsNone(qb_data.identity(2026,directory)['data']['2026'])
            for historical in (False,True):
                with self.subTest(historical=historical), self.assertRaisesRegex(ValueError,
                        'Missing QB dropbacks for 2026: .*missing season_type; game IDs 123'):
                    qb_data.identity(2026,directory,historical=historical,require_current=True)
            (directory/'2026.json').write_text(json.dumps({'input_key':'current'}))
            self.assertEqual(qb_data.identity(2026,directory,require_current=True)['data']['2026'],'current')

    def test_daily_refresh_bootstrap_revalidation_and_last_good_data(self):
        from tempfile import TemporaryDirectory
        base={'pass':1.,'EPA':1.,'completion_player_id':None,'incompletion_player_id':10,
            'interception_thrown_player_id':None,'sack_taken_player_id':None,'pos_team':'A','def_pos_team':'B',
            'game_id':1,'home':'A','away':'B','week':1,'season_type':'regular','pos_score_diff_start':0.,'period':1,
            'game_play_number':1}
        calls=[]
        def fetch(url,path,etag=None,limit=None):
            calls.append((url,etag))
            if etag: return None
            path.parent.mkdir(parents=True,exist_ok=True)
            if url.endswith('.csv.gz'):
                path.write_bytes(gzip.compress(('game_id,start_date,home_team,away_team,home_division,away_division,season_type\n'+
                    '\n'.join(f'{i},2026-09-01T00:00:00Z,T{i},B,fbs,fcs,regular' for i in range(100))).encode()))
            else: path.write_bytes(b'fixture')
            return {'etag':'saved','sha256':'fixture','url':qb_data.BASE+url}
        with TemporaryDirectory() as temp, patch.dict(sys.modules,{'pyreadr':SimpleNamespace(
                read_r=lambda _: {None:pd.DataFrame([base,{**base,'game_play_number':2,'season_type':None}])})}):
            directory=Path(temp)/'saved';task=Path(temp)/'download'
            now=dt.datetime(2026,11,23,tzinfo=dt.timezone.utc)
            qb_data.refresh(2026,directory,task,now,fetch)
            self.assertEqual(len(calls),12); self.assertFalse(task.exists())
            current=json.loads((directory/'2026.json').read_text())
            self.assertEqual(len(current['rows']),1)
            self.assertEqual(current['rows'][0][2],'regular')
            self.assertEqual(current['rows'][0][9],2)
            first=qb_data.identity(2026,directory)
            qb_data.refresh(2026,directory,task,now,fetch);self.assertEqual(len(calls),12)
            # Migrate the previous IDs/dates-only cache even if the schedule ETag is unchanged.
            legacy={**current,'schedule':[{k:v for k,v in r.items() if k!='season_type'} for r in current['schedule']]}
            (directory/'2026.json').write_text(json.dumps(legacy))
            qb_data.refresh(2026,directory,task,now+dt.timedelta(days=1),fetch)
            self.assertEqual(len(calls),24);self.assertEqual(first,qb_data.identity(2026,directory))
            self.assertEqual(calls[-1],('cfb_schedules/cfb_schedules_2026.csv.gz',None))
            self.assertTrue(all(r['season_type']=='regular' for r in json.loads((directory/'2026.json').read_text())['schedule']))
            def failed(*a,**kw): raise ValueError('test outage')
            qb_data.refresh(2026,directory,task,now+dt.timedelta(days=2),failed)
            self.assertEqual(first,qb_data.identity(2026,directory))
            self.assertEqual(len(json.loads((directory/'refresh.json').read_text())['errors']),6)

    def test_release_redirects_are_https_github_assets_only(self):
        from urllib.request import Request
        handler=qb_data.ReleaseRedirect(); request=Request(qb_data.BASE+'cfbfastR_cfb_pbp/play_by_play_2026.rds')
        allowed=handler.redirect_request(request,None,302,'',{},'https://release-assets.githubusercontent.com/file')
        self.assertEqual(allowed.full_url,'https://release-assets.githubusercontent.com/file')
        for url in ('http://release-assets.githubusercontent.com/file','https://example.com/file'):
            with self.assertRaises(ValueError): handler.redirect_request(request,None,302,'',{},url)

    def test_qb_likelihood_density_matches_supplied_model(self):
        import jax
        import jax.numpy as jnp
        from numpyro.infer.util import log_density
        jax.config.update('jax_enable_x64',True)
        args={'n_teams':2,'home':jnp.array([0,1]),'away':jnp.array([1,0]),'venue':jnp.ones(2),
            'margin':jnp.array([10.,-5.]),'host':jnp.array([1,2]),'home_prior':(jnp.zeros(3),jnp.eye(3)),
            'structure':{'division':[0,0],'conference':[0,1],'conference_labels':['X','Y']},
            'has_prior':jnp.array([True,True]),'prior_mean':jnp.zeros(2),'prior_sd':5.,'fcs_mean':-10.,
            'qbx':jnp.array([2.,-3.])}
        values={'z':jnp.array([1.,0.]),'mu_free':jnp.array([-10.]),'tau':jnp.array([10.,10.]),
            'tau_conf':5.,'w':jnp.zeros(2),'s_prev':5.,'home_z':jnp.zeros(3),
            'eta_sigma':np.log(6.),'eta_nu':np.log(5.),'lam':1.3}
        _,trace=log_density(model.forecast_model,(),args,values)
        theta=np.asarray(trace['theta']['value']); hv=np.asarray(trace['home_values']['value'])
        sigma=float(trace['sigma']['value']);nu=float(trace['nu']['value'])
        loc=theta[[0,1]]-theta[[1,0]]+hv[0]+hv[[1,2]]+1.3*np.array([2.,-3.])
        expected=t.logpdf((np.array([10.,-5.])-loc)/sigma,nu).sum()-2*np.log(sigma)
        self.assertAlmostEqual(float(trace['lik']['fn'].log_factor),expected,places=9)


if __name__=='__main__': unittest.main()
