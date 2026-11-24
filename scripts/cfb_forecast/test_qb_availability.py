"""Focused starter/refresh checks using in-memory feeds; no network or files."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cfb'))
from cfb_forecast import qb_availability as a


def roster():
    return {'team':{'id':'26'},'season':{'year':2026},'athletes':[{'position':'offense','items':[
        {'id':'5092275','displayName':'Ty Dieffenbach','position':{'abbreviation':'QB'}},
        {'id':'5142594','displayName':'Madden Iamaleava','position':{'abbreviation':'QB'}},
        {'id':'4870799','displayName':'Nico Iamaleava','position':{'abbreviation':'QB'}},
        {'id':'4899366','displayName':'Semaj Morgan','position':{'abbreviation':'WR'}}]}]}


def injury(status='Questionable'):
    return {'injuries':[{'id':'26','injuries':[{'athlete':{'displayName':'Ty Dieffenbach',
        'position':{'abbreviation':'QB'},'links':[{'href':'https://www.espn.com/college-football/player/_/id/5092275/ty-dieffenbach'}]},
        'status':status,'date':'2026-11-23T12:00:00Z'}]}]}


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.roster=a.roster_rows(roster(),'26',2026)
        self.recent=['5092275','4899366','5142594','4870799']

    def test_current_starter_retained_unless_out(self):
        for status in ('Questionable','Doubtful','Day-To-Day','Probable','Active'):
            with self.subTest(status=status):
                r=a.resolve('5092275',self.recent,self.roster,a.injury_rows(injury(status))['26'])
                self.assertEqual(r['starter'],'5092275');self.assertFalse(r['replaced'])
                self.assertEqual(r['uncertain'],status.lower() in a.UNCERTAIN)

    def test_known_out_selects_recent_qb_not_trick_passer_or_former_starter(self):
        r=a.resolve('5092275',self.recent,self.roster,a.injury_rows(injury('Out'))['26'])
        self.assertEqual(r['starter'],'5142594');self.assertTrue(r['replaced'])
        self.assertIn('inferred',r['note'])

    def test_multiple_out_and_no_evidence(self):
        injuries={p:{'status':'out'} for p in ['5092275','5142594']}
        self.assertEqual(a.resolve('5092275',self.recent,self.roster,injuries)['starter'],'4870799')
        injuries['4870799']={'status':'out'}
        r=a.resolve('5092275',self.recent,self.roster,injuries)
        self.assertIsNone(r['starter']);self.assertTrue(r['uncertain'])
        self.assertIsNone(a.resolve('5092275',self.recent,{},injuries)['starter'])

    def test_not_listed_is_not_a_health_claim(self):
        r=a.resolve('5092275',self.recent,self.roster,{})
        self.assertEqual(r['starter'],'5092275');self.assertIn('does not confirm health',r['note'])

    def test_roster_ids_positions_and_season(self):
        self.assertNotIn('4899366',self.roster)
        with self.assertRaisesRegex(ValueError,'season'):a.roster_rows(roster(),'26',2025)
        with self.assertRaisesRegex(ValueError,'team'):a.roster_rows(roster(),'30',2026)

    def test_feed_schema_and_link_id_recovery(self):
        self.assertEqual(a.injury_rows(injury())['26']['5092275']['status'],'questionable')
        for broken in ({},{'injuries':None},{'injuries':[{'id':'26'}]}):
            with self.assertRaises(ValueError):a.injury_rows(broken)
        broken=injury();broken['injuries'][0]['injuries'][0]['athlete']['links']=[]
        with self.assertRaisesRegex(ValueError,'identify'):a.injury_rows(broken)

    def test_daily_cache_identity_and_outage_preserves_reports(self):
        saved={};calls=[];day=dt.datetime(2026,11,24,tzinfo=dt.timezone.utc)
        def read(path,default=None):return copy.deepcopy(saved.get(str(path),default))
        def write(path,value):saved[str(path)]=copy.deepcopy(value)
        def fetch(url):calls.append(url);return injury('Out') if url.endswith('/injuries') else roster()
        with patch.object(a,'read',read),patch.object(a,'write',write):
            state=a.refresh(2026,['26'],now=day,fetcher=fetch,pause=lambda _:None)
            first=a.identity(2026);self.assertEqual(len(calls),2)
            a.refresh(2026,['26'],now=day,fetcher=fetch,pause=lambda _:None);self.assertEqual(len(calls),2)
            a.refresh(2026,['26'],now=day+dt.timedelta(days=1),fetcher=fetch,pause=lambda _:None)
            self.assertEqual(a.identity(2026),first)
            def outage(url):raise OSError('test outage')
            later=a.refresh(2026,['26'],now=day+dt.timedelta(days=2),fetcher=outage,pause=lambda _:None)
            self.assertEqual(later['injuries'],state['injuries']);self.assertTrue(later['errors'])
            self.assertNotEqual(a.identity(2026),first)  # Publish the stale-source explanation.
            self.assertIsNone(a.identity(2025))
            self.assertIsNone(a.refresh(2025,['26'],now=day,fetcher=fetch,pause=lambda _:None))
            self.assertEqual(len(calls),4)

    def test_empty_feed_does_not_clear_saved_out_status(self):
        old={'season':2026,'teams':{},'injuries':a.injury_rows(injury('Out')),'injuries_observed_at':'earlier'}
        def fetch(url):return {'injuries':[]} if url.endswith('/injuries') else roster()
        with patch.object(a,'read',lambda *args:copy.deepcopy(old)),patch.object(a,'write'):
            state=a.refresh(2026,['26'],now=dt.datetime(2026,11,24,tzinfo=dt.timezone.utc),fetcher=fetch,pause=lambda _:None)
        self.assertEqual(state['injuries'],old['injuries']);self.assertTrue(state['errors'])


if __name__=='__main__':unittest.main()
