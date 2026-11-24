"""Focused forecast-accuracy checks; standard library only, no fits or API calls."""
import json
from pathlib import Path
import unittest

import evaluation


def rows(values, clusters=None):
    return [{'model':value, 'actual':0., 'opener':0., 'close':0.,
             'cluster':clusters[i] if clusters else i}
            for i,value in enumerate(values)]


class ErrorSummaryTests(unittest.TestCase):
    def test_within_points_counts_include_boundaries_without_rounding(self):
        result=evaluation.summarize(rows([-14.01,-14.,-10.01,-10.,-7.01,-7.,-3.01,-3.,
                                         0.,3.,3.01,7.,7.01,10.,10.01,14.,14.01]))
        self.assertEqual(result['n'],17)
        self.assertEqual(result['within_points'],{'3':3,'7':7,'10':11,'14':15})

    def test_weekly_order_separates_seasons_and_postseason(self):
        sample=rows([0.,1.,2.,3.,4.],['2026-postseason-1','2026-regular-10',
                    '2026-regular-2','2026-regular-1','2025-regular-1'])
        result=evaluation.grouped(sample,'week')
        self.assertEqual([r['group'] for r in result],['2025-regular-1','2026-regular-1',
                         '2026-regular-2','2026-regular-10','2026-postseason-1','all'])
        self.assertEqual(sum(r['n'] for r in result[:-1]),result[-1]['n'])

    def test_balanced_errors_have_zero_bias_but_nonzero_magnitude(self):
        result=evaluation.summarize(rows([-10.,10.]))
        self.assertEqual(result['model_bias'],0.)
        self.assertEqual(result['model_mae'],10.)
        self.assertEqual(result['model_bias_se'],10.)
        self.assertEqual(result['model_mae_se'],0.)
        self.assertEqual([result['error_lo80'],result['error_hi80']],[-8.,8.])
        self.assertEqual([result['error_lo95'],result['error_hi95']],[-9.5,9.5])

    def test_error_sign_is_prediction_minus_result(self):
        sample=rows([3.,7.])
        for row in sample: row['actual']=5.
        result=evaluation.summarize(sample)
        self.assertEqual(result['model_bias'],0.)
        self.assertEqual(result['model_mae'],2.)

    def test_histogram_keeps_tails_and_exact_bin_edges(self):
        values=[-101.,-10.,-5.,0.,5.,10.,103.]
        histogram=evaluation.summarize(rows(values))['error_histogram']
        self.assertEqual(sum(histogram['counts']),len(values))
        self.assertEqual(histogram['start'],-105)
        self.assertEqual(histogram['counts'][0],1)
        self.assertEqual(histogram['counts'][-1],1)
        self.assertEqual(histogram['counts'][(0-histogram['start'])//5],1)

    def test_single_week_has_observed_ranges_but_no_cluster_se(self):
        result=evaluation.summarize(rows([-10.,10.],['week1','week1']))
        self.assertIsNone(result['model_bias_se'])
        self.assertIsNone(result['model_mae_se'])
        self.assertEqual(result['error_hi80'],8.)
        zero=evaluation.summarize(rows([0.,0.]))
        self.assertEqual(zero['error_histogram'],{'start':0,'width':5,'counts':[2]})

    def test_saved_report_reconciles_to_supplied_evaluation_records(self):
        root=Path(__file__).resolve().parents[2]
        evidence=json.loads((root/'_cfb_data/forecast_inputs/evaluation.json').read_text())
        report=json.loads((root/'assets/data/cfb/projections/backtest.json').read_text())
        for period,mae,bias in [('development',12.200791758982353,-.4143174067059464),
                                ('holdout',12.464253118002837,-.42327620901659685)]:
            result=evaluation.summarize(evidence[period])
            saved=next(r for r in report[period]['phase'] if r['group']=='all')
            self.assertAlmostEqual(result['model_mae'],mae)
            self.assertAlmostEqual(result['model_bias'],bias)
            for field in ('model_bias','error_lo80','error_hi80','error_lo95','error_hi95','error_histogram','within_points'):
                self.assertEqual(saved[field],result[field])
            self.assertEqual(sum(saved['error_histogram']['counts']),saved['n'])
            self.assertNotIn('opener_mae',saved)
            for by in ('week','phase','season','tier'):
                for group in report[period][by]:
                    field='cluster' if by=='week' else by
                    selected=[r for r in evidence[period] if group['group']=='all' or r[field]==group['group']]
                    self.assertEqual(group['n'],len(selected))
                    self.assertEqual(set(group['within_points']),{'3','7','10','14'})
                    for limit,count in group['within_points'].items():
                        self.assertEqual(count,sum(abs(r['model']-r['actual'])<=int(limit) for r in selected))
        self.assertEqual([r['group'] for r in report['holdout']['week']],
                         [f'2026-regular-{week}' for week in range(1,13)]+['all'])
        self.assertFalse(report['includes_quarterbacks'])
        self.assertFalse(report['includes_team_scores'])


if __name__=='__main__': unittest.main()
