"""Bayesian QB value model (hierarchical Gaussian; hyperparameters by empirical Bayes / REML).

Unit: one passer x team x game (non-garbage dropbacks: pass attempts and sacks). Outcome: mean EPA per dropback, with
known noise variance sigma^2 / n (sigma = per-dropback SD of EPA, pooled within passer-games).

  ybar_i = mu + h*home_i + f_o*FCS_offense_i + f_d*FCS_defense_i
           + b*z_{k,season}             (experience prior: z = log1p(career dropbacks before this season / 100); a QB
                                         with no history starts at replacement level, not at the average starter)
           + f_r*new_i                  (new_i = 1 if the passer had fewer than 50 career dropbacks before this game:
                                         first-time passers do worse than any prior based on QBs who play)
           + q_k                        (QB, persistent across seasons and transfers; ESPN athlete id)
           + s_{k,season}               (QB's season deviation: development, health)
           + o_{offense, season}        (the rest of the offense: line, receivers, scheme)
           + d_{defense, season}        (opposing pass defense)
           + e_i,   e_i ~ N(0, sigma^2 / n_i)
  q ~ N(0, tq^2), s ~ N(0, ts^2), o ~ N(0, to^2), d ~ N(0, td^2); flat priors on mu, h, f_o, f_d, b.

Given the variance components the posterior of every effect is Gaussian and exact (Henderson's mixed-model equations,
sparse). The variance components maximize the restricted (REML) likelihood of the data before the forecast week.
QB value for a season: v = b*z + q + s, in EPA per dropback relative to an average passer in an average offense."""
import numpy as np, pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import splu
from scipy.optimize import minimize


def _lu(A):
    # symmetric positive definite system: a symmetric minimum-degree ordering keeps fill-in small (about 20x faster)
    return splu(A, permc_spec='MMD_AT_PLUS_A', options={'SymmetricMode': True}, diag_pivot_thresh=0.0)


def career_before(db):
    """Career dropbacks of each passer before each season, from the dropbacks table (starts in 2021)."""
    t = db.groupby(['passer_id', 'season']).n.sum().unstack(fill_value=0).sort_index(axis=1)
    cb = t.cumsum(axis=1).shift(1, axis=1).fillna(0)
    return cb.stack().rename('career_before').reset_index()


def prepare(db, fbs_by_season, cutoff=None, cb=None):
    """cutoff: (season, week) -> regular-season games of that season before that week, plus all earlier seasons."""
    d = db.copy()
    if cutoff is not None:
        s, w = cutoff
        d = d[(d.season < s) | ((d.season == s) & (d.week < w) & (d.season_type == 'regular'))]
    d = d[d.n > 0].copy()
    d['ybar'] = d.epa_sum / d.n
    d['home_off'] = (d.pos_team == d.home).astype(float)
    d['fcs_off'] = [float(t not in fbs_by_season.get(s, set())) for s, t in zip(d.season, d.pos_team)]
    d['fcs_def'] = [float(t not in fbs_by_season.get(s, set())) for s, t in zip(d.season, d.def_pos_team)]
    cb = career_before(db) if cb is None else cb
    d = d.merge(cb, on=['passer_id', 'season'], how='left'); d['career_before'] = d.career_before.fillna(0.)
    d['z'] = np.log1p(d.career_before / 100.)
    d = d.sort_values(['season', 'week', 'game_id']).copy()
    d['season_before_game'] = d.groupby(['passer_id', 'season']).n.transform(lambda x: x.cumsum() - x)   # same-week rows are separate games
    d['new'] = ((d.career_before + d.season_before_game) < 50).astype(float)
    return d.reset_index(drop=True)


def pooled_sigma(d):
    ss = (d.epa2_sum - d.n * d.ybar ** 2).sum(); df = (d.n - 1).clip(lower=0).sum()
    return float(np.sqrt(ss / df))


def _uniq(a, b):
    return pd.Index(list(dict.fromkeys(zip(a, b))), tupleize_cols=False)


def _design(d):
    qb = pd.Index(d.passer_id.unique()); qs = _uniq(d.passer_id, d.season); off = _uniq(d.pos_team, d.season); de = _uniq(d.def_pos_team, d.season)
    n = len(d); r = np.arange(n)
    cols = [qb.get_indexer(d.passer_id), qs.get_indexer(list(zip(d.passer_id, d.season))),
            off.get_indexer(list(zip(d.pos_team, d.season))), de.get_indexer(list(zip(d.def_pos_team, d.season)))]
    sizes = [len(qb), len(qs), len(off), len(de)]
    Z = sp.hstack([sp.csr_matrix((np.ones(n), (r, c)), shape=(n, m)) for c, m in zip(cols, sizes)]).tocsr()
    X = sp.csr_matrix(np.c_[np.ones(n), d[['home_off', 'fcs_off', 'fcs_def', 'z', 'new']].to_numpy()])
    return X, Z, sizes, (qb, qs, off, de)


def _system(X, Z, w, y, sizes, tau):
    W = sp.diags(w)
    ginv = np.concatenate([np.full(m, 1 / t ** 2) for m, t in zip(sizes, tau)])
    A = sp.bmat([[X.T @ W @ X, X.T @ W @ Z], [Z.T @ W @ X, Z.T @ W @ Z + sp.diags(ginv)]]).tocsc()
    rhs = np.r_[X.T @ W @ y, Z.T @ W @ y]
    return A, rhs, ginv


def reml(d, sigma, start=(0.1, 0.05, 0.06, 0.06)):
    """Variance components (tq, ts, to, td) maximizing the restricted likelihood."""
    X, Z, sizes, _ = _design(d); y = d.ybar.to_numpy(); w = d.n.to_numpy() / sigma ** 2
    yRy = float(y @ (w * y))
    def obj(lt):
        tau = np.exp(lt); A, rhs, ginv = _system(X, Z, w, y, sizes, tau)
        lu = _lu(A); sol = lu.solve(rhs)
        logdetA = float(np.sum(np.log(np.abs(lu.U.diagonal()))))
        logdetG = float(-np.sum(np.log(ginv)))
        return logdetG + logdetA + yRy - float(sol @ rhs)
    r = minimize(obj, np.log(start), method='Nelder-Mead', options={'xatol': 1e-3, 'fatol': 1e-2, 'maxiter': 400})
    tq, ts, to, td = np.exp(r.x)
    return {'tq': float(tq), 'ts': float(ts), 'to': float(to), 'td': float(td), 'sigma': sigma, 'reml_obj': float(r.fun),
            'converged': bool(r.success), 'n_rows': int(len(d)), 'n_qb': int(d.passer_id.nunique())}


def solve(d, hp, want_sd_for=None):
    """Exact posterior given the variance components. Returns fixed effects, QB / QB-season / offense / defense effects,
    value(passer_id, season, z=None) -> posterior mean of b*z + q + s, and optional posterior SDs of v."""
    X, Z, sizes, (qb, qs, off, de) = _design(d); y = d.ybar.to_numpy(); w = d.n.to_numpy() / hp['sigma'] ** 2
    tau = tuple(max(hp[k], 0.005) for k in ('tq', 'ts', 'to', 'td'))   # floor: a component REML puts at 0 stays numerically stable
    A, rhs, _ = _system(X, Z, w, y, sizes, tau)
    lu = _lu(A); sol = lu.solve(rhs)
    p = X.shape[1]; fx = sol[:p]; u = sol[p:]
    nq, nqs, no = sizes[0], sizes[1], sizes[2]
    q = pd.Series(u[:nq], index=qb); s_ = pd.Series(u[nq:nq + nqs], index=qs)
    zmap = dict(zip(zip(d.passer_id, d.season), d.z))
    res = {'fixed': dict(zip(['mu', 'h', 'f_o', 'f_d', 'b', 'f_r'], map(float, fx))), 'q': q, 's': s_,
           'off': pd.Series(u[nq + nqs:nq + nqs + no], index=off), 'def': pd.Series(u[nq + nqs + no:], index=de)}
    b, f_r = float(fx[4]), float(fx[5])
    def value(pid, season, z=None, new=0.):
        """Posterior mean EPA/dropback value; new = 1 if the passer has under 50 career dropbacks at the game in question."""
        zz = zmap.get((pid, season), z if z is not None else 0.)
        return float(b * zz + f_r * new + (q[pid] if pid in q.index else 0.) + s_.get((pid, season), 0.))
    res['value'] = value; res['b'] = b; res['f_r'] = f_r
    if want_sd_for:
        sds = {}
        for pid, season in want_sd_for:
            e = np.zeros(A.shape[0]); e[4] = zmap.get((pid, season), 0.)
            if pid in q.index: e[p + qb.get_loc(pid)] = 1.
            j = qs.get_indexer([(pid, season)])[0]
            if j >= 0: e[p + nq + j] = 1.
            sds[(pid, season)] = float(np.sqrt(e @ lu.solve(e)))
        res['sd'] = sds
    return res
