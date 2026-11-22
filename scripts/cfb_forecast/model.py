"""Predictive model from the November 22 forecast handoff; never used for merit.

The prior means are frozen before weekly fitting. Home-field covariance comes
from exactly three preceding seasons. No ranking policy or reference team enters.
"""
import math


def efficiency_target(margin, expectancy):
    import numpy as np
    y = np.asarray(margin, float)
    p = np.asarray([np.nan if x is None else x for x in expectancy], float)
    ok = np.isfinite(p)
    if np.any((p[ok] < 0) | (p[ok] > 1)):
        raise ValueError('Postgame expectancy must be a probability')
    logits = np.log(np.clip(p[ok], .001, .999) / (1 - np.clip(p[ok], .001, .999)))
    if len(logits) < 3 or np.ptp(logits) == 0:
        raise ValueError('Too little postgame expectancy information for the efficiency blend')
    scale = float(np.polyfit(logits, y[ok], 1)[0])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid training-only efficiency scale')
    eff = y.copy(); eff[ok] = scale * logits
    return .75 * y + .25 * eff, scale, int(ok.sum())


def previous_division_gap(games, fbs_ids):
    """The handoff's Gaussian empirical Bayes prior, from last season only.

    Includes completed FBS-involving games, including bowls; never current data.
    This estimates the FCS gap, not current power ratings or merit.
    """
    import numpy as np
    from scipy.linalg import cho_factor, cho_solve
    from scipy.optimize import minimize
    teams = sorted({g[k] for g in games for k in ('homeId', 'awayId')})
    ix = {t: i for i, t in enumerate(teams)}
    isf = np.array([t in fbs_ids for t in teams])
    n, k = len(games), len(teams)
    if n < 100 or isf.all() or not isf.any():
        raise ValueError('Previous-season FBS/FCS evidence is incomplete')
    X = np.zeros((n, k))
    for j, g in enumerate(games): X[j, ix[g['homeId']]], X[j, ix[g['awayId']]] = 1., -1.
    site = np.array([not g['neutralSite'] for g in games], float)
    y = np.array([g['homePoints'] - g['awayPoints'] for g in games], float)
    F = np.column_stack([X @ (~isf).astype(float), site])
    def objective(par):
        s, tf, tc = np.exp(par)
        C = (X * np.where(isf, tf * tf, tc * tc)) @ X.T + 1e4 * F @ F.T + s * s * np.eye(n)
        factor = cho_factor(C, lower=True)
        return np.log(np.diag(factor[0])).sum() + .5 * y @ cho_solve(factor, y)
    opt = minimize(objective, np.log([15., 12., 12.]), method='Nelder-Mead',
                   options={'xatol': 1e-4, 'fatol': 1e-4})
    if not opt.success or not np.isfinite(opt.fun): raise ValueError('Previous-season gap fit did not converge')
    s, tf, tc = np.exp(opt.x)
    Z = np.column_stack([X, F])
    P = Z.T @ Z / s**2 + np.diag(np.r_[1 / np.where(isf, tf**2, tc**2), 1e-4, 1e-4])
    mean = np.linalg.solve(P, Z.T @ y / s**2)
    return float(mean[k])


def forecast_model(n_teams, home, away, venue, margin, host, home_prior, structure,
                   has_prior, prior_mean, prior_sd, fcs_mean):
    import jax.numpy as jnp
    import numpyro as nr
    import numpyro.distributions as d
    division = jnp.asarray(structure['division'])
    conf = jnp.asarray(structure['conference'])
    z = nr.sample('theta_z', d.Normal(0., 1.).expand((n_teams,)).to_event(1))
    mu = nr.sample('mu_fcs', d.Normal(fcs_mean, 5.))
    tau = nr.sample('tau_division', d.HalfNormal(30.).expand((2,)).to_event(1))
    tc = nr.sample('tau_conf', d.ImproperUniform(d.constraints.positive, (), ()))
    cz = nr.sample('conference_z', d.Normal(0., 1.).expand((len(structure['conference_labels']),)).to_event(1))
    gamma = nr.deterministic('conference_effect', tc * cz)
    s = nr.sample('s_prev', d.LogNormal(jnp.log(prior_sd), .35))
    theta = nr.deterministic('theta', jnp.where(division == 0, 0., mu) + gamma[conf]
        + has_prior * prior_mean + jnp.where(has_prior, s, tau[division]) * z)
    hm, hL = home_prior
    hz = nr.sample('home_z', d.Normal(0., 1.).expand((len(hm),)).to_event(1))
    hv = nr.deterministic('home_effect', hm + hL @ hz)
    nr.deterministic('home_adv', hv[0])
    sigma = nr.deterministic('sigma', 8. + jnp.exp(nr.sample('eta_sigma', d.Normal(jnp.log(6.), .75))))
    nu = nr.deterministic('nu', 2. + jnp.exp(nr.sample('eta_nu', d.Normal(jnp.log(5.), .9))))
    loc = theta[home] - theta[away] + venue * (hv[0] + jnp.where(host > 0, hv[host], 0.))
    with nr.plate('games', len(home)): nr.sample('margin', d.StudentT(nu, loc, sigma), obs=margin)


def fit(inputs, prior, home_prior, gap, target, *, seed, warmup, draws):
    import jax
    import jax.numpy as jnp
    from numpyro.infer import MCMC, NUTS, init_to_value
    jax.config.update('jax_enable_x64', True)
    means = prior['mean_by_id']
    has = [str(t['id']) in means and t['classification'] == 'fbs' for t in inputs['teams']]
    pm = [means.get(str(t['id']), 0.) for t in inputs['teams']]
    sampler = MCMC(NUTS(forecast_model, target_accept_prob=.9, max_tree_depth=10,
        init_strategy=init_to_value(values={'mu_fcs': gap, 'tau_division': jnp.array([10., 10.]), 'tau_conf': 5.})),
        num_warmup=warmup, num_samples=draws, num_chains=4, chain_method='sequential', progress_bar=False)
    data = {k: jnp.asarray(v) for k, v in inputs['data'].items()}; data['margin'] = jnp.asarray(target)
    sampler.run(jax.random.PRNGKey(seed), len(inputs['teams']), **data,
        home_prior=(jnp.asarray(home_prior['mean']), jnp.asarray(home_prior['chol'])),
        structure=inputs['strength_structure'], has_prior=jnp.asarray(has), prior_mean=jnp.asarray(pm),
        prior_sd=prior['sd'], fcs_mean=gap, extra_fields=('energy', 'num_steps'))
    return sampler


def diagnose(sampler):
    import arviz as az
    import numpy as np
    samples = {k: np.asarray(v) for k, v in sampler.get_samples(group_by_chain=True).items()}
    idata = az.from_dict(posterior=samples)
    def values(fn, **kw): return np.concatenate([np.asarray(v).ravel() for v in fn(idata, **kw).data_vars.values()])
    rhat, bulk, tail = values(az.rhat, method='rank'), values(az.ess, method='bulk'), values(az.ess, method='tail')
    extra = sampler.get_extra_fields(group_by_chain=True)
    energy = np.asarray(extra['energy']); bfmi = np.mean(np.diff(energy, axis=1)**2, axis=1) / energy.var(axis=1)
    d = {'max_rank_normalized_rhat': float(rhat.max()), 'min_bulk_ess': float(bulk.min()),
         'min_tail_ess': float(tail.min()), 'divergences': int(np.asarray(extra['diverging']).sum()),
         'tree_depth_limit_hits': int((np.asarray(extra['num_steps']) >= 1023).sum()), 'bfmi_by_chain': bfmi.tolist()}
    d['sampling_checks_passed'] = bool(all(np.isfinite(v).all() for v in (rhat, bulk, tail, bfmi))
        and rhat.max() <= 1.01 and min(bulk.min(), tail.min()) >= 400 and bfmi.min() >= .3
        and d['divergences'] == d['tree_depth_limit_hits'] == 0)
    return samples, d, {}


def prediction_arrays(samples, inputs, target):
    import numpy as np
    flat = {k: v.reshape((-1,) + v.shape[2:]) for k, v in samples.items()}
    data = inputs['data']; host = np.asarray(data['host'])
    hv = flat['home_effect'].mean(0)
    loc = flat['theta'].mean(0)[data['home']] - flat['theta'].mean(0)[data['away']]
    loc += np.asarray(data['venue']) * (hv[0] + np.where(host > 0, hv[host], 0.))
    denom = np.mean((target - loc)**2)
    factor = np.sqrt(np.mean((np.asarray(data['margin']) - loc)**2) / denom) if denom > 0 else np.nan
    if not np.isfinite(factor) or factor <= 0: raise ValueError('Invalid predictive residual rescaling')
    return {'theta': flat['theta'], 'home_values': flat['home_effect'], 'sigma': flat['sigma'] * factor,
            'nu': flat['nu']}, float(factor)
