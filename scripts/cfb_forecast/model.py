"""Predictive model from the frozen forecasting handoff (weekly drift and FCS priors); never used for merit.

The prior means are frozen before weekly fitting. Home-field covariance comes
from exactly three preceding seasons. No ranking policy or reference team enters.
"""
import math
from .config import CONFIG

SAMPLING_ATTEMPTS = ((2000, 2000), (4000, 4000))


def efficiency_target(margin, expectancy, config=CONFIG):
    import numpy as np
    y = np.asarray(margin, float)
    p = np.asarray([np.nan if x is None else x for x in expectancy], float)
    ok = np.isfinite(p)
    if np.any((p[ok] < 0) | (p[ok] > 1)):
        raise ValueError('Postgame expectancy must be a probability')
    logits = np.log(np.clip(p[ok], .001, .999) / (1 - np.clip(p[ok], .001, .999)))
    # Frozen production rule: sparse early-season expectancy falls back to 4.5.
    scale = float(np.polyfit(logits, y[ok], 1)[0]) if len(logits) > 30 and np.ptp(logits) > 0 else 4.5
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid training-only efficiency scale')
    eff = y.copy(); eff[ok] = scale * logits
    return config.margin_weight * y + (1 - config.margin_weight) * eff, scale, int(ok.sum())


def forecast_model(n_teams, home, away, venue, margin, host, home_prior, structure,
                   has_prior, prior_mean, prior_sd, fcs_mean, fcs_prior=None, fcs_sd=5.,
                   week=None, n_weeks=1, config=CONFIG, qbx=None):
    # Execute the supplied model. This adapter only maps the saved-data schema;
    # priors, likelihood, latent structure and parameter names live in reference/.
    import jax.numpy as jnp
    from .reference.forecast_model import forecast_model as supplied_model
    return supplied_model(hi=home, ai=away, site=venue, host_idx=host,
        grp=jnp.asarray(structure['division']), n_teams=n_teams, n_groups=2,
        hmu=home_prior[0], hL=home_prior[1], cl=jnp.asarray(structure['conference']),
        n_clusters=len(structure['conference_labels']), has_prev=has_prior,
        prev_mean=prior_mean, s_prev=prior_sd, fcs_mu=fcs_mean, fcs_sd=5.,
        w=jnp.ones(len(home)), y=margin, learn_s=True, wk=week, n_weeks=n_weeks,
        dynamic=n_weeks > 1, q_scale=config.drift_sd, conf_scale=None,
        fcs_prior=fcs_prior, fcs_s=fcs_sd, qbx=qbx)


def fit(inputs, prior, home_prior, gap, target, *, seed, warmup, draws, target_accept=None):
    import jax
    import jax.numpy as jnp
    from numpyro.infer import MCMC, NUTS, init_to_value
    jax.config.update('jax_enable_x64', True)
    means = prior['mean_by_id']; fm = prior['fcs_mean_by_id']
    has = [str(t['id']) in means and t['classification'] == 'fbs' for t in inputs['teams']]
    fcs = [str(t['id']) in fm and t['classification'] == 'fcs' for t in inputs['teams']]
    pm = [(fm if is_fcs else means).get(str(t['id']), 0.) for t, is_fcs in zip(inputs['teams'], fcs)]
    has = [h or f for h, f in zip(has, fcs)]
    n_weeks = max(g['week'] for g in inputs['games'])
    # A longer recovery attempt also takes smaller steps; the posterior model
    # and publication thresholds are unchanged.
    if target_accept is None: target_accept = .99 if warmup > 2000 else .97
    if not 0 < target_accept < 1: raise ValueError('Target acceptance must be between zero and one')
    sampler = MCMC(NUTS(forecast_model, target_accept_prob=target_accept, max_tree_depth=10,
        init_strategy=init_to_value(values={'mu_free': jnp.array([gap]), 'tau': jnp.array([10., 10.]), 'tau_conf': 5.})),
        num_warmup=warmup, num_samples=draws, num_chains=4, chain_method='sequential', progress_bar=False)
    data = {k: jnp.asarray(v) for k, v in inputs['data'].items()}; data['margin'] = jnp.asarray(target)
    sampler.run(jax.random.PRNGKey(seed), len(inputs['teams']), **data,
        home_prior=(jnp.asarray(home_prior['mean']), jnp.asarray(home_prior['chol'])),
        structure=inputs['strength_structure'], has_prior=jnp.asarray(has), prior_mean=jnp.asarray(pm),
        prior_sd=prior['sd'], fcs_mean=gap, fcs_prior=jnp.asarray(fcs), fcs_sd=prior['fcs_sd'],
        week=jnp.asarray([max(g['week']-1, 0) for g in inputs['games']]), n_weeks=n_weeks,
        qbx=jnp.asarray(inputs['qbx']) if 'qbx' in inputs else None,
        extra_fields=('energy', 'num_steps', 'accept_prob', 'potential_energy', 'adapt_state.step_size'))
    sampler.forecast_target_accept = target_accept
    return sampler


def diagnose(sampler):
    import arviz as az
    import numpy as np
    samples = {k: np.asarray(v) for k, v in sampler.get_samples(group_by_chain=True).items()}
    # Week 1 walk is identically zero; omit that deterministic coordinate only.
    checked = {k: (v[..., 1:] if k == 'walk' else v) for k, v in samples.items()}
    idata = az.from_dict(posterior=checked)
    def values(fn, **kw): return np.concatenate([np.asarray(v).ravel() for v in fn(idata, **kw).data_vars.values()])
    rhat, bulk, tail = values(az.rhat, method='rank'), values(az.ess, method='bulk'), values(az.ess, method='tail')
    extra = sampler.get_extra_fields(group_by_chain=True)
    energy = np.asarray(extra['energy']); bfmi = np.mean(np.diff(energy, axis=1)**2, axis=1) / energy.var(axis=1)
    d = {'max_rank_normalized_rhat': float(rhat.max()), 'min_bulk_ess': float(bulk.min()),
         'min_tail_ess': float(tail.min()), 'divergences': int(np.asarray(extra['diverging']).sum()),
         'target_accept_prob': getattr(sampler, 'forecast_target_accept', None),
         'tree_depth_limit_hits': int((np.asarray(extra['num_steps']) >= 1023).sum()), 'bfmi_by_chain': bfmi.tolist()}
    d['sampling_checks_passed'] = bool(all(np.isfinite(v).all() for v in (rhat, bulk, tail, bfmi))
        and rhat.max() <= 1.01 and min(bulk.min(), tail.min()) >= 400 and bfmi.min() >= .3
        and d['divergences'] == d['tree_depth_limit_hits'] == 0)
    d.update(transition_details(samples, extra))
    # Diagnostics include all stochastic parameters. Persist only arrays needed
    # for prediction; duplicated latent/deterministic paths waste task storage.
    keep = ('theta', 'theta_last', 'walk', 'q', 'home_values', 'sigma', 'nu', 's_prev', 'lam')
    saved = {k: v for k, v in samples.items() if k in keep}
    import jax
    jax.clear_caches()
    return saved, d, {}


def transition_details(samples, extra):
    """Small diagnostic record, including failed fits; never discard divergence flags.

    NumPyro's retained state can precede a rejected divergent proposal. These
    contexts locate warning transitions; they are not the exploding trajectory.
    """
    import numpy as np
    flags = np.asarray(extra['diverging'], bool)
    report = {'divergences_by_chain': flags.sum(axis=1).tolist(),
        'divergent_transitions': [{'chain': int(c)+1, 'draw': int(i)+1} for c,i in np.argwhere(flags)[:50]],
        'divergence_context': {}}
    for key, field in [('acceptance_by_chain','accept_prob'), ('step_size_by_chain','adapt_state.step_size')]:
        if field in extra: report[key] = np.asarray(extra[field]).mean(axis=1).tolist()
    if flags.any():
        for name in ('mu_free','tau','tau_conf','s_prev','q','eta_sigma','eta_nu'):
            if name not in samples: continue
            a = np.asarray(samples[name]); flat = a.reshape((-1,)+a.shape[2:])
            report['divergence_context'][name] = {'all_q05_q50_q95': np.quantile(flat,[.05,.5,.95],axis=0).tolist(),
                'flagged_states': a[flags][:50].tolist()}
    return report


def prediction_arrays(samples, inputs, target):
    import numpy as np
    flat = {k: v.reshape((-1,) + v.shape[2:]) for k, v in samples.items()}
    data = inputs['data']; host = np.asarray(data['host'])
    weeks = np.array([max(g['week']-1, 0) for g in inputs['games']])
    hv = flat.get('home_values', flat.get('home_effect')).mean(0)
    path = flat['theta'][:, :, None] + flat.get('walk', np.zeros((len(flat['theta']), len(inputs['teams']), 1)))
    trajectory = path.mean(0)
    loc = trajectory[data['home'], weeks] - trajectory[data['away'], weeks]
    loc += np.asarray(data['venue']) * (hv[0] + np.where(host > 0, hv[host], 0.))
    if 'lam' in flat: loc += flat['lam'].mean() * np.asarray(inputs['qbx'])
    denom = np.mean((target - loc)**2)
    factor = np.sqrt(np.mean((np.asarray(data['margin']) - loc)**2) / denom) if denom > 0 else np.nan
    if not np.isfinite(factor) or factor <= 0: raise ValueError('Invalid predictive residual rescaling')
    last = flat.get('theta_last', flat['theta'])
    q = flat.get('q', np.zeros(len(last)))
    # One stored innovation per team/draw supports every horizon in the browser.
    # Scaling by sqrt(weeks ahead) preserves the random-walk marginal variance.
    z = np.random.default_rng(CONFIG.seed).standard_normal(last.shape)
    return {'theta': last + q[:, None] * z, 'theta_last': last, 'drift': q[:, None] * z,
            'q': q, **({'lam': flat['lam']} if 'lam' in flat else {}), 'trajectory_mean': trajectory, 'trajectory_sd': path.std(0),
            'home_values': flat.get('home_values', flat.get('home_effect')), 'sigma': flat['sigma'] * factor, 'nu': flat['nu']}, float(factor)


def prior_arrays(inputs, prior, home, n=4000):
    """Week-1 Gaussian approximation from the frozen prior, with no current fit."""
    import numpy as np
    rng = np.random.default_rng(CONFIG.seed); th = []; means=[]; variances=[]
    for t in inputs['teams']:
        key = str(t['id']); fbs = t['classification'] == 'fbs'
        if fbs:
            m = prior['mean_by_id'].get(key, 0.)
            sd = prior['sd'] if key in prior['mean_by_id'] else prior['tau_fbs']
        else:
            m = prior['fcs_gap'] + prior['fcs_mean_by_id'].get(key, 0.)
            sd = np.sqrt((prior['fcs_sd'] if key in prior['fcs_mean_by_id'] else prior['tau_fcs'])**2 + 25.)
        th.append(rng.normal(m, sd, n));means.append(m);variances.append(sd**2)
    return {'theta': np.array(th).T, 'home_values': np.array(home['mean']) + rng.standard_normal((n,len(home['mean']))) @ np.array(home['chol']).T,
            'sigma': np.full(n,prior['sigma']), 'nu': np.full(n,1e7),
            'gaussian_mean':np.array(means), 'gaussian_var':np.array(variances),
            'gaussian_home_mean':np.array(home['mean']), 'gaussian_home_cov':np.array(home['chol'])@np.array(home['chol']).T,
            'gaussian_sigma':prior['sigma']}
