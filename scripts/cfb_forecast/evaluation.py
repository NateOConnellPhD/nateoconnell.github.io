"""Forecast errors and season-week clustered uncertainty.

Paired comparisons are retained for reproducing the original research;
public_report exposes only the model's error against actual results.
"""
import math
from collections import defaultdict
from statistics import mean


def signed_errors(rows):
    """Bias and observed spread of predicted minus actual home margins."""
    values = [r['model'] - r['actual'] for r in rows]
    ordered = sorted(values)
    bias = mean(values)
    clusters = defaultdict(list)
    for row, value in zip(rows, values): clusters[row['cluster']].append(value)
    k = len(clusters)
    se = math.sqrt(k / (k - 1) * sum((sum(v) - bias * len(v)) ** 2
                                    for v in clusters.values())) / len(values) if k > 1 else None
    def quantile(p):
        at = (len(ordered) - 1) * p
        lo, hi = math.floor(at), math.ceil(at)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo)
    width = 5
    start = math.floor(ordered[0] / width) * width
    counts = [0] * (math.floor((ordered[-1] - start) / width) + 1)
    for value in values: counts[math.floor((value - start) / width)] += 1
    return {'model_bias': bias, 'model_bias_se': se, 'error_median': quantile(.5),
            'error_lo80': quantile(.1), 'error_hi80': quantile(.9),
            'error_lo95': quantile(.025), 'error_hi95': quantile(.975),
            'error_histogram': {'start': start, 'width': width, 'counts': counts}}


def summarize(rows):
    if not rows: raise ValueError('No scored forecasts')
    errors = {'model':[], 'opener':[], 'close':[]}; clusters=defaultdict(list)
    for r in rows:
        for key in errors: errors[key].append(abs(r['actual'] - r[key]))
        clusters[r['cluster']].append(errors['model'][-1] - errors['opener'][-1])
    diff=mean(errors['model'])-mean(errors['opener']); n=len(rows); k=len(clusters)
    se=math.sqrt(k/(k-1)*sum((sum(v)-diff*len(v))**2 for v in clusters.values()))/n if k>1 else None
    model_clusters=defaultdict(list)
    for r,error in zip(rows,errors['model']): model_clusters[r['cluster']].append(error)
    mae=mean(errors['model'])
    model_se=math.sqrt(k/(k-1)*sum((sum(v)-mae*len(v))**2 for v in model_clusters.values()))/n if k>1 else None
    return {'n':n, **{key+'_mae':mean(val) for key,val in errors.items()}, 'difference':diff, 'se':se,
            'model_mae_se':model_se,'clusters':k,
            'within_points':{str(limit):sum(error <= limit for error in errors['model'])
                             for limit in (3,7,10,14)}, **signed_errors(rows)}


def grouped(rows, by):
    # The saved cluster distinguishes postseason week 1 from regular week 1,
    # and keeps each season's weeks separate in a multi-season report.
    field = 'cluster' if by == 'week' else by
    def week_order(key):
        season, season_type, week = key.split('-')
        return int(season), season_type != 'regular', int(week)
    keys = sorted({r[field] for r in rows}, key=week_order if by == 'week' else None)
    return [{'group':key, **summarize([r for r in rows if r[field]==key])} for key in keys] + [{'group':'all',**summarize(rows)}]


def public_report(report):
    fields=('group','n','model_mae','model_mae_se','clusters','model_bias','model_bias_se',
            'error_median','error_lo80','error_hi80','error_lo95','error_hi95','error_histogram','within_points')
    return {**report, 'error_definition':'predicted_home_margin_minus_actual_home_margin',
            'evaluated_model':'V7LDe75', 'includes_quarterbacks':False, 'includes_team_scores':False,
            **{period:{by:[{k:r[k] for k in fields} for r in rows]
            for by,rows in report[period].items()} for period in ('development','holdout')}}


if __name__ == '__main__':
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    source=json.loads((root/'_cfb_data/forecast_inputs/evaluation.json').read_text())
    path=root/'assets/data/cfb/projections/backtest.json'
    saved=json.loads(path.read_text())
    report={**saved,**{p:{by:grouped(source[p],by) for by in ('week','phase','season','tier')}
                      for p in ('development','holdout')}}
    path.write_text(json.dumps(public_report(report),allow_nan=False,separators=(',',':'))+'\n')
