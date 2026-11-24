"""Conditional final-score extension; the supplied margin posterior is unchanged.

Model the lower of the two scores given the absolute margin, with a normal
likelihood truncated below zero. School-season and season effects are pooled
with proper Gaussian priors. Inference is a checked Laplace approximation,
not a second HMC fit. See docs/CFB-SCORE-PREDICTIONS.md for the specification.
"""
import hashlib
import json
import math
from pathlib import Path

from sync_data import DATA, digest

VERSION = 'conditional-scores-1'
SEED = 20261123


def load_rows(inputs, root=DATA):
    """Use only validated historical IDs and the already cutoff-filtered games.

    Home-history records omit the separate scores. Recover them from the same
    saved provider response, never from a fresh request or an unfiltered season.
    """
    season = inputs['season']
    history = inputs['home_history']
    if history['years'] != list(range(season - 3, season)):
        raise ValueError('Score history must precede the forecast by exactly three seasons')
    sources = {}
    for year in history['years']:
        raw = json.loads((Path(root) / str(year) / 'games.json').read_text())['payload']
        sources[year] = {g['id']: g for g in raw}
    rows = []
    for g in history['games']:
        raw = sources[g['season']][g['id']]
        if (raw['homeId'] != g['home_id'] or raw['awayId'] != g['away_id'] or
                raw['homePoints'] - raw['awayPoints'] != g['margin']):
            raise ValueError('Historical score source disagrees with validated game')
        rows.append({'season': g['season'], 'id': g['id'], 'home': str(g['home_id']),
                     'away': str(g['away_id']), 'hp': raw['homePoints'], 'ap': raw['awayPoints']})
    rows.extend({'season': season, 'id': g['id'], 'home': str(g['home_id']),
                 'away': str(g['away_id']), 'hp': g['home_points'], 'ap': g['away_points']}
                for g in inputs['games'])
    validate_rows(rows, season)
    return sorted(rows, key=lambda r: (r['season'], r['id']))


def validate_rows(rows, season):
    seen = set()
    for r in rows:
        key = (r['season'], r['id'])
        if (key in seen or not season - 3 <= r['season'] <= season or r['home'] == r['away'] or
                any(type(r[k]) not in (int, float) or not math.isfinite(r[k]) or
                    r[k] < 0 or int(r[k]) != r[k] for k in ('hp', 'ap'))):
            raise ValueError('Invalid or duplicate score training game')
        seen.add(key)
    if not rows:
        raise ValueError('No validated scores available')


def design(rows, season, team_ids):
    import numpy as np
    from scipy.sparse import csr_matrix
    years = sorted({r['season'] for r in rows} | {season})
    pairs = sorted({(r['season'], t) for r in rows for t in (r['home'], r['away'])} |
                   {(season, t) for t in team_ids})
    si = {year: i + 2 for i, year in enumerate(years)}
    ti = {pair: i + 2 + len(years) for i, pair in enumerate(pairs)}
    p = 2 + len(years) + len(pairs)
    rr, cc, vv = [], [], []
    for i, r in enumerate(rows):
        cols = [0, 1, si[r['season']], ti[r['season'], r['home']], ti[r['season'], r['away']]]
        rr.extend([i] * 5); cc.extend(cols)
        vv.extend([1., (abs(r['hp'] - r['ap']) - 14.) / 14., 1., 1., 1.])
    x = csr_matrix((vv, (rr, cc)), shape=(len(rows), p))
    y = np.array([min(r['hp'], r['ap']) for r in rows], dtype=float)
    center = np.zeros(p + 1); center[:2] = [20., -3.]; center[-1] = np.log(10.)
    sd = np.r_[10., 6., np.full(len(years), 3.), np.full(len(pairs), 5.), .5]
    # Keep covariance among the global terms, this season, and its schools.
    keep = [0, 1, p, si[season]] + [ti[season, t] for t in team_ids]
    return x, y, center, sd ** -2, keep


def objective(value, x, y, center, precision, hessian=False):
    import numpy as np
    from scipy.special import log_ndtr
    mu = x @ value[:-1]; scale = np.exp(value[-1])
    a = mu / scale; z = (y - mu) / scale
    log_cdf = log_ndtr(a)
    mills = np.exp(-.5 * a * a - .5 * np.log(2 * np.pi) - log_cdf)
    delta = value - center
    loss = np.sum(value[-1] + .5 * z * z + log_cdf) + .5 * np.dot(delta * precision, delta)
    gradient = np.r_[x.T @ ((-z + mills) / scale), np.sum(1 - z * z - a * mills)] + precision * delta
    if not hessian:
        return loss, gradient
    d = mills * (a + mills)
    matrix = np.zeros((len(value), len(value)))
    matrix[:-1, :-1] = (x.T @ x.multiply(((1 - d) / scale ** 2)[:, None])).toarray()
    cross = x.T @ ((2 * z - mills + a * d) / scale)
    matrix[:-1, -1] = cross; matrix[-1, :-1] = cross
    matrix[-1, -1] = np.sum(2 * z * z + a * mills - a * a * d)
    matrix.flat[::len(value) + 1] += precision
    return matrix


def fit(rows, season, team_ids):
    import numpy as np
    from scipy.linalg import cholesky, cho_solve, solve_triangular
    from scipy.optimize import minimize
    validate_rows(rows, season)
    if len(set(team_ids)) != len(team_ids) or not team_ids:
        raise ValueError('Invalid score forecast roster')
    x, y, center, precision, keep = design(rows, season, team_ids)
    result = minimize(objective, center, args=(x, y, center, precision), jac=True,
                      method='L-BFGS-B', options={'maxiter': 2000, 'ftol': 1e-13, 'gtol': 1e-6, 'maxls': 40})
    # Relative objective convergence can precede gradient convergence in a
    # large dataset. Polish the same posterior mode; never relax the gate.
    refinements = 0
    if result.success:
        for _ in range(6):
            if np.max(np.abs(result.jac)) < 1e-5: break
            curvature = objective(result.x, x, y, center, precision, hessian=True)
            step = cho_solve((cholesky(curvature, lower=True), True), result.jac)
            for exponent in range(16):
                amount = .5 ** exponent
                candidate = result.x - amount * step
                loss, grad = objective(candidate, x, y, center, precision)
                if loss <= result.fun - .0001 * amount * np.dot(result.jac, step) + 1e-10:
                    result.x, result.fun, result.jac = candidate, loss, grad
                    refinements += 1
                    break
            else: break
    gradient = float(np.max(np.abs(result.jac)))
    if not result.success or not np.isfinite(result.fun) or gradient > .001:
        raise ValueError(f'Score model optimization failed: {result.message}; gradient={gradient:.6g}')
    hessian = objective(result.x, x, y, center, precision, hessian=True)
    # No diagonal jitter: a non-positive Hessian is a failed approximation.
    factor = cholesky(hessian, lower=True)
    columns = np.eye(len(result.x))[:, keep]
    solved = solve_triangular(factor, columns, lower=True)
    covariance = solved.T @ solved
    cholesky(covariance, lower=True)
    if not np.isfinite(covariance).all():
        raise ValueError('Non-finite score posterior covariance')
    return {'version': VERSION, 'teams': team_ids, 'mean': result.x[keep].tolist(),
            'covariance': covariance.tolist(), 'report': {
                'method': 'Laplace approximation with fixed pooling priors', 'games': len(rows),
                'season_games': sum(r['season'] == season for r in rows),
                'training_seasons': sorted({r['season'] for r in rows}),
                'max_gradient': gradient, 'positive_definite_hessian': True,
                'iterations': int(result.nit), 'mode_refinements': refinements,
                'residual_scale_mode': float(np.exp(result.x[-1])),
                'checks_passed': True}}


def load_or_fit(rows, season, team_ids, cache):
    from importlib.metadata import version
    key = digest({'rows': rows, 'season': season, 'teams': team_ids, 'version': VERSION,
                  'source': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'packages': {p: version(p) for p in ('numpy', 'scipy')}})
    path = Path(cache) / (key + '.json')
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get('key') == key and saved['fit']['report'].get('checks_passed'):
            return saved['fit'], key, True
    fitted = fit(rows, season, team_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'key': key, 'fit': fitted}, allow_nan=False))
    # Only this module's disposable fit cache, after the replacement passes.
    for old in path.parent.glob('*.json'):
        if old != path: old.unlink()
    return fitted, key, False


def browser_draws(fitted, count):
    import numpy as np
    from scipy.linalg import cholesky
    rng = np.random.default_rng(SEED)
    values = rng.normal(size=(count, len(fitted['mean']))) @ cholesky(fitted['covariance'], lower=True).T + fitted['mean']
    rnd = lambda v: np.round(v, 7).tolist()
    return {'version': VERSION, 'intercept': rnd(values[:, 0] + values[:, 3]),
            'slope': rnd(values[:, 1]), 'scale': rnd(np.exp(values[:, 2])),
            'teams': {t: rnd(values[:, i + 4]) for i, t in enumerate(fitted['teams'])},
            'uniform': rng.uniform(.000001, .999999, size=(2, count)).tolist()}


def predict(draws, home, away, margins):
    """margins is (posterior draws, 2 noise replicates), before sorting."""
    import numpy as np
    from scipy.special import log_ndtr, ndtri_exp
    margin = np.asarray(margins, float)
    mu = (np.asarray(draws['intercept'])[:, None] + np.asarray(draws['teams'][home])[:, None] +
          np.asarray(draws['teams'][away])[:, None] + np.asarray(draws['slope'])[:, None] * (np.abs(margin) - 14.) / 14.)
    scale = np.asarray(draws['scale'])[:, None]
    # Inverse survival sampling avoids cancellation for strongly negative mu.
    log_survival = log_ndtr(mu / scale) + np.log1p(-np.asarray(draws['uniform']).T)
    lower_score = mu - scale * ndtri_exp(log_survival)
    if not np.isfinite(lower_score).all() or (lower_score < -1e-7).any():
        raise ValueError('Invalid conditional score draws')
    lower_score = np.maximum(lower_score, 0.)  # floating-point roundoff only
    return (lower_score + np.maximum(margin, 0.)).ravel(), (lower_score + np.maximum(-margin, 0.)).ravel()


def attach(public, browser, fitted):
    """One shared score-draw payload supports every game and local QB scenario."""
    import numpy as np
    from .export import summary
    browser['scores'] = browser_draws(fitted, len(browser['sigma']))
    public['meta']['score_model'] = {'version': VERSION, **fitted['report']}
    for g in public['games']:
        h, a = g['home'], g['away']
        if 'last' in browser:
            strength = lambda t: np.asarray(browser['last'][t]) + np.sqrt(g.get('ahead', 1)) * np.asarray(browser['drift'][t])
        else:
            strength = lambda t: np.asarray(browser['teams'][t])
        loc = strength(h) - strength(a)
        if not g['neutral']:
            loc += np.asarray(browser['home']['national']) + np.asarray(browser['home'].get(h, 0.))
        loc += np.asarray(browser.get('lam', 0.)) * (g.get('qb_x_home', 0.) - g.get('qb_x_away', 0.))
        home_scores, away_scores = predict(browser['scores'], h, a, loc[:, None] + np.asarray(browser['noise']).T)
        g['scores'] = {'home': summary(home_scores), 'away': summary(away_scores)}
