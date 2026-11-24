"""One prior builder for production and historical forecast windows.

Inputs are reviewed numerical summaries of public sources, never executable
pickles. Annual priors are fitted once, then reused unchanged for every week.
"""
import math
from .config import CONFIG

COLS = ('prev', 'talent_z', 'ap', 'p4', 'rpc', 'prev_rp', 'rec_z',
        'newcoach', 'prev_coach', 'portal_z', 'g5_prev')


def zscores(values):
    import numpy as np
    good = np.array([x for x in values.values() if x is not None], float)
    if len(good) < 2 or good.std(ddof=1) <= 0:
        raise ValueError('Insufficient preseason covariate coverage')
    return {k: (float(v) - good.mean()) / good.std(ddof=1) if v is not None else None for k, v in values.items()}


def covariates(bundle, season):
    import numpy as np
    roster = bundle['rosters'][str(season)]
    raw = bundle['covariates'][str(season)]
    prev = bundle['ratings'][str(season - 1)]
    talent = zscores({k: r['talent'] for k, r in raw.items() if r['talent'] is not None})
    recruit = zscores({k: raw[k]['recruiting_points'] for k in roster})
    portal = zscores({k: raw[k]['portal_points'] for k in roster})
    rows = {}
    for key, team in roster.items():
        r = raw[key]; p = prev['mean'].get(key) if key in prev['fbs'] else None
        rp = max(0., r['returning_ppa']) - .5 if r['returning_ppa'] is not None else 0.
        p4 = float(team['conference'] in ({'SEC', 'Big Ten', 'Big 12', 'ACC'} | ({'Pac-12'} if season <= 2023 else set())) or team['name'] == 'Notre Dame')
        rows[key] = {'prev': p, 'talent_z': talent.get(key), 'ap': math.log1p(r['ap_points']), 'p4': p4,
            'rpc': rp, 'prev_rp': p * rp if p is not None else None, 'rec_z': recruit[key] or 0.,
            'newcoach': float(r['new_coach']), 'prev_coach': p * r['new_coach'] if p is not None else None,
            'portal_z': portal[key], 'g5_prev': (1 - p4) * p if p is not None else None}
    return rows


def build(bundle, season, config=CONFIG):
    import numpy as np
    if season < config.first_forecast_season or str(season) not in bundle['covariates']:
        raise ValueError(f'Forecast inputs are available for 2023–{max(map(int, bundle["covariates"]))}; no substitute prior for {season}')
    years = list(range(config.prior_first_season, season))
    cov = {y: covariates(bundle, y) for y in years + [season]}
    # V2 supplies only the annual prior spread and the common FBS/FCS level.
    train2 = []
    for y in years:
        rating = bundle['ratings'][str(y)]
        for key in sorted(rating['fbs']):
            c = cov[y].get(key)
            if c and all(c[k] is not None for k in ('prev', 'talent_z', 'ap')):
                train2.append(([1., c['prev'], c['talent_z'], c['ap']], rating['mean'][key], rating['var'][key]))
    if len(train2) < 100: raise ValueError('Insufficient prior-season rating evidence')
    X = np.array([r[0] for r in train2]); yv = np.array([r[1] for r in train2]); yvar = np.array([r[2] for r in train2])
    beta2 = np.linalg.lstsq(X, yv, rcond=None)[0]
    s = float(np.sqrt(max((yv - X @ beta2).var(ddof=1) - yvar.mean(), 1.)))
    m2 = {key: float(np.array([1., c['prev'], c['talent_z'], c['ap']]) @ beta2) for key, c in cov[season].items()
          if all(c[k] is not None for k in ('prev', 'talent_z', 'ap'))}
    # Fit differences to early regular-season game margins; never use target-year results.
    X, yv = [], []
    for g in bundle['early_games']:
        if g['season'] not in years or g['week'] > config.prior_max_week or g['season_type'] != 'regular': continue
        h, a = cov[g['season']].get(g['home']), cov[g['season']].get(g['away'])
        if not h or not a or any(h[k] is None or a[k] is None for k in COLS): continue
        X.append([h[k] - a[k] for k in COLS] + [float(not g['neutral'])]); yv.append(g['margin'])
    if len(X) < 100: raise ValueError('Insufficient early-season margin training data')
    X = np.array(X); yv = np.array(yv); beta = np.linalg.lstsq(X, yv, rcond=None)[0]
    means = {key: float(np.array([c[k] for k in COLS]) @ beta[:-1]) for key, c in cov[season].items()
             if all(c[k] is not None for k in COLS)}
    common = sorted(means.keys() & m2.keys())
    shift = float(np.mean([m2[k] - means[k] for k in common]))
    means = {k: v + shift for k, v in means.items()}
    # FCS carryover uses all Division I games, with lambda=2 ridge ratings.
    ridge = bundle['fcs_ratings']; pairs = []
    for y in years:
        r0, r1 = ridge[str(y-1)], ridge[str(y)]
        pairs += [(r0[k], r1[k]) for k in sorted(r0.keys() & r1.keys())]
    p = np.array(pairs); slope, intercept = np.polyfit(p[:, 0], p[:, 1], 1)
    fs = float((p[:, 1] - intercept - slope * p[:, 0]).std())
    fm = {k: float(intercept + slope * v) for k, v in ridge[str(season-1)].items()}
    center = np.mean(list(fm.values())); fm = {k: float(v - center) for k, v in fm.items()}
    previous = bundle['ratings'][str(season-1)]
    columns = {k: {'inputs': c, 'contributions': {name: (c[name] - np.mean([cov[season][t][name] for t in means])) * beta[j]
        for j, name in enumerate(COLS)} if k in means else None} for k, c in cov[season].items()}
    return {'schema': 'cfb-forecast-prior-v7', 'model': config.model, 'season': season, 'previous_season': season-1,
        'training_seasons': years, 'sd': s, 'mean_by_id': means, 'fcs_mean_by_id': fm, 'fcs_sd': fs,
        'fcs_gap': previous['mu_fcs'], 'tau_fbs': previous['tau_fbs'], 'tau_fcs': previous['tau_fcs'], 'sigma': previous['sigma'],
        'coefficients': dict(zip(COLS + ('home',), map(float, beta))), 'level_shift': shift,
        'v2_coefficients': dict(zip(('intercept', 'prev', 'talent_z', 'ap'), map(float, beta2))),
        'training_games': len(X), 'v2_training_teams': len(train2), 'fcs_slope': float(slope), 'fcs_pairs': len(pairs),
        'prior_average': float(np.mean(list(means.values()))), 'team_inputs': columns,
        'caveat': bundle['caveats'].get(str(season), ''), 'source_hashes': bundle['source_hashes'], 'config': config.identity()}
