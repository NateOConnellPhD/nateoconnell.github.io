"""V6 historical home prior: robust Student-t MAP and IRLS Gaussian covariance.

Adapted from the supplied V6 historical_home.py, using verified CFBD IDs and
season rosters instead of name aliases or appearance-count membership. This is
an approximate historical posterior, not historical HMC or an exact Hessian.
Only the national/host block transfers into the current season.
"""
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from sync_data import digest, encoded


@dataclass(frozen=True)
class HomeSpecification:
    version: str = 'rolling-three-season-home-v6'
    theta_sd: float = 14.0
    global_mean: float = 2.0
    global_sd: float = 2.5
    host_sd: float = 2.0
    sigma: float = 14.0
    nu: float = 12.0
    drift_global_sd: float = 0.25
    drift_host_sd: float = 0.75


CANONICAL = HomeSpecification()


def design(games):
    import numpy as np
    from scipy.sparse import coo_matrix
    strengths = sorted({(g['season'], g[side]) for g in games for side in ('home_id', 'away_id')})
    hosts = sorted({g[side] for g in games for side in ('home_id', 'away_id')})
    ti = {team: i for i, team in enumerate(strengths)}
    hi = {team: len(strengths) + 1 + i for i, team in enumerate(hosts)}
    rows, cols, values = [], [], []
    for i, game in enumerate(games):
        rows.extend((i, i)); values.extend((1., -1.))
        cols.extend((ti[(game['season'], game['home_id'])], ti[(game['season'], game['away_id'])]))
        if game['venue']:
            rows.extend((i, i)); values.extend((1., 1.)); cols.extend((len(strengths), hi[game['home_id']]))
    matrix = coo_matrix((values, (rows, cols)), shape=(len(games), len(strengths)+1+len(hosts))).tocsr()
    return matrix, strengths, hosts


def estimate(history, fbs_ids, specification=CANONICAL):
    import numpy as np
    from scipy.sparse import diags
    from scipy.sparse.linalg import spsolve, splu
    s = specification
    X, strengths, hosts = design(history['games'])
    ntheta = len(strengths)
    mean = np.r_[np.zeros(ntheta), s.global_mean, np.zeros(len(hosts))]
    sd = np.r_[np.full(ntheta, s.theta_sd), s.global_sd, np.full(len(hosts), s.host_sd)]
    precision = (s.sigma / sd)**2
    y = np.asarray([g['margin'] for g in history['games']], float)
    b = mean.copy()
    converged = False
    for iteration in range(80):
        residual = y - X @ b
        weight = (s.nu+1) / (s.nu + (residual/s.sigma)**2)
        H = (X.T @ diags(weight) @ X + diags(precision)).tocsc()
        new = spsolve(H, np.asarray(X.T @ (weight*y)).ravel() + precision*mean)
        if not np.isfinite(new).all():
            raise ValueError('Historical home fit is nonfinite')
        delta = float(np.max(abs(new-b)))
        b = new
        if delta < 1e-8:
            converged = True
            break
    if not converged:
        raise ValueError('Historical home fit did not converge; no prior was saved')
    residual = y-X@b
    weight = (s.nu+1) / (s.nu + (residual/s.sigma)**2)
    H = (X.T @ diags(weight) @ X + diags(precision)).tocsc()
    block = np.arange(ntheta, len(mean))
    E = np.zeros((len(mean), len(block)))
    E[block, np.arange(len(block))] = 1
    covariance = s.sigma**2 * splu(H).solve(E)[block, :]
    covariance = (covariance + covariance.T)/2
    minimum = float(np.linalg.eigvalsh(covariance).min())
    if not np.isfinite(covariance).all() or minimum < -1e-7:
        raise ValueError('Historical home covariance is not positive semidefinite')
    covariance += np.eye(len(block))*max(1e-9, -minimum+1e-9)
    means = b[block]
    old = {team: i+1 for i, team in enumerate(hosts)}
    source_indices = [0] + [old.get(team) for team in fbs_ids]
    mu = np.zeros(1+len(fbs_ids)); C = np.zeros((len(mu), len(mu)))
    for i, source in enumerate(source_indices):
        if source is None:
            C[i, i] = s.host_sd**2
            continue
        mu[i] = means[source]
        for j, other in enumerate(source_indices):
            if other is not None: C[i, j] = covariance[source, other]
    C[0, 0] += s.drift_global_sd**2
    C[1:, 1:] += np.eye(len(fbs_ids))*s.drift_host_sd**2
    C = (C+C.T)/2 + np.eye(len(mu))*1e-8
    L = np.linalg.cholesky(C)
    return {'fbs_ids': fbs_ids, 'years': history['years'], 'mean': mu.tolist(), 'chol': L.tolist(),
            'covariance': C.tolist(), 'history_input_sha256': history['input_sha256'],
            'specification': asdict(s), 'diagnostics': {'converged': True, 'iterations': iteration+1,
                'games': len(y), 'historical_team_season_parameters': ntheta,
                'historical_global_mean': float(means[0]), 'historical_global_sd': float(covariance[0,0]**.5),
                'new_fbs_host_ids': [team for team in fbs_ids if team not in old],
                'approximation': 'Robust Student-t MAP with IRLS Gaussian home-block covariance; historical strengths marginalized, not transferred.'}}


def validate(prior, season, fbs_ids, history_hash):
    import numpy as np
    from home_history_inputs import years_for
    if (prior['years'] != years_for(season) or prior['fbs_ids'] != fbs_ids
            or prior['history_input_sha256'] != history_hash or not prior['diagnostics']['converged']):
        raise ValueError('Historical home prior does not match the exact three-season window and roster')
    n = 1+len(fbs_ids)
    mu, L, C = (np.asarray(prior[k], float) for k in ('mean','chol','covariance'))
    if mu.shape != (n,) or L.shape != (n,n) or C.shape != (n,n):
        raise ValueError('Historical home prior dimensions disagree with the roster')
    if (not all(np.isfinite(a).all() for a in (mu,L,C)) or np.any(np.diag(L)<=0)
            or not np.array_equal(L, np.tril(L)) or not np.allclose(L@L.T,C,rtol=1e-9,atol=1e-9)):
        raise ValueError('Historical home prior covariance is invalid')


def load_or_estimate(inputs, cache):
    history = inputs['home_history']
    ids = [inputs['teams'][i]['id'] for i in inputs['fbs_indices']]
    identity = {'history_input_sha256': history['input_sha256'], 'fbs_ids': ids,
                'specification': asdict(CANONICAL), 'source_sha256': digest(Path(__file__).read_text())}
    path = Path(cache) / (digest(identity)+'.json')
    if path.exists():
        saved = json.loads(path.read_text())
        prior = saved['prior']
        if saved['identity'] != identity or saved['prior_sha256'] != digest(prior):
            raise ValueError('Cached historical home prior failed its identity/integrity check')
    else:
        prior = estimate(history, ids)
        validate(prior, inputs['season'], ids, history['input_sha256'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded({'identity': identity, 'prior': prior, 'prior_sha256': digest(prior)}))
    validate(prior, inputs['season'], ids, history['input_sha256'])
    return prior
