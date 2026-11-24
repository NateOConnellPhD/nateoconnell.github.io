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
    from scipy.stats import t, norm
    th, hv, sigma, nu = (np.asarray(arrays[k], float) for k in ('theta', 'home_values', 'sigma', 'nu'))
    n, nt = th.shape
    if (n < 100 or nt != len(teams) or hv.shape != (n, len(home_ids)) or sigma.shape != (n,) or nu.shape != (n,)
            or any(not np.isfinite(a).all() for a in (th, hv, sigma, nu)) or (sigma <= 0).any() or (nu <= 2).any()):
        raise ValueError('Invalid predictive posterior arrays')
    ix = {t['id']: i for i, t in enumerate(teams)}; hn = {t: i for i, t in enumerate(home_ids)}
    if len(ix) != nt or len(hn) != len(home_ids) or home_ids[0] != 'national': raise ValueError('Invalid forecast roster')
    fbs = [i for i, team in enumerate(teams) if team['division'] == 'fbs']
    if not fbs: raise ValueError('No FBS power estimates')
    # Preserve the supplied model scale, including uncertainty in its level.
    # Subtracting the realized FBS mean changes marginal rating intervals.
    ranks = (-th[:, fbs]).argsort(axis=1).argsort(axis=1) + 1
    ratings = []
    for j, col in enumerate(fbs):
        team = teams[col]; key = team['id']
        ratings.append({**team, **summary(th[:, col]), 'record': records.get(key),
            'prior_mean': prior_means.get(key), 'rank_median': float(np.median(ranks[:, j])),
            'rank_lo80': float(np.quantile(ranks[:, j], .1)), 'rank_hi80': float(np.quantile(ranks[:, j], .9)),
            **{f'p_top{k}': float((ranks[:, j] <= k).mean()) for k in (1, 4, 12, 25)}})
    ratings.sort(key=lambda r: (-r['mean'], r['name']))
    for i, row in enumerate(ratings, 1): row['position'] = i
    selected = np.linspace(0, n - 1, min(thin, n)).round().astype(int)
    # Same draw indices for all teams, venues, sigma and nu; never independent resampling.
    rng = np.random.default_rng(20261122)
    noise = sigma[selected, None] * rng.standard_t(nu[selected, None], (len(selected), 2))
    rnd = lambda a: np.round(a, 5).tolist()
    browser = {'schema': SCHEMA, 'teams': {team['id']: rnd(th[selected, i]) for i, team in enumerate(teams)},
               'home': {key: rnd(hv[selected, i]) for i, key in enumerate(home_ids)},
               'sigma': rnd(sigma[selected]), 'nu': rnd(nu[selected]), 'noise': rnd(noise.T)}
    lam=np.asarray(arrays.get('lam',np.zeros(n)),float)
    if lam.shape != (n,) or not np.isfinite(lam).all(): raise ValueError('Invalid QB coefficient draws')
    if 'lam' in arrays:
        browser['lam']=rnd(lam[selected]); browser['lambda_mean']=float(lam.mean())
    dynamic = 'drift' in arrays
    if dynamic:
        last = np.asarray(arrays['theta_last']); drift = np.asarray(arrays['drift'])
        if last.shape != th.shape or drift.shape != th.shape or not np.isfinite(last).all() or not np.isfinite(drift).all():
            raise ValueError('Invalid weekly drift arrays')
        browser['last'] = {team['id']: rnd(last[selected,i]) for i,team in enumerate(teams)}
        browser['drift'] = {team['id']: rnd(drift[selected,i]) for i,team in enumerate(teams)}
        browser['means'] = {'last':{team['id']:float(last[:,i].mean()) for i,team in enumerate(teams)},
            'drift':{team['id']:float(drift[:,i].mean()) for i,team in enumerate(teams)},
            'home':{key:float(hv[:,i].mean()) for i,key in enumerate(home_ids)}}
        del browser['teams']  # next-week draws are last + innovation, not another download
    else:
        browser['means'] = {'teams': {team['id']: float(th[:, i].mean()) for i, team in enumerate(teams)},
                            'home': {key: float(hv[:, i].mean()) for i, key in enumerate(home_ids)}}
    if 'gaussian_mean' in arrays:
        gm=np.asarray(arrays['gaussian_mean'])
        browser['gaussian']={'teams':{team['id']:{'mean':float(gm[i]),'variance':float(arrays['gaussian_var'][i])} for i,team in enumerate(teams)},
            'home_ids':home_ids,'home_mean':np.asarray(arrays['gaussian_home_mean']).tolist(),
            'home_cov':np.asarray(arrays['gaussian_home_cov']).tolist(), 'sigma':float(arrays['gaussian_sigma'])}
    rows = []
    for game in games:
        h, a = game['home'], game['away']; host = hn.get(h, 0)
        if h == a or h not in ix or a not in ix: raise ValueError('Unknown or identical matchup teams')
        if dynamic:
            ahead = game.get('ahead',1)
            if type(ahead) is not int or not 1 <= ahead <= 52: raise ValueError('Invalid forecast horizon')
            # Report full-posterior means and probabilities, as predict() does
            # in the supplied code. Browser thinning is only for exploration.
            strength = np.asarray(arrays['theta_last']) + np.sqrt(ahead) * np.asarray(arrays['drift'])
            loc = strength[:, ix[h]] - strength[:, ix[a]]
            if not game['neutral']: loc += hv[:, 0] + (hv[:, host] if host else 0.)
            loc += lam * (game.get('qb_x_home',0.) - game.get('qb_x_away',0.))
            p = float(t.cdf(loc / sigma, nu).mean())
            simulated = (loc[selected,None] + noise).ravel()
        else:
            loc = th[:, ix[h]] - th[:, ix[a]]
            if not game['neutral']: loc = loc + hv[:, 0] + (hv[:, host] if host else 0.)
            loc += lam * (game.get('qb_x_home',0.) - game.get('qb_x_away',0.))
            p = float(t.cdf(loc / sigma, nu).mean())
            simulated = (loc[selected,None] + noise).ravel()
        mean = float(loc.mean())
        if 'gaussian' in browser:
            z=browser['gaussian']; m=z['teams']; hc=np.array(z['home_cov']); hm=np.array(z['home_mean'])
            mean=m[h]['mean']-m[a]['mean']+(0. if game['neutral'] else hm[0]+(hm[host] if host else 0.))
            variance=m[h]['variance']+m[a]['variance']+(0. if game['neutral'] else hc[0,0]+(hc[host,host]+2*hc[0,host] if host else 0.))
            sd=float(np.sqrt(variance+z['sigma']**2));p=float(norm.cdf(mean/sd))
            intervals={f'margin_{side}{coverage}':float(mean+norm.ppf(q)*sd) for coverage,lo,hi in ((80,.1,.9),(95,.025,.975)) for side,q in (('lo',lo),('hi',hi))}
        else: intervals={}
        rows.append({**game, 'home_margin':mean, 'home_line':-mean, 'p_home':p,
            'margin_lo80':float(np.quantile(simulated,.1)), 'margin_hi80':float(np.quantile(simulated,.9)),
            'margin_lo95':float(np.quantile(simulated,.025)), 'margin_hi95':float(np.quantile(simulated,.975)), **intervals})
    public = {'schema': SCHEMA, 'meta': {**meta, 'rating_scale':'supplied-model', 'draws':n, 'matchup_draws':len(selected)},
              'teams':teams, 'ratings':ratings, 'games':rows}
    return public, browser


def add_details(public, arrays, inputs, prior, home_ids, expectancy):
    """Inspectable prior, posterior paths and retrospective game evidence."""
    import numpy as np
    from .model import efficiency_target
    teams=public['teams']; ix={t['id']:i for i,t in enumerate(teams)}
    fbs=[i for i,t in enumerate(teams) if t['division']=='fbs']
    hm=np.asarray(arrays['home_values']).mean(0); hn={t:i for i,t in enumerate(home_ids)}
    trajectory=arrays.get('trajectory_mean'); spread=arrays.get('trajectory_sd')
    details={}
    for t in teams:
        key=t['id']; item=prior.get('team_inputs',{}).get(key,{})
        row={'prior':prior['mean_by_id'].get(key), 'prior_average':prior.get('prior_average'), **item, 'games':[]}
        if t['division']=='fcs' and key in prior.get('fcs_mean_by_id',{}):
            row['fcs_prior']={'mean':prior['fcs_gap']+prior['fcs_mean_by_id'][key], 'deviation':prior['fcs_mean_by_id'][key], 'sd':prior['fcs_sd']}
        if trajectory is not None:
            row['path']=[{'week':w+1,'mean':float(m),'sd':float(spread[ix[key],w])} for w,m in enumerate(trajectory[ix[key]])]
        details[key]=row
    if inputs['games']:
        target,_,_=efficiency_target(inputs['data']['margin'],expectancy)
        for j,g in enumerate(inputs['games']):
            home,away=str(g['home_id']),str(g['away_id']); slot=hn.get(home,0)
            edge=0. if g.get('neutral_site',False) else float(hm[0]+(hm[slot] if slot else 0.))
            qb_edge=float(np.asarray(arrays['lam']).mean()*inputs['qbx'][j]) if 'qbx' in inputs else 0.
            for team,opp,sign in ((home,away,1),(away,home,-1)):
                w=max(g['week']-1,0)
                opp_strength=float(trajectory[ix[opp],w]) if trajectory is not None else None
                details[team]['games'].append({'id':g['id'],'week':g['week'],'date':g['start_date'],'opponent':opp,
                    'site':'neutral' if g.get('neutral_site',False) else ('home' if sign==1 else 'away'),
                    'margin':sign*inputs['data']['margin'][j], 'target':float(sign*target[j]), 'home_edge':sign*edge,
                    'qb_edge':sign*qb_edge, 'opponent_strength':opp_strength,
                    'game_implied_strength':float(sign*target[j]+opp_strength-sign*edge-sign*qb_edge) if opp_strength is not None else None})
    public['team_details']=details
    public['home_means']={k:float(hm[i]) for i,k in enumerate(home_ids)}
    public['prior_coefficients']=prior.get('coefficients',{})


def write(public, draws, destination):
    """Content-addressed snapshots; the index is replaced only after both files exist."""
    import hashlib
    from datetime import datetime, timezone
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    encode = lambda v: (json.dumps(v, allow_nan=False, separators=(',', ':')) + '\n').encode()
    dr = encode(draws); draw_id = hashlib.sha256(dr).hexdigest()[:16]
    draw_name = f'draws-{draw_id}.json'
    # A data observation timestamp is not a forecast creation timestamp. Record
    # the actual save time, including for retrospective fits, for honest grading.
    public = {**public, 'draws_file': draw_name,
              'meta': {**public['meta'], 'saved_at': datetime.now(timezone.utc).isoformat()}}
    body = encode(public); ident = hashlib.sha256(body).hexdigest()[:16]
    name = f'forecast-{ident}.json'
    (destination / draw_name).write_bytes(dr); (destination / name).write_bytes(body)
    index_path = destination / 'index.json'
    old = json.loads(index_path.read_text()) if index_path.exists() else {'snapshots': []}
    row = {'id': ident, 'file': name, 'season': public['meta']['season'],
           'through_date': public['meta']['through_date'], 'observed_at': public['meta']['observed_at'],
           'week': public['meta']['week'], 'input_key': public['meta']['input_key']}
    row['model'] = public['meta'].get('model')
    row['historical_reconstruction'] = public['meta'].get('historical_reconstruction',False)
    history = [row] + [r for r in old['snapshots'] if r['id'] != ident]
    live = [r for r in history if not r.get('historical_reconstruction')]
    latest = max(live or history, key=lambda r:(r['season'],r['week'],r['observed_at'],r['id']))['id']
    if not row['historical_reconstruction'] and row['season'] == max(r['season'] for r in live): latest = ident
    index_path.write_bytes(encode({'schema': SCHEMA, 'latest': latest, 'snapshots': history}))
    return row
