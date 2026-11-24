"""Margin of Merit strength model used as a power rating and spread forecaster (research module).

The merit pipeline is unchanged. This module reuses its strength model for forecasting and adds an optional
preseason prior built from the previous season:

    V0 (merit strength model):  theta_i = mu_div + gamma_conf + tau_div * z_i      (flat hyperpriors, no preseason info)
    V1 (preseason prior):       theta_i = mu_div + gamma_conf + m_i + s * z_i       for FBS teams with a prior mean m_i
                                theta_i = mu_div + gamma_conf + tau_div * z_i       for everyone else
                                mu_FCS ~ N(last season's FCS gap, 5^2); tau_div ~ HalfNormal(30)

V1: m_i = a + b * last season's rating (`carryover`). V2: m_i from last season's rating, roster talent and AP preseason
points (`preseason_regression`). Coefficients and s come only from seasons before the one being forecast.
Optional time weighting multiplies each game's log-likelihood by 0.5 ** (age_weeks / half_life).

Power rating = posterior mean of theta (points above the average FBS team, neutral field).
Spread = theta_home - theta_away + home effect at that stadium (0 on a neutral field).
"""
import numpy as np
import pandas as pd
import jax
import jax.numpy as jnp
import numpyro
import numpyro.distributions as dist
from numpyro.distributions import constraints
from numpyro.infer import MCMC, NUTS, init_to_value
from scipy import optimize, stats
from scipy.special import logsumexp

jax.config.update('jax_enable_x64', True)


# ----------------------------------------------------------------------------------------------------------------
# Last-season ratings and carryover (fast Gaussian empirical Bayes; used only to build the preseason prior)
# ----------------------------------------------------------------------------------------------------------------
def season_ratings(g, fbs):
    """Gaussian ratings for one season. g: home_team, away_team, home_points, away_points, neutral_site.
    theta_i = mu_div + delta_i, delta_i ~ N(0, tau_div^2), mu_FBS = 0, mu_FCS and home effect flat;
    sigma, tau_FBS, tau_FCS by marginal likelihood. Returns posterior means/variances (FBS mean = 0)."""
    teams = sorted(set(g.home_team) | set(g.away_team)); ix = {t: i for i, t in enumerate(teams)}
    isf = np.array([t in fbs for t in teams]); n, k = len(g), len(teams)
    X = np.zeros((n, k)); X[np.arange(n), g.home_team.map(ix)] = 1; X[np.arange(n), g.away_team.map(ix)] -= 1
    site = (~g.neutral_site.astype(bool)).to_numpy(float); y = (g.home_points - g.away_points).to_numpy(float)
    F = np.c_[X @ (~isf).astype(float), site]                    # flat effects: mu_FCS, home
    big = 1e4

    def cov(par):
        s, tf, tc = np.exp(par)
        d = np.where(isf, tf ** 2, tc ** 2)
        return (X * d) @ X.T + big * F @ F.T + s ** 2 * np.eye(n), d

    def nll(par):
        C, _ = cov(par)
        L = np.linalg.cholesky(C)
        a = np.linalg.solve(L, y)
        return np.log(np.diag(L)).sum() + .5 * a @ a

    par = optimize.minimize(nll, np.log([15., 12., 12.]), method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-4}).x
    s, tf, tc = np.exp(par)
    # posterior of [delta, mu_FCS, h]
    Z = np.c_[X, F]; prior_prec = np.r_[1 / np.where(isf, tf ** 2, tc ** 2), 1 / big, 1 / big]
    P = Z.T @ Z / s ** 2 + np.diag(prior_prec); V = np.linalg.inv(P); m = V @ Z.T @ y / s ** 2
    A = np.c_[np.eye(k), (~isf)[:, None].astype(float), np.zeros((k, 1))]   # theta = delta + mu_FCS * 1{FCS}
    th = A @ m; thv = np.einsum('ij,jk,ik->i', A, V, A)
    return {'teams': teams, 'mean': dict(zip(teams, th)), 'var': dict(zip(teams, thv)), 'fbs': set(t for t in teams if t in fbs),
            'mu_fcs': float(m[k]), 'mu_fcs_sd': float(np.sqrt(V[k, k])), 'home': float(m[k + 1]), 'sigma': float(s),
            'tau_fbs': float(tf), 'tau_fcs': float(tc), 'n_games': n}


def carryover(rating_list):
    """Regress each season's FBS ratings on the previous season's. rating_list: list of (season, ratings) in order.
    Returns slope b (with intercept), residual SD s of TRUE ratings (posterior variance removed), and the pairs."""
    rows = []
    for (s0, r0), (s1, r1) in zip(rating_list[:-1], rating_list[1:]):
        if s1 != s0 + 1:
            continue
        for t in r1['fbs'] & r0['fbs']:
            rows.append((s1, t, r0['mean'][t], r1['mean'][t], r1['var'][t]))
    d = pd.DataFrame(rows, columns=['season', 'team', 'prev', 'cur', 'cur_var'])
    b, a = np.polyfit(d.prev, d.cur, 1)
    resid = d.cur - (a + b * d.prev)
    s = float(np.sqrt(max(resid.var() - d.cur_var.mean(), 1.)))
    return {'b': float(b), 'a': float(a), 's': s, 'n_pairs': len(d), 'seasons': sorted(d.season.unique().tolist())}


# ----------------------------------------------------------------------------------------------------------------
# Forecast model (NUTS)
# ----------------------------------------------------------------------------------------------------------------
def forecast_model(hi, ai, site, host_idx, grp, n_teams, n_groups, hmu, hL, cl, n_clusters,
                   has_prev, prev_mean, s_prev, fcs_mu, fcs_sd, w, y=None, learn_s=False,
                   wk=None, n_weeks=1, dynamic=False, q_scale=1.5, conf_scale=None, fcs_prior=None, fcs_s=5.):
    z = numpyro.sample('z', dist.Normal(0., 1.).expand([n_teams]).to_event(1))
    if fcs_sd > 0:                                            # V1: informative division gap from last season
        mu_free = numpyro.sample('mu_free', dist.Normal(fcs_mu, fcs_sd).expand([n_groups - 1]).to_event(1))
    else:                                                     # V0: flat, as in the merit model
        mu_free = numpyro.sample('mu_free', dist.ImproperUniform(constraints.real, (), (n_groups - 1,)))
    if fcs_sd > 0:                                            # V1: weak proper prior (tau_FBS may have no teams left)
        tau = numpyro.sample('tau', dist.HalfNormal(30.).expand([n_groups]).to_event(1))
    else:
        tau = numpyro.sample('tau', dist.ImproperUniform(constraints.positive, (), (n_groups,)))
    mu = jnp.concatenate([jnp.zeros(1), mu_free])
    wc = numpyro.sample('w', dist.Normal(0., 1.).expand([n_clusters]).to_event(1))
    if conf_scale:                                            # conference shifts beyond the prior: kept modest
        tau_conf = numpyro.sample('tau_conf', dist.HalfNormal(conf_scale))
    else:
        tau_conf = numpyro.sample('tau_conf', dist.ImproperUniform(constraints.positive, (), ()))
    gamma = tau_conf * wc
    if learn_s:                                               # how far teams stray from the preseason prior: learned
        s_prev = numpyro.sample('s_prev', dist.LogNormal(jnp.log(s_prev), .35))
    scale = jnp.where(has_prev, s_prev, tau[grp])
    if fcs_prior is not None:                                 # FCS teams with a team-specific preseason prior: own spread
        scale = jnp.where(fcs_prior, fcs_s, scale)
    theta = numpyro.deterministic('theta', mu[grp] + gamma[cl] + has_prev * prev_mean + scale * z)
    hz = numpyro.sample('home_z', dist.Normal(0., 1.).expand([hmu.shape[0]]).to_event(1))
    hh = numpyro.deterministic('home_values', hmu + hL @ hz)
    sigma = numpyro.deterministic('sigma', 8. + jnp.exp(numpyro.sample('eta_sigma', dist.Normal(jnp.log(6.), .75))))
    nu = numpyro.deterministic('nu', 2. + jnp.exp(numpyro.sample('eta_nu', dist.Normal(jnp.log(5.), .9))))
    if dynamic and n_weeks > 1:                               # strength drifts week to week: a random walk from week 1
        q = numpyro.sample('q', dist.HalfNormal(q_scale))
        zw = numpyro.sample('zw', dist.Normal(0., 1.).expand([n_teams, n_weeks - 1]).to_event(2))
        walk = numpyro.deterministic('walk', jnp.concatenate([jnp.zeros((n_teams, 1)), jnp.cumsum(q * zw, axis=1)], axis=1))
        numpyro.deterministic('theta_last', theta + walk[:, -1])
        loc = theta[hi] + walk[hi, wk] - theta[ai] - walk[ai, wk] + site * (hh[0] + jnp.where(host_idx > 0, hh[host_idx], 0.))
    else:
        loc = theta[hi] - theta[ai] + site * (hh[0] + jnp.where(host_idx > 0, hh[host_idx], 0.))
    numpyro.factor('lik', jnp.sum(w * dist.StudentT(nu, loc, sigma).log_prob(y)))


def prior_from_carryover(prev, carry):
    """V1 preseason prior: a + b * last season's rating for FBS teams rated last season."""
    return {'mean': {t: carry['a'] + carry['b'] * prev['mean'][t] for t in prev['fbs']}, 's': carry['s'],
            'mu_fcs': prev['mu_fcs'], 'tau_fbs': prev['tau_fbs'], 'tau_fcs': prev['tau_fcs'], 'sigma': prev['sigma']}


def preseason_regression(rating_by_season, covariates, season, cols=('prev', 'talent_z', 'ap')):
    """V2 preseason prior: regress each season's FBS ratings on last season's rating, roster talent (z-scored within
    season) and log(1 + AP preseason points), using only seasons before `season` with covariates.
    covariates: DataFrame season, team, talent_z, ap. Returns prior means for `season` and the residual SD of true
    ratings (posterior variance removed)."""
    rows = []
    for s, r in rating_by_season.items():                     # training rows: seasons before `season`
        if s >= season or s - 1 not in rating_by_season:
            continue
        r0 = rating_by_season[s - 1]
        for t in r['fbs']:
            rows.append((s, t, r['mean'][t], r['var'][t], r0['mean'][t] if t in r0['fbs'] else np.nan))
    r0 = rating_by_season[season - 1]                          # forecast rows: this season's FBS teams
    for t in set(covariates.loc[covariates.season == season, 'team']):
        rows.append((season, t, np.nan, np.nan, r0['mean'][t] if t in r0['fbs'] else np.nan))
    d = pd.DataFrame(rows, columns=['season', 'team', 'y', 'yvar', 'prev']).merge(covariates, on=['season', 'team'], how='left')
    cols = list(cols); tr = d[d.season < season].dropna(subset=cols + ['y'])
    X = np.c_[np.ones(len(tr)), tr[cols]]; beta = np.linalg.lstsq(X, tr.y, rcond=None)[0]
    resid = tr.y - X @ beta; s_true = float(np.sqrt(max(resid.var() - tr.yvar.mean(), 1.)))
    te = d[d.season == season].dropna(subset=cols)
    m = dict(zip(te.team, np.c_[np.ones(len(te)), te[cols]] @ beta))
    return {'mean': m, 's': s_true, 'beta': dict(zip(['intercept'] + cols, map(float, beta))), 'n_train': len(tr),
            'train_seasons': sorted(tr.season.unique().tolist())}


def preseason_regression_games(games, covariates, season, cols, max_week=5, sigma_game=None):
    """V3 preseason prior, fitted to game margins rather than to end-of-season ratings (which are pulled toward one
    FBS mean and flatten real gaps such as P4 vs G5). For FBS-vs-FBS regular-season games in weeks 1..max_week of
    seasons before `season`: margin = beta'(x_home - x_away) + h * site + e, by OLS. Prior mean m_i = beta'x_i
    (the caller sets the level). s, the spread of true strength around m_i, comes from the residual variance:
    var(e) = 2 s^2 + sigma_game^2.
    games: season, week, season_type, home_team, away_team, margin, site. covariates: season, team and `cols`."""
    cols = list(cols)
    X = covariates.set_index(['season', 'team'])[cols]
    tr = games[(games.season < season) & (games.season_type == 'regular') & (games.week <= max_week)]
    tr = tr[[(s, h) in X.index and (s, a) in X.index for s, h, a in zip(tr.season, tr.home_team, tr.away_team)]]
    D = X.loc[list(zip(tr.season, tr.home_team))].to_numpy() - X.loc[list(zip(tr.season, tr.away_team))].to_numpy()
    ok = ~np.isnan(D).any(1)
    A = np.c_[D[ok], tr.site.to_numpy(float)[ok]]; yv = tr.margin.to_numpy(float)[ok]
    b = np.linalg.lstsq(A, yv, rcond=None)[0]; resid = yv - A @ b
    sg2 = float(sigma_game) ** 2 if sigma_game else 0.
    s_true = float(np.sqrt(max((resid.var() - sg2) / 2., 4.)))
    te = covariates[covariates.season == season].dropna(subset=cols)
    m = dict(zip(te.team, te[cols].to_numpy() @ b[:-1]))
    return {'mean': m, 's': s_true, 'beta': dict(zip(cols + ['home'], map(float, b))), 'n_train': int(ok.sum()),
            'train_seasons': sorted(tr.season.unique().tolist()), 'resid_sd': float(resid.std())}


def fit_forecast(train, teams, division, conference, home_prior, prior=None, half_life=None,
                 asof_week=None, alpha=None, learn_s=False, warm=400, keep=500, chains=2, seed=1,
                 dynamic=False, q_scale=1.5, steps_ahead=None, conf_scale=None):
    """train: games before the forecast window (columns home_team, away_team, home_points, away_points,
    neutral_site, week). teams: team universe (training teams plus teams to forecast).
    prior: preseason prior {'mean': {team: m}, 's', 'mu_fcs'} for FBS teams (None = V0, the merit model).
    learn_s: treat s as unknown, LogNormal(log s, 0.35), so the season's games decide how far teams stray from it.
    alpha: if given, fit to alpha * margin + (1 - alpha) * efficiency margin (column 'eff', from postgame win
    expectancy) and rescale sigma so the predictive distribution is on the scale of real margins.
    dynamic: team strength follows a random walk across weeks (step SD q ~ HalfNormal(q_scale)); the prior applies to
    week-1 strength, and forecasts start from each team's latest strength plus steps_ahead more weeks of drift
    (default: asof_week minus the last training week)."""
    ix = {t: i for i, t in enumerate(teams)}
    groups = ['fbs', 'fcs']; grp = np.array([groups.index(division[t]) for t in teams], dtype=np.int32)
    lab = {t: (t if 'independent' in str(conference.get(t) or 'independent').lower() else str(conference[t])) for t in teams}
    cls = sorted(set(lab.values())); cl = np.array([cls.index(lab[t]) for t in teams], dtype=np.int32)
    hn = {t: i for i, t in enumerate(home_prior['names'])}
    hi = np.array([ix[t] for t in train.home_team], dtype=np.int32); ai = np.array([ix[t] for t in train.away_team], dtype=np.int32)
    site = (~train.neutral_site.astype(bool)).to_numpy(float); margin = (train.home_points - train.away_points).to_numpy(float)
    y = margin if alpha is None else alpha * margin + (1 - alpha) * train.eff.to_numpy(float)
    host = np.array([hn.get(t, 0) for t in train.home_team], dtype=np.int32)
    if half_life:
        w = 0.5 ** ((asof_week - train.week.to_numpy(float)) / half_life)
    else:
        w = np.ones(len(train))
    if prior is not None:
        has_prev = np.array([division[t] == 'fbs' and t in prior['mean'] for t in teams])
        pm = np.array([prior['mean'][t] if h else 0. for t, h in zip(teams, has_prev)])
        fm = prior.get('fcs_mean', {})                         # FCS deviations from the FCS mean (V6+)
        fcs_mask = np.array([division[t] != 'fbs' and t in fm for t in teams])
        pm = np.where(fcs_mask, [fm.get(t, 0.) for t in teams], pm); has_prev = has_prev | fcs_mask
        s_prev, fcs_mu, fcs_sd = prior['s'], prior['mu_fcs'], 5.
    else:
        has_prev, pm, s_prev, fcs_mu, fcs_sd = np.zeros(len(teams), bool), np.zeros(len(teams)), 1., 0., 0.
        fcs_mask = np.zeros(len(teams), bool)
    weeks = train.week.to_numpy(int); n_weeks = int(weeks.max()) if len(weeks) else 1
    wk = np.clip(weeks - 1, 0, n_weeks - 1).astype(np.int32); dyn = bool(dynamic and n_weeks > 1)
    init = {'tau': jnp.full(2, 10.), 'mu_free': jnp.full(1, -20. if prior is None else fcs_mu), 'tau_conf': jnp.asarray(5.)}
    kernel = NUTS(forecast_model, target_accept_prob=.9, init_strategy=init_to_value(values=init))
    mcmc = MCMC(kernel, num_warmup=warm, num_samples=keep, num_chains=chains, chain_method='sequential', progress_bar=False)
    mcmc.run(jax.random.PRNGKey(seed), extra_fields=('diverging',), hi=jnp.asarray(hi), ai=jnp.asarray(ai),
             site=jnp.asarray(site), host_idx=jnp.asarray(host), grp=jnp.asarray(grp), n_teams=len(teams), n_groups=2,
             hmu=jnp.asarray(home_prior['mean']), hL=jnp.asarray(home_prior['chol']), cl=jnp.asarray(cl), n_clusters=len(cls),
             has_prev=jnp.asarray(has_prev), prev_mean=jnp.asarray(pm), s_prev=float(s_prev), fcs_mu=float(fcs_mu),
             fcs_sd=float(fcs_sd), w=jnp.asarray(w), y=jnp.asarray(y), learn_s=bool(learn_s and prior is not None),
             wk=jnp.asarray(wk), n_weeks=n_weeks, dynamic=dyn, q_scale=float(q_scale), conf_scale=conf_scale,
             fcs_prior=(jnp.asarray(fcs_mask) if prior is not None and fcs_mask.any() else None),
             fcs_s=float(prior.get('fcs_s', 5.)) if prior is not None else 5.)
    s = {k: np.asarray(v) for k, v in mcmc.get_samples().items()}
    from arviz_stats.base.array import array_stats as A
    th = np.asarray(mcmc.get_samples(group_by_chain=True)['theta_last' if dyn else 'theta'])
    sigma = s['sigma']
    if alpha is not None:                                     # put the noise back on the scale of real margins
        hv = s['home_values'].mean(0); hloc = site * (hv[0] + np.where(host > 0, hv[host], 0.))
        tg = s['theta'].mean(0)[:, None] + (s['walk'].mean(0) if dyn else 0.)
        tg = np.broadcast_to(tg, (len(teams), n_weeks)) if not dyn else tg
        loc = tg[hi, wk] - tg[ai, wk] + hloc
        sigma = sigma * np.sqrt(np.average((margin - loc) ** 2, weights=w) / np.average((y - loc) ** 2, weights=w))
    rhat = float(np.nanmax(A.rhat(np.moveaxis(th, -1, 0), method='rank'))) if chains > 1 else np.nan
    s_post = float(np.mean(s['s_prev'])) if 's_prev' in s else None
    theta_out, q_post = s['theta'], None
    if dyn:                                                   # latest strength plus drift until the forecast week
        ahead = steps_ahead if steps_ahead is not None else max(int(asof_week) - n_weeks, 1)
        rng = np.random.default_rng(seed)
        theta_out = s['theta_last'] + s['q'][:, None] * np.sqrt(ahead) * rng.standard_normal(s['theta_last'].shape)
        q_post = float(np.mean(s['q']))
    extra = {}
    if dyn:                                                   # weekly strength path (theta + walk), for the product's explorer
        tw = s['theta'][:, :, None] + s['walk']
        extra = {'traj_mean': tw.mean(0), 'traj_sd': tw.std(0), 'theta_last': s['theta_last'], 'q_draws': s['q'], 'n_weeks': n_weeks}
    jax.clear_caches()                                         # compiled kernels pile up across refits otherwise
    return {'s_prev_post': s_post, 'q_post': q_post, 'teams': list(teams), 'theta': theta_out, 'home_values': s['home_values'], 'home_names': list(home_prior['names']),
            'sigma': sigma, 'nu': s['nu'], 'divergences': int(np.asarray(mcmc.get_extra_fields()['diverging']).sum()),
            'max_rhat_theta': rhat, **extra}


# ----------------------------------------------------------------------------------------------------------------
# Predictions
# ----------------------------------------------------------------------------------------------------------------
def _home_draws(fit, games):
    hn = {t: i for i, t in enumerate(fit['home_names'])}
    host = np.array([hn.get(t, 0) for t in games.home_team])
    site = (~games.neutral_site.astype(bool)).to_numpy(float)
    hv = fit['home_values']
    return site[None] * (hv[:, :1] + np.where(host[None] > 0, hv[:, host], 0.))


def predict(fit, games):
    """Posterior predictive for each game (home perspective): spread, SD, P(home win), and, when scores are present,
    log predictive density of the observed margin, PIT, and 90% interval hit."""
    ix = {t: i for i, t in enumerate(fit['teams'])}
    loc = fit['theta'][:, games.home_team.map(ix)] - fit['theta'][:, games.away_team.map(ix)] + _home_draws(fit, games)
    sig, nu = fit['sigma'][:, None], fit['nu'][:, None]
    out = pd.DataFrame({'spread': loc.mean(0), 'sd': np.sqrt(loc.var(0) + (sig ** 2 * nu / (nu - 2)).mean(0)),
                        'p_home': stats.t.sf(0, nu, loc, sig).mean(0)}, index=games.index)
    if 'home_points' in games and games.home_points.notna().all():
        y = (games.home_points - games.away_points).to_numpy(float)
        out['lpd'] = logsumexp(stats.t.logpdf(y[None], nu, loc, sig), axis=0) - np.log(len(sig))
        out['pit'] = stats.t.cdf(y[None], nu, loc, sig).mean(0)
    return out


def predict_from_prior(prior, games, division, home_prior):
    """Week-1 forecast from the preseason prior alone (no current-season games): Gaussian approximation."""
    def mv(t):
        if division[t] == 'fbs' and t in prior['mean']:
            return prior['mean'][t], prior['s'] ** 2
        if division[t] == 'fbs':
            return 0., prior['tau_fbs'] ** 2
        if t in prior.get('fcs_mean', {}):
            return prior['mu_fcs'] + prior['fcs_mean'][t], prior.get('fcs_s', 5.) ** 2 + 25.
        return prior['mu_fcs'], prior['tau_fcs'] ** 2 + 25.
    hn = {t: i for i, t in enumerate(home_prior['names'])}
    out = []
    for g in games.itertuples():
        (mh, vh), (ma, va) = mv(g.home_team), mv(g.away_team)
        k = hn.get(g.home_team, 0); site = 0. if g.neutral_site else 1.
        hm = site * (home_prior['mean'][0] + (home_prior['mean'][k] if k else 0.))
        hv = site * (home_prior['covariance'][0, 0] + (home_prior['covariance'][k, k] + 2 * home_prior['covariance'][0, k] if k else 0.))
        mu = mh - ma + hm; sd = np.sqrt(vh + va + hv + prior['sigma'] ** 2)
        out.append((mu, sd))
    o = pd.DataFrame(out, columns=['spread', 'sd'], index=games.index)
    o['p_home'] = stats.norm.sf(0, o.spread, o.sd)
    if 'home_points' in games:
        y = (games.home_points - games.away_points).to_numpy(float)
        o['lpd'] = stats.norm.logpdf(y, o.spread, o.sd); o['pit'] = stats.norm.cdf(y, o.spread, o.sd)
    return o
