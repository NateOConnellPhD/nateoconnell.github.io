"""Forecast errors and season-week clustered uncertainty.

Paired comparisons are retained for reproducing the original research;
public_report exposes only the model's error against actual results.
"""
import math
from collections import defaultdict
from statistics import mean


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
            'model_mae_se':model_se,'clusters':k}


def grouped(rows, by):
    return [{'group':key, **summarize([r for r in rows if r[by]==key])} for key in sorted({r[by] for r in rows})] + [{'group':'all',**summarize(rows)}]


def public_report(report):
    fields=('group','n','model_mae','model_mae_se','clusters')
    return {**report, **{period:{by:[{k:r[k] for k in fields} for r in rows]
            for by,rows in report[period].items()} for period in ('development','holdout')}}


if __name__ == '__main__':
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    source=json.loads((root/'_cfb_data/forecast_inputs/evaluation.json').read_text())
    path=root/'assets/data/cfb/projections/backtest.json'
    saved=json.loads(path.read_text())
    report={**saved,**{p:{by:grouped(source[p],by) for by in ('phase','season','tier')}
                      for p in ('development','holdout')}}
    path.write_text(json.dumps(public_report(report),allow_nan=False,separators=(',',':'))+'\n')
