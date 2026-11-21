"""PSIS-LOO merit with the handoff's explicitly approximate joint transport.

Unreliable PSIS requires a checked omitted-game refit from the production
callback, or stops the comparison. It never substitutes raw importance weights.
"""
import arviz as az
import numpy as np
from scipy.special import stdtr
from scipy.stats import t as student


def flatten(samples):
    return {k: np.asarray(samples[k]).reshape((-1,) + np.asarray(samples[k]).shape[2:])
            for k in ('theta', 'home_adv', 'sigma', 'nu', 'home_effect') if k in samples}


def venue_effect(samples, data):
    """Actual host's structural advantage for each draw/game, zero at neutral sites."""
    if 'host' in data:
        if 'home_effect' not in samples:
            raise ValueError('Host-specific scoring requires historical-home posterior draws')
        host = np.asarray(data['host'], dtype=int)
        effects = samples['home_effect']
        if len(host) != len(data['home']) or np.any(host < 0) or np.any(host >= effects.shape[1]):
            raise ValueError('Invalid scoring host index')
        advantage = effects[:, :1] + np.where(host[None, :] > 0, effects[:, host], 0.)
    else:
        if 'home_effect' in samples:
            raise ValueError('Historical-home scoring requires host indices')
        advantage = samples['home_adv'][:, None]
    return advantage * np.asarray(data['venue'])


def reference_strength(samples, reference_rank=25, reference_indices=None):
    theta = samples['theta'] if reference_indices is None else samples['theta'][:, reference_indices]
    n = theta.shape[1]
    if not 1 <= reference_rank <= n:
        raise ValueError('Reference rank outside the FBS roster')
    return np.partition(theta, n-reference_rank, axis=1)[:, n-reference_rank]


def game_values(samples, data, game, reference_rank=25, reference=None, *, reference_indices=None):
    n = samples['theta'].shape[1] if reference_indices is None else len(reference_indices)
    if not 1 <= reference_rank <= n:
        raise ValueError('Reference rank outside the season roster')
    if reference is None:
        reference = reference_strength(samples, reference_rank, reference_indices)
    h, a, venue, margin = (data[key][game] for key in ('home', 'away', 'venue', 'margin'))
    home = venue_effect(samples, {key: [data[key][game]] for key in ('home', 'venue', 'host') if key in data})[:, 0]
    mu_h = reference - samples['theta'][:, a] + home
    mu_a = reference - samples['theta'][:, h] - home
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
    mu = flat['theta'][:, data['home']] - flat['theta'][:, data['away']] + venue_effect(flat, data)
    return student.logpdf(np.asarray(data['margin'])[None, :], flat['nu'][:, None], loc=mu, scale=flat['sigma'][:, None])


def score(samples, data, *, reference_rank=25, reff=None, exact_refitter=None,
          reference_indices=None, scored_indices=None):
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
    selected = list(range(len(data['margin']))) if scored_indices is None else list(scored_indices)
    if len(set(selected)) != len(selected) or any(i < 0 or i >= len(data['margin']) for i in selected):
        raise ValueError('Invalid scored-game indices')
    selected_weights, selected_k = loo_weights(log_likelihood(flat, data)[:, selected], reff)
    weights = np.full((len(data['margin']), draws), 1 / draws)
    k = np.zeros(len(data['margin']))
    weights[selected] = selected_weights; k[selected] = selected_k
    cutoff = min(.7, 1. - 1. / np.log10(draws))
    bad = np.flatnonzero(~np.isfinite(k) | (k > cutoff))
    if len(bad) and exact_refitter is None:
        raise ValueError(f'Exact LOO refits required before ranking games {bad.tolist()}')
    exact = {}
    for game in bad:
        # The callback must refit with this observation omitted and check MCMC.
        exact[int(game)] = exact_refitter(int(game))
        weights[game] = 1 / draws  # Not used for an exact-refit marginal.
    result = aggregate_credits(flat, data, weights, reference_rank, exact=exact,
        reference_indices=reference_indices, scored_indices=selected)
    result['weights'] = weights
    for row in result['audit']:
        game = row['game']
        row['pareto_k'] = float(k[game]) if np.isfinite(k[game]) else None
        row['method'] = 'exact_loo' if game in exact else 'psis_loo'
    finite_k = k[np.isfinite(k)]
    result['diagnostics'].update(max_pareto_k=float(finite_k.max()) if len(finite_k) else None,
                                 nonfinite_pareto_k=int((~np.isfinite(k)).sum()), threshold=cutoff,
                                 relative_efficiency=reff, psis_unreliable_games=len(bad),
                                 exact_refits=len(exact), unreliable_games=0)
    return result


def aggregate_credits(flat, data, weights, reference_rank=25, *, exact=None,
                      reference_indices=None, scored_indices=None):
    """Accumulate validated per-game marginals; weights determine the target.

    Production callers must use score(), which obtains and checks LOO weights.
    Kept separate so the forensic comparison can reproduce the archived mistake.
    """
    draws, n = flat['theta'].shape
    exact = exact or {}
    if weights.shape != (len(data['margin']), draws) or not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError('Invalid game weights')
    if not np.allclose(weights.sum(axis=1), 1.):
        raise ValueError('LOO weights do not sum to one')
    merit, sos = np.zeros((draws, n)), np.zeros((draws, n))
    counts = np.bincount(data['home'], minlength=n) + np.bincount(data['away'], minlength=n)
    audit, error = [], 0.
    reference = reference_strength(flat, reference_rank, reference_indices)
    selected = set(range(len(data['margin']))) if scored_indices is None else set(scored_indices)
    for game, (h, a, margin) in enumerate(zip(data['home'], data['away'], data['margin'])):
        if game not in selected: continue
        raw = game_values(flat, data, game, reference_rank, reference)
        if game in exact:
            replacement = exact[game]
            if set(replacement) != set(raw):
                raise ValueError('Exact LOO quantities do not match the scoring definition')
            moved, weighted = {}, {}
            for name, value in raw.items():
                values = np.asarray(replacement[name])
                if values.ndim != 1 or len(values) < 4 or not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
                    raise ValueError('Invalid exact LOO probability draws')
                ranks = np.empty(draws, int)
                ranks[np.argsort(value, kind='stable')] = np.arange(draws)
                # Replace the marginal, retaining the disclosed approximate
                # full-posterior rank coupling rather than pairing random chains.
                moved[name] = np.quantile(values, (ranks + .5) / draws)
                weighted[name] = float(values.mean())
        else:
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
