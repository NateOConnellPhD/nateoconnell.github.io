"""Public, allowlisted forecast outputs. No raw handoff files or embedded source."""
import json
from pathlib import Path

SCHEMA = 'cfb-projections-v1'


def summary(values):
    import numpy as np
    v = np.asarray(values)
    return {'mean': float(v.mean()), 'median': float(np.median(v)),
            'lo80': float(np.quantile(v, .1)), 'hi80': float(np.quantile(v, .9)),
            'lo95': float(np.quantile(v, .025)), 'hi95': float(np.quantile(v, .975))}


def build(arrays, teams, home_ids, games, meta, prior_means, records, *, thin=1000):
    import numpy as np
    from scipy.stats import t
    th, hv, sigma, nu = (np.asarray(arrays[k], float) for k in ('theta', 'home_values', 'sigma', 'nu'))
    n, nt = th.shape
    if (n < 100 or nt != len(teams) or hv.shape != (n, len(home_ids)) or sigma.shape != (n,) or nu.shape != (n,)
            or any(not np.isfinite(a).all() for a in (th, hv, sigma, nu)) or (sigma <= 0).any() or (nu <= 2).any()):
        raise ValueError('Invalid predictive posterior arrays')
    ix = {t['id']: i for i, t in enumerate(teams)}; hn = {t: i for i, t in enumerate(home_ids)}
    if len(ix) != nt or len(hn) != len(home_ids) or home_ids[0] != 'national': raise ValueError('Invalid forecast roster')
    fbs = [i for i, team in enumerate(teams) if team['division'] == 'fbs']
    if not fbs: raise ValueError('No FBS power estimates')
    # The reported scale is points relative to the average FBS team in each draw.
    # Centering cancels in every matchup; preserve the joint draws and covariance.
    centered = th - th[:, fbs].mean(1)[:, None]
    ranks = (-th[:, fbs]).argsort(axis=1).argsort(axis=1) + 1
    ratings = []
    for j, col in enumerate(fbs):
        team = teams[col]; key = team['id']
        ratings.append({**team, **summary(centered[:, col]), 'record': records.get(key),
            'prior_mean': prior_means.get(key), 'rank_median': float(np.median(ranks[:, j])),
            'rank_lo80': float(np.quantile(ranks[:, j], .1)), 'rank_hi80': float(np.quantile(ranks[:, j], .9)),
            **{f'p_top{k}': float((ranks[:, j] <= k).mean()) for k in (1, 4, 12, 25)}})
    ratings.sort(key=lambda r: (-r['mean'], r['name']))
    for i, row in enumerate(ratings, 1): row['position'] = i
    selected = np.linspace(0, n - 1, min(thin, n)).round().astype(int)
    # Same draw indices for all teams, venues, sigma and nu; never independent resampling.
    rng = np.random.default_rng(20261122)
    noise = sigma[selected, None] * rng.standard_t(nu[selected, None], (len(selected), 2))
    rows = []
    for game in games:
        h, a = game['home'], game['away']; host = hn.get(h, 0)
        if h == a or h not in ix or a not in ix: raise ValueError('Unknown or identical matchup teams')
        loc = th[:, ix[h]] - th[:, ix[a]]
        if not game['neutral']: loc = loc + hv[:, 0] + (hv[:, host] if host else 0.)
        mean = float(loc.mean()); p = float(t.cdf(loc / sigma, nu).mean())
        simulated = (loc[selected, None] + noise).ravel()
        rows.append({**game, 'home_margin': mean, 'home_line': -mean, 'p_home': p,
                     'margin_lo80': float(np.quantile(simulated, .1)), 'margin_hi80': float(np.quantile(simulated, .9)),
                     'margin_lo95': float(np.quantile(simulated, .025)), 'margin_hi95': float(np.quantile(simulated, .975))})
    public = {'schema': SCHEMA, 'meta': {**meta, 'draws': n, 'matchup_draws': len(selected)},
              'teams': teams, 'ratings': ratings, 'games': rows}
    # Round only browser draw payloads; published tables use every full-precision draw.
    rnd = lambda a: np.round(a, 5).tolist()
    browser = {'schema': SCHEMA, 'teams': {team['id']: rnd(centered[selected, i]) for i, team in enumerate(teams)},
               'home': {key: rnd(hv[selected, i]) for i, key in enumerate(home_ids)},
               'sigma': rnd(sigma[selected]), 'nu': rnd(nu[selected]), 'noise': rnd(noise.T)}
    browser['means'] = {'teams': {team['id']: float(centered[:, i].mean()) for i, team in enumerate(teams)},
                        'home': {key: float(hv[:, i].mean()) for i, key in enumerate(home_ids)}}
    return public, browser


def write(public, draws, destination):
    """Content-addressed snapshots; the index is replaced only after both files exist."""
    import hashlib
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    encode = lambda v: (json.dumps(v, allow_nan=False, separators=(',', ':')) + '\n').encode()
    dr = encode(draws); draw_id = hashlib.sha256(dr).hexdigest()[:16]
    draw_name = f'draws-{draw_id}.json'
    public = {**public, 'draws_file': draw_name}
    body = encode(public); ident = hashlib.sha256(body).hexdigest()[:16]
    name = f'forecast-{ident}.json'
    (destination / draw_name).write_bytes(dr); (destination / name).write_bytes(body)
    index_path = destination / 'index.json'
    old = json.loads(index_path.read_text()) if index_path.exists() else {'snapshots': []}
    row = {'id': ident, 'file': name, 'season': public['meta']['season'],
           'through_date': public['meta']['through_date'], 'observed_at': public['meta']['observed_at'],
           'week': public['meta']['week'], 'input_key': public['meta']['input_key']}
    history = [row] + [r for r in old['snapshots'] if r['id'] != ident]
    index_path.write_bytes(encode({'schema': SCHEMA, 'latest': ident, 'snapshots': history}))
    return row
