"""Paired errors against the opener, with season-week clustered uncertainty."""
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
    return {'n':n, **{key+'_mae':mean(val) for key,val in errors.items()}, 'difference':diff, 'se':se}


def grouped(rows, by):
    return [{'group':key, **summarize([r for r in rows if r[by]==key])} for key in sorted({r[by] for r in rows})] + [{'group':'all',**summarize(rows)}]
