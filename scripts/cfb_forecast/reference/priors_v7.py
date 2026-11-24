"""Frozen V7 preseason prior, the same construction as pipeline/backtest_forecast.py (variant prefix V7):
FBS teams: game-fitted regression of weeks 1-5 FBS-v-FBS margins (seasons 2022..season-1) on team covariates, level-shifted
to the V2 prior's mean, spread s from the V2 regression; FCS teams: own carryover of last season's D-I rating.
Used by code/make_forecasts.py. Checked against the backtest: identical coefficients, level shift and FCS prior for 2026."""
from pathlib import Path
import numpy as np
import pandas as pd
from forecast_model import (season_ratings, carryover, prior_from_carryover, preseason_regression,
                            preseason_regression_games)
from historical_home import CURRENT_TO_HISTORICAL

V7_COLS = ['prev', 'talent_z', 'ap', 'p4', 'rpc', 'prev_rp', 'rec_z', 'newcoach', 'prev_coach', 'portal_z', 'g5_prev']
H2C = {v: k for k, v in CURRENT_TO_HISTORICAL.items()}


class Data:
    def __init__(self, data):
        self.data = Path(data)
        a = pd.read_csv(self.data / 'historical_game_scores_2002_2024.csv')
        a['home_team'] = a.home_team.replace(H2C); a['away_team'] = a.away_team.replace(H2C)
        self.arch = a

    def sched(self, y):
        return pd.read_csv(self.data / 'cfbd' / f'cfb_schedules_{y}.csv', low_memory=False)

    @staticmethod
    def di(df):
        d = df[df.home_division.isin(['fbs', 'fcs']) & df.away_division.isin(['fbs', 'fcs']) & df.completed.astype(bool)].copy()
        d = d[d.home_points.notna() & d.away_points.notna()]
        d['neutral_site'] = d.neutral_site.fillna(False).astype(bool)
        return d

    def latest(self, prefix):
        return sorted((self.data / 'preseason').glob(prefix + '*.csv'))[-1]


def ratings_for(D, s):
    if s <= 2020:
        g = D.arch[D.arch.season == s]
        n = pd.concat([g.home_team, g.away_team]).value_counts(); fbs = set(n[n >= 5].index)
    else:
        g = D.di(D.sched(s)); g = g[g.home_division.eq('fbs') | g.away_division.eq('fbs')]
        fbs = set(g.loc[g.home_division.eq('fbs'), 'home_team']) | set(g.loc[g.away_division.eq('fbs'), 'away_team'])
    return season_ratings(g[['home_team', 'away_team', 'home_points', 'away_points', 'neutral_site']], fbs)


def covariates_v2(D):
    tal = pd.read_csv(D.data / 'preseason' / 'talent_composite_cfbd_2022_2026.csv')[['season', 'team', 'talent']]
    tal['talent_z'] = tal.groupby('season').talent.transform(lambda x: (x - x.mean()) / x.std())
    ap = pd.read_csv(D.data / 'preseason' / 'ap_preseason_poll_2022_2026.csv')
    ap = ap.assign(team=ap.team_cfbd)[['season', 'team', 'ap_points']]
    cov = tal.merge(ap, on=['season', 'team'], how='left')
    cov['ap'] = np.log1p(cov.ap_points.fillna(0.))
    return cov[['season', 'team', 'talent_z', 'ap']]


def covariates_v7(D, ratings, seasons):
    cov = covariates_v2(D)
    rp = pd.read_csv(D.latest('returning_production_cfbd_2022_'))[['season', 'team', 'percentPPA']]
    rec = pd.read_csv(D.latest('recruiting_class_cfbd_2022_'))[['season', 'team', 'recruiting_points']]
    rows = []
    for s in seasons:
        sc = D.sched(s)
        fb = pd.concat([sc.loc[sc.home_division == 'fbs', ['home_team', 'home_conference']].set_axis(['team', 'conf'], axis=1),
                        sc.loc[sc.away_division == 'fbs', ['away_team', 'away_conference']].set_axis(['team', 'conf'], axis=1)]).drop_duplicates('team')
        p4c = {'SEC', 'Big Ten', 'Big 12', 'ACC'} | ({'Pac-12'} if s <= 2023 else set())
        r0 = ratings.get(s - 1)
        for t, c in zip(fb.team, fb.conf):
            rows.append((s, t, float(c in p4c or t == 'Notre Dame'), r0['mean'][t] if r0 is not None and t in r0['fbs'] else np.nan))
    d = pd.DataFrame(rows, columns=['season', 'team', 'p4', 'prev']).merge(cov, on=['season', 'team'], how='left') \
          .merge(rp, on=['season', 'team'], how='left').merge(rec, on=['season', 'team'], how='left')
    d['rpc'] = (d.percentPPA.clip(lower=0.) - 0.5).fillna(0.); d['prev_rp'] = d.prev * d.rpc
    d['rec_z'] = d.groupby('season').recruiting_points.transform(lambda x: (x - x.mean()) / x.std()).fillna(0.)
    co = pd.read_csv(D.data / 'preseason' / 'coaching_changes_2022_2026.csv')[['season', 'team']].assign(newcoach=1.)
    po = pd.read_csv(D.data / 'preseason' / 'transfer_portal_247_2022_2026.csv')[['season', 'team', 'points']]
    d = d.merge(co, on=['season', 'team'], how='left').merge(po, on=['season', 'team'], how='left')
    d['newcoach'] = d.newcoach.fillna(0.); d['prev_coach'] = d.prev * d.newcoach
    d['g5_prev'] = (1. - d.p4) * d.prev
    d['portal_z'] = d.groupby('season').points.transform(lambda x: (x.fillna(0.) - x.fillna(0.).mean()) / x.fillna(0.).std())
    return d


def di_ratings(D, y, lam=2.):
    sc = D.di(D.sched(y)); teams = sorted(set(sc.home_team) | set(sc.away_team)); ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
    X = np.zeros((len(sc), n + 1)); r = np.arange(len(sc)); X[r, sc.home_team.map(ix)] = 1; X[r, sc.away_team.map(ix)] = -1
    X[:, n] = (~sc.neutral_site.astype(bool)).astype(float); P = np.eye(n + 1) * lam; P[n, n] = 1e-6
    b = np.linalg.solve(X.T @ X + P, X.T @ (sc.home_points - sc.away_points).to_numpy(float))
    fcs = set(sc.loc[sc.home_division == 'fcs', 'home_team']) | set(sc.loc[sc.away_division == 'fcs', 'away_team'])
    return {t: b[ix[t]] for t in teams if t in fcs}


def fcs_prior(D, season):
    R_ = {y: di_ratings(D, y) for y in range(2021, season)}
    pairs = [(R_[y - 1][t], R_[y][t]) for y in range(2022, season) for t in R_[y] if t in R_[y - 1]]
    b_, a_ = np.polyfit([p[0] for p in pairs], [p[1] for p in pairs], 1)
    res = np.array([p[1] - (a_ + b_ * p[0]) for p in pairs])
    pred = {t: a_ + b_ * v for t, v in R_[season - 1].items()}; m_ = np.mean(list(pred.values()))
    return {t: v - m_ for t, v in pred.items()}, float(res.std()), float(b_), len(pairs)


def build_v7_prior(data, season, cache_path=None):
    """Returns (prior, info, covariates). prior has mean (FBS), s, mu_fcs, tau_fbs, tau_fcs, sigma, fcs_mean, fcs_s."""
    D = Data(data)
    cache = pd.read_pickle(cache_path) if cache_path and Path(cache_path).exists() else {}
    R = [(s, cache[s] if s in cache else ratings_for(D, s)) for s in range(2009, season)]
    carry = carryover([(s, r) for s, r in R if s != 2020])
    prev = dict(R)[season - 1]
    prior1 = prior_from_carryover(prev, carry)
    reg2 = preseason_regression(dict(R), covariates_v2(D), season)
    prior2 = {**prior1, 'mean': reg2['mean'], 's': reg2['s']}
    seasons3 = list(range(2022, season + 1))
    cov3 = covariates_v7(D, dict(R), seasons3)
    gm = pd.concat([D.sched(s) for s in seasons3 if s < season])
    gm = gm[(gm.home_division == 'fbs') & (gm.away_division == 'fbs') & gm.completed.astype(bool) & gm.home_points.notna()].copy()
    gm['margin'] = gm.home_points - gm.away_points; gm['site'] = (~gm.neutral_site.fillna(False).astype(bool)).astype(float)
    reg3 = preseason_regression_games(gm, cov3, season, V7_COLS, max_week=5, sigma_game=prev['sigma'])
    common = [t for t in reg3['mean'] if t in prior2['mean']]
    shift = float(np.mean([prior2['mean'][t] for t in common]) - np.mean([reg3['mean'][t] for t in common]))
    prior = {**prior1, 'mean': {t: m + shift for t, m in reg3['mean'].items()}, 's': prior2['s']}
    fm, fs, fb_, npair = fcs_prior(D, season)
    prior['fcs_mean'], prior['fcs_s'] = fm, fs
    info = {'carryover': carry, 'v2_regression': reg2 | {'mean': None}, 'v7_regression': reg3 | {'mean': None}, 'level_shift': shift,
            'fcs_slope': fb_, 'fcs_spread': fs, 'fcs_pairs': npair, 'prev_sigma': prev['sigma']}
    return prior, info, cov3, D
