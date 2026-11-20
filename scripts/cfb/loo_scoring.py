"""PSIS-LOO merit with the handoff's explicitly approximate joint transport.

This comparison scorer fails closed on unreliable PSIS; it never substitutes
unvalidated raw importance weights. Selective exact refits for a production
pipeline are separate from the reference comparison.
"""
import arviz as az
import numpy as np
from scipy.special import stdtr
from scipy.stats import t as student


def flatten(samples):
    return {k: np.asarray(samples[k]).reshape((-1,) + np.asarray(samples[k]).shape[2:])
            for k in ('theta', 'home_adv', 'sigma', 'nu')}


def game_values(samples, data, game, reference_rank=25, reference=None):
    n = samples['theta'].shape[1]
    if not 1 <= reference_rank <= n:
        raise ValueError('Reference rank outside the season roster')
    if reference is None:
        reference = np.partition(samples['theta'], n - reference_rank, axis=1)[:, n - reference_rank]
    h, a, venue, margin = (data[key][game] for key in ('home', 'away', 'venue', 'margin'))
    mu_h = reference - samples['theta'][:, a] + samples['home_adv'] * venue
    mu_a = reference - samples['theta'][:, h] - samples['home_adv'] * venue
    return {
        'home_cdf': stdtr(samples['nu'], (margin - mu_h) / samples['sigma']),
        'away_cdf': stdtr(samples['nu'], (-margin - mu_a) / samples['sigma']),
        'home_sos': stdtr(samples['nu'], -mu_h / samples['sigma']),
        'away_sos': stdtr(samples['nu'], -mu_a / samples['sigma']),
    }


def transport(values, weights):
    order = np.argsort(values, kind='stable')
    sorted_values, w = values[order], weights[order]
    x = np.r_[0., np.cumsum(w) - w / 2, 1.]
    y = np.r_[sorted_values[0], sorted_values, sorted_values[-1]]
    ranks = np.empty(len(values), int)
    ranks[order] = np.arange(len(values))
    return np.interp((ranks + .5) / len(values), x, y)


def loo_weights(log_likelihood, reff=1.):
    """ArviZ 0.22 expects log importance ratios, hence the minus sign.

    Keep this explicit: other packages' similarly named APIs can instead accept
    log likelihoods and negate them internally.
    """
    log_weights, k = az.psislw(-np.asarray(log_likelihood).T, reff=reff)
    return np.exp(log_weights), k


def log_likelihood(flat, data):
    mu = flat['theta'][:, data['home']] - flat['theta'][:, data['away']] + flat['home_adv'][:, None] * np.asarray(data['venue'])
    return student.logpdf(np.asarray(data['margin'])[None, :], flat['nu'][:, None], loc=mu, scale=flat['sigma'][:, None])


def score(samples, data, *, reference_rank=25, reff=None):
    flat = flatten(samples)
    draws, n = flat['theta'].shape
    if not 1 <= reference_rank <= n:
        raise ValueError('Reference rank outside the season roster')
    if any(m == 0 for m in data['margin']):
        raise ValueError('Tied games have no merit policy yet')
    if reff is None:
        ess = az.ess(samples, method='mean')
        reff = min(1., float(np.concatenate([np.asarray(v).ravel() for v in ess.data_vars.values()]).mean()) / draws)
    if not np.isfinite(reff) or reff <= 0:
        raise ValueError('Invalid relative MCMC efficiency')
    weights, k = loo_weights(log_likelihood(flat, data), reff)
    cutoff = min(.7, 1. - 1. / np.log10(draws))
    bad = np.flatnonzero(~np.isfinite(k) | (k > cutoff))
    if len(bad):
        raise ValueError(f'Exact LOO refits required before ranking games {bad.tolist()}')
    result = aggregate_credits(flat, data, weights, reference_rank)
    result['weights'] = weights
    for game, row in enumerate(result['audit']):
        row['pareto_k'] = float(k[game])
    result['diagnostics'].update(max_pareto_k=float(k.max()), threshold=cutoff,
                                 relative_efficiency=reff, unreliable_games=len(bad))
    return result


def aggregate_credits(flat, data, weights, reference_rank=25):
    """Accumulate validated per-game marginals; weights determine the target.

    Production callers must use score(), which obtains and checks LOO weights.
    Kept separate so the forensic comparison can reproduce the archived mistake.
    """
    draws, n = flat['theta'].shape
    if weights.shape != (len(data['margin']), draws) or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('Invalid game weights')
    if not np.allclose(weights.sum(axis=1), 1.):
        raise ValueError('LOO weights do not sum to one')
    merit, sos = np.zeros((draws, n)), np.zeros((draws, n))
    counts = np.bincount(data['home'], minlength=n) + np.bincount(data['away'], minlength=n)
    audit, error = [], 0.
    reference = np.partition(flat['theta'], n - reference_rank, axis=1)[:, n - reference_rank]
    for game, (h, a, margin) in enumerate(zip(data['home'], data['away'], data['margin'])):
        raw = game_values(flat, data, game, reference_rank, reference)
        weighted = {name: float(np.dot(value, weights[game])) for name, value in raw.items()}
        moved = {name: transport(value, weights[game]) for name, value in raw.items()}
        error = max(error, *(abs(moved[name].mean() - weighted[name]) for name in raw))
        credit_h = moved['home_cdf'] - int(margin < 0)
        credit_a = moved['away_cdf'] - int(margin > 0)
        for credit, won in ((credit_h, margin > 0), (credit_a, margin < 0)):
            if not (np.isfinite(credit).all() and np.all((credit >= (0 if won else -1)) & (credit <= (1 if won else 0)))):
                raise ValueError('Game credit outside its win/loss bounds')
        merit[:, h] += credit_h
        merit[:, a] += credit_a
        sos[:, h] += moved['home_sos']
        sos[:, a] += moved['away_sos']
        audit.append({'game': game,
                      'home_credit': weighted['home_cdf'] - int(margin < 0),
                      'away_credit': weighted['away_cdf'] - int(margin > 0)})
    sos = np.divide(sos, counts, out=np.full_like(sos, np.nan), where=counts > 0)
    return {'merit': merit, 'sos': sos, 'flat': flat,
            'audit': audit, 'diagnostics': {'max_transport_mean_error': error,
                                          'joint_uncertainty': 'marginal quantile transport approximation'}}
