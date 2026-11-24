"""Focused refresh/rollover checks using local fixtures, without API or HMC calls."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cfb'))
from cfb_forecast import refresh as r, annual, inputs, markets


class RefreshTests(unittest.TestCase):
    def test_season_rolls_in_july_not_january(self):
        for date,year in (('2027-01-20',2026),('2027-06-30',2026),('2027-07-01',2027)):
            self.assertEqual(r.season_for(dt.datetime.fromisoformat(date)),year)

    def test_ap_requires_all_ballot_points(self):
        raw=[{'season':2027,'seasonType':'regular','week':1,'polls':[{'poll':'AP Top 25',
            'ranks':[{'school':'Team 1','points':25,'firstPlaceVotes':1}]}]}]
        with self.assertRaisesRegex(ValueError,'omits votes'): r.ap_points(raw,{'team 1':'1'},2027)
        # A complete one-voter ballot, with the first-place count in the team cell.
        header='<tr><th colspan="3">Rank</th><th>Team (FPV)</th><th>Conf</th><th>Rec</th><th>Pts</th></tr>'
        rows=''.join(f'<tr><td>{i}</td><td>&lt;</td><td>NR</td><td>Team {i}{" (1)" if i==1 else ""}</td><td>X</td><td>0-0</td><td>{26-i}</td></tr>' for i in range(1,26))
        html='<h2>2027 Preseason AP Football Poll</h2><table>'+header+rows+'</table>'
        points=r.archive_ap(2027,{f'team {i}':str(i) for i in range(1,26)},lambda _:html)
        self.assertEqual(sum(points.values()),325)
        with self.assertRaisesRegex(ValueError,'requested preseason'):
            r.archive_ap(2027,{},lambda _:'<h2>2026 Preseason AP Football Poll</h2><option value="1">Preseason</option>')

    def test_portal_follows_all_pages_and_rejects_partial_table(self):
        names={f'team {i}':str(i) for i in range(100)}
        def page(start,more=False):
            body=''
            for i in range(start,start+50):
                href=f'/college/team-{i}/season/2027-football/transferportal/'
                body+=f'<a href="{href}">Team {i}</a><a href="{href}">10 Commits</a><a href="{href}">{i}.50</a>'
            return body+('<a href="?Page=2">Load More</a>' if more else '')
        calls=[]
        def fetch(url): calls.append(url); return page(50) if 'Page=2' in url else page(0,True)
        points=r.portal_points(2027,names,fetch)
        self.assertEqual(len(points),100); self.assertEqual(points['99'],99.5); self.assertEqual(len(calls),2)
        with self.assertRaisesRegex(ValueError,'Incomplete'): r.portal_points(2027,names,lambda _:page(0))

    def test_midseason_coaching_change_uses_starting_coach(self):
        def tenure(ident,start,end=None):return {'coach':{'id':ident},'effectiveStart':start,'effectiveEnd':end}
        tenures=[tenure(1,'2025-12-01T00:00:00Z','2026-10-01T00:00:00Z'),tenure(2,'2026-10-01T00:00:00Z')]
        self.assertEqual(r.coach_at(tenures,r.instant('2026-08-29T12:00:00Z')),1)
        with self.assertRaisesRegex(ValueError,'Cannot establish'):r.coach_at([],r.instant('2026-08-29T12:00:00Z'))

    def test_refresh_retains_failures_checks_daily_and_detects_talent_change(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            directory=Path(tmp)/'inputs'; data=Path(tmp)/'seasons'; priors=Path(tmp)/'priors'
            teams=[{'id':i,'school':f'Team {i}','conference':'X'} for i in range(1,102)]
            cov={str(t['id']):{f:(False if f=='new_coach' else float(t['id'])) for f in r.FIELDS} for t in teams}
            r.write(directory/'evidence.json',{'covariates':{'2026':cov},'ratings':{'2025':{}}})
            calls=[]; talent=[1.]; partial=[False]
            def syncer(year,key,**kwargs):
                calls.append('games'); r.write(data/str(year)/'teams.json',{'payload':teams})
                r.write(data/str(year)/'games.json',{'payload':[]})
            def fetch(endpoint,params,key):
                calls.append(endpoint)
                if endpoint=='/player/returning':raise ValueError('feed unavailable')
                field='talent' if endpoint=='/talent' else 'points'
                use=teams[:-1] if partial[0] and field=='talent' else teams
                return [{'year':2026,'team':t['school'],field:t['id']*talent[0]} for t in use]
            kwargs=dict(directory=directory,data=data,prior_directory=priors,cfbd=fetch,syncer=syncer,
                portal=lambda *_:{str(t['id']):float(t['id']) for t in teams})
            now=dt.datetime(2026,11,23,tzinfo=dt.timezone.utc)
            with patch('home_history_inputs.ensure_history'),patch.object(r,'complete_ap',return_value={}),patch.object(r,'coaching',return_value={k:False for k in cov}):
                first=r.refresh(2026,'test-key',now=now,**kwargs)
                self.assertTrue(first['covariates_ready']);self.assertTrue(first['needs_prior'])
                self.assertEqual(first['feeds']['returning_ppa']['status'],'retained')
                self.assertEqual(r.read(directory/'live/2026.json')['covariates']['1']['returning_ppa'],1.)
                r.write(priors/'live/2026.json',{'live_input_key':first['covariate_key'],'builder_key':r.prior_builder_key()})
                count=len(calls); second=r.refresh(2026,'test-key',now=now,**kwargs)
                self.assertFalse(second['needs_prior']);self.assertEqual(len(calls),count)
                self.assertTrue(r.needs_prior(second,{'live_input_key':second['covariate_key'],'builder_key':'old builder'}))
                talent[0]=2.
                third=r.refresh(2026,'test-key',now=now+dt.timedelta(days=1),**kwargs)
                self.assertTrue(third['needs_prior']);self.assertNotEqual(first['covariate_key'],third['covariate_key'])
                partial[0]=True
                fourth=r.refresh(2026,'test-key',now=now+dt.timedelta(days=2),**kwargs)
                self.assertEqual(fourth['feeds']['talent']['status'],'retained')
                self.assertEqual(third['covariate_key'],fourth['covariate_key'])
                self.assertEqual(r.read(directory/'evidence.json')['covariates']['2026'],cov)

    def test_prior_updates_current_only_and_extends_next_year_once(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            directory=Path(tmp)/'inputs'; priors=Path(tmp)/'priors'
            base=r.read(r.DIRECTORY/'evidence.json'); r.write(directory/'evidence.json',base)
            live={'roster':base['rosters']['2026'],'covariates':copy.deepcopy(base['covariates']['2026']),'sources':{'talent':{'observed_at':'first'}}}
            r.write(directory/'live/2026.json',live)
            first=annual.build_live(2026,directory,prior_directory=priors)
            frozen=(priors/'2026.json').read_bytes()
            live['sources']['talent']['observed_at']='second';r.write(directory/'live/2026.json',live)
            self.assertEqual(first,annual.build_live(2026,directory,prior_directory=priors))
            live['covariates']['61']['talent']+=10.;r.write(directory/'live/2026.json',live)
            changed=annual.build_live(2026,directory,prior_directory=priors)
            self.assertNotEqual(changed['mean_by_id'],first['mean_by_id']);self.assertEqual((priors/'2026.json').read_bytes(),frozen)
            r.write(directory/'live/2027.json',live)
            calls=[]
            def summary(year,data):
                calls.append(year)
                return {'ratings':base['ratings']['2025'],'fcs_ratings':base['fcs_ratings']['2025'],
                    'early_games':[{**g,'season':2026} for g in base['early_games'] if g['season']==2025],'source_hashes':{}}
            future=annual.build_live(2027,directory,prior_directory=priors,summarizer=summary)
            self.assertEqual(future['previous_season'],2026);self.assertEqual(max(future['training_seasons']),2026)
            annual.build_live(2027,directory,prior_directory=priors,summarizer=summary)
            self.assertEqual(calls,[2026])

    def test_preseason_schedule_does_not_require_completed_games(self):
        sources={n:r.read(r.DATA/'2026'/f'{n}.json') for n in ('teams','calendar','games','games-fcs')}
        for name in ('games','games-fcs'):
            sources[name]['retrieved_at']='2026-08-01T00:00:00Z'
            for game in sources[name]['payload']:game['completed']=False
        def read_saved(path,*args):return sources[path.stem]
        with patch('sync_data.read_saved',side_effect=read_saved),patch('home_history_inputs.load_history',return_value={'input_sha256':'test'}):
            result=inputs.preseason_inputs(2026,r.DATA)
        self.assertEqual(result['games'],[]);self.assertEqual(result['data']['host'],[])
        self.assertEqual(len(result['fbs_indices']),138)

    def test_annual_adapters_call_the_supplied_estimators_with_correct_scopes(self):
        import pandas as pd
        original=annual.reference_priors()
        rows=[]
        for ident,h,a,hd,ad in ((1,'1','2','fbs','fbs'),(2,'1','3','fbs','fcs'),(3,'3','4','fcs','fcs')):
            rows.append({'game_id':ident,'season':2026,'week':1,'season_type':'regular','home_team':h,'away_team':a,
                'home_division':hd,'away_division':ad,'home_points':20,'away_points':10,'neutral_site':False,'completed':True})
        frame=pd.DataFrame(rows)
        rating={'mu_fcs':-20.,'tau_fbs':10.,'tau_fcs':12.,'sigma':15.,'mean':{'1':3.,'2':1.},'var':{'1':2.,'2':2.}}
        with patch.object(annual,'season_frame',return_value=(frame,{})), \
             patch('cfb_forecast.reference.forecast_model.season_ratings',return_value=rating) as gaussian, \
             patch.object(original,'di_ratings',wraps=original.di_ratings) as ridge:
            result=annual.annual_summary(2026)
        self.assertEqual(len(gaussian.call_args.args[0]),2)
        self.assertEqual(len(ridge.call_args.args[0].sched(2026)),3)
        self.assertEqual(set(result['fcs_ratings']),{'3','4'})
        self.assertEqual(len(result['early_games']),1)

    def test_unchanged_market_check_keeps_observation_time(self):
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as tmp:
            directory=Path(tmp); payload=[{'id':1,'lines':[{'provider':'a','spread':-3}]}]
            markets.sync(2026,'day1','test-key',directory,lambda *_:payload)
            first=markets.read(2026,directory)
            markets.sync(2026,'day2','test-key',directory,lambda *_:payload)
            second=markets.read(2026,directory)
            self.assertEqual(first['observed_at'],second['observed_at']);self.assertEqual(first['games'],second['games'])


if __name__ == '__main__':unittest.main()
