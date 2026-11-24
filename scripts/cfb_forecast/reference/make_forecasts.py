"""Frozen production model, V7LDe75: current power ratings, forecasts for upcoming games, and the draws and team detail the
explorer dashboard uses. Same model and inputs as the backtest variant V7LDe75 (see SPEC.md).

usage: python code/make_forecasts.py DATA_DIR OUT_DIR SEASON [THROUGH_WEEK] [WARM KEEP CHAINS SEED] [--qb]
  --qb: add the QB term (variant V7LDe75S; code/qb_term.py): the margin model gets lambda * (x_home - x_away), x from
  the Bayesian QB value model; upcoming games use each team's incumbent starter unless data/qb/qb_status_<season>.csv
  names another (columns team, passer_id, note). Needs runs/qb/hyper_<season>.json and data/pbp/dropbacks_*.parquet.
  Training games: regular-season D-I games of SEASON through THROUGH_WEEK (default: the last completed week), from
  DATA_DIR/<season>_DI_completed_games_current.csv (else ..._frozen.csv); postgame win probabilities from the CFBD schedule.
  Upcoming games: FBS-involved games after THROUGH_WEEK. If THROUGH_WEEK is before the last completed week, the next
  week's completed games are forecast instead (validation mode). With the backtest's sampler (250 250 2, SEED = week + 7)
  it matches the backtest's forecasts for that week within Monte Carlo error; NUTS runs are not bitwise reproducible
  across processes here (two backtest runs of 2026 week 12 differ by 0.45 points at most).
  Defaults: 1000 1000 4 2026 (4,000 draws).
Writes: <season>_power_ratings.csv, <season>_upcoming_forecasts.csv, <season>_forecast_draws.npz, <season>_team_games.csv,
        <season>_prior_table.csv, <season>_forecast_run.json"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here))
from forecast_model import fit_forecast, predict
from historical_home import load_historical, robust_history_fit, current_home_prior
from priors_v7 import build_v7_prior, V7_COLS

argv = [a for a in sys.argv[1:] if not a.startswith('--')]; QB_ON = '--qb' in sys.argv
data, out, season = Path(argv[0]), Path(argv[1]), int(argv[2])
through = int(argv[3]) if len(argv) > 3 and argv[3] != '-' else None
warm, keep, chains, seed = (int(x) for x in (argv[4:8] if len(argv) > 7 else (1000, 1000, 4, 2026)))
VARIANT = 'V7LDe75S' if QB_ON else 'V7LDe75'
out.mkdir(parents=True, exist_ok=True)
t0 = time.time()
cache = here.parent / 'runs' / 'season_ratings_cache.pkl'
prior, info, cov, D = build_v7_prior(data, season, cache)

# ---- games ----
cur = data / f'{season}_DI_completed_games_current.csv'
G = D.di(pd.read_csv(cur if cur.exists() else data / f'{season}_DI_completed_games_frozen.csv', low_memory=False))
G = G[G.season_type == 'regular'].reset_index(drop=True)
sch = D.sched(season)
if 'home_post_win_prob' not in G:
    G = G.merge(sch[['game_id', 'home_post_win_prob']], on='game_id', how='left')
last_done = int(G.week.max()); through = through or last_done
train = G[G.week <= through].copy()
if through < last_done:                                       # validation: forecast the next week's completed games
    upcoming = G[G.week == through + 1].copy()
else:
    upcoming = sch[~sch.completed.astype(bool) & (sch.season_type == 'regular')].copy()
    upcoming['neutral_site'] = upcoming.neutral_site.fillna(False).astype(bool)
upcoming = upcoming[upcoming.home_division.eq('fbs') | upcoming.away_division.eq('fbs')]
upcoming = upcoming[upcoming.home_division.isin(['fbs', 'fcs']) & upcoming.away_division.isin(['fbs', 'fcs'])]
division, conference = {}, {}
for df in (G, upcoming):
    for side in ('home', 'away'):
        division.update(dict(zip(df[f'{side}_team'], df[f'{side}_division'])))
        conference.update(dict(zip(df[f'{side}_team'], df[f'{side}_conference'].fillna(''))))
conference = {t: (c if c else 'independent') for t, c in conference.items()}

# ---- home prior: three previous seasons of FBS-vs-FBS games ----
years = [season - 3, season - 2, season - 1]
extra = data / '2025_verified_history.csv' if season - 1 >= 2025 else None
his, _ = load_historical(data / 'historical_game_scores_2002_2024.csv', years, additional=extra)
fbs_now = {t for t, d in division.items() if d == 'fbs'}
home_prior = current_home_prior(robust_history_fit(his), set(division), fbs_now)

# ---- fit: 75% final margin + 25% efficiency margin (CFBD postgame win expectancy on the margin scale) ----
pw = train.home_post_win_prob.clip(1e-3, 1 - 1e-3); train['logit_wp'] = np.log(pw / (1 - pw))
ok = train.logit_wp.notna(); mg = train.home_points - train.away_points
kk = float(np.polyfit(train.logit_wp[ok], mg[ok], 1)[0]) if ok.sum() > 30 else 4.5
train['eff'] = np.where(ok, kk * train.logit_wp, mg)
teams = sorted(set(train.home_team) | set(train.away_team) | set(upcoming.home_team) | set(upcoming.away_team))
qbx_train, QB, override = None, None, {}
if QB_ON:
    from qb_term import QBTerm
    QB = QBTerm(data, season, through, here.parent / 'runs' / 'qb' / f'hyper_{season}.json')
    qbx_train = QB.x_training(train, 'start')
    st_file = data / 'qb' / f'qb_status_{season}.csv'
    status = pd.read_csv(st_file) if st_file.exists() else pd.DataFrame(columns=['team', 'passer_id', 'note'])
    override = {t: int(pid) for t, pid in zip(status.team, status.passer_id) if pd.notna(pid)}
    qx = {}
    for t in set(upcoming.home_team) | set(upcoming.away_team):
        qx[t] = QB.x_for(t, override.get(t))
    upcoming['x_home'] = [qx[t][0] for t in upcoming.home_team]; upcoming['x_away'] = [qx[t][0] for t in upcoming.away_team]
    upcoming['home_qb'] = [QB.names.get(qx[t][1], qx[t][1]) for t in upcoming.home_team]
    upcoming['away_qb'] = [QB.names.get(qx[t][1], qx[t][1]) for t in upcoming.away_team]
fit = fit_forecast(train, teams, division, conference, home_prior, prior=prior, half_life=None, alpha=0.75, learn_s=True, qbx=qbx_train,
                   asof_week=through + 1, dynamic=True, q_scale=1.5, conf_scale=None,
                   warm=warm, keep=keep, chains=chains, seed=seed)
ix = {t: i for i, t in enumerate(teams)}

# ---- upcoming forecasts: drift grows with weeks ahead ----
rng = np.random.default_rng(seed + 1)
rows = []
for wk, grp in upcoming.groupby('week'):
    ahead = max(int(wk) - through, 1)
    th = fit['theta'] if ahead == 1 else fit['theta_last'] + fit['q_draws'][:, None] * np.sqrt(ahead) * rng.standard_normal(fit['theta_last'].shape)
    p = predict({**fit, 'theta': th}, grp, qbx=(grp.x_home - grp.x_away).to_numpy() if QB_ON else None)
    rows.append(grp.join(p))
up = pd.concat(rows) if rows else upcoming.assign(spread=np.nan, sd=np.nan, p_home=np.nan)
up['lo80'] = up.spread - stats.norm.ppf(.9) * up.sd; up['hi80'] = up.spread + stats.norm.ppf(.9) * up.sd
up['favorite'] = np.where(up.spread >= 0, up.home_team, up.away_team); up['fav_by'] = up.spread.abs()
up['fav_win_prob'] = np.where(up.spread >= 0, up.p_home, 1 - up.p_home)
keepc = [c for c in ['game_id', 'week', 'start_date', 'home_team', 'away_team', 'neutral_site', 'home_conference', 'away_conference',
                     'home_qb', 'away_qb', 'x_home', 'x_away', 'home_points', 'away_points', 'spread', 'sd', 'p_home', 'lpd', 'pit', 'lo80', 'hi80', 'favorite', 'fav_by', 'fav_win_prob'] if c in up]
up[keepc].sort_values(['week', 'game_id']).to_csv(out / f'{season}_upcoming_forecasts.csv', index=False)

# ---- power ratings (strength for next week's games, FBS) ----
th = fit['theta']; fbs_list = sorted(fbs_now & set(teams))
ranks = (-th[:, [ix[t] for t in fbs_list]]).argsort(1).argsort(1) + 1
rec = {}
for g in train.itertuples():
    hw = g.home_points > g.away_points
    rec.setdefault(g.home_team, [0, 0])[0 if hw else 1] += 1; rec.setdefault(g.away_team, [0, 0])[1 if hw else 0] += 1
tm, tsd = fit['traj_mean'], fit['traj_sd']
pr = pd.DataFrame({'team': fbs_list, 'conference': [conference[t] for t in fbs_list],
                   'rating': [th[:, ix[t]].mean() for t in fbs_list], 'rating_sd': [th[:, ix[t]].std() for t in fbs_list],
                   'preseason_prior': [prior['mean'].get(t, np.nan) for t in fbs_list],
                   'week1_strength': [tm[ix[t], 0] for t in fbs_list],
                   'strength_4wk_ago': [tm[ix[t], max(fit['n_weeks'] - 5, 0)] for t in fbs_list],
                   'strength_last': [tm[ix[t], -1] for t in fbs_list],
                   'W': [rec.get(t, [0, 0])[0] for t in fbs_list], 'L': [rec.get(t, [0, 0])[1] for t in fbs_list]})
for q, lab in ((.025, 'lo95'), (.1, 'lo80'), (.9, 'hi80'), (.975, 'hi95')):
    pr[lab] = [np.quantile(th[:, ix[t]], q) for t in fbs_list]
pr['P_rank1'] = (ranks == 1).mean(0); pr['P_top4'] = (ranks <= 4).mean(0); pr['P_top12'] = (ranks <= 12).mean(0); pr['P_top25'] = (ranks <= 25).mean(0)
pr['rank_lo80'] = np.quantile(ranks, .1, axis=0).astype(int); pr['rank_hi80'] = np.quantile(ranks, .9, axis=0).astype(int)
if QB_ON:                                                       # rating with the team's current starter, and QB tables
    lam = float(np.mean(fit['lam']))
    cur = {t: QB.x_for(t, override.get(t)) for t in fbs_list}
    pr['qb_now'] = [QB.names.get(cur[t][1], cur[t][1]) for t in pr.team]
    pr['qb_adj'] = [lam * cur[t][0] for t in pr.team]; pr['rating_qb_now'] = pr.rating + pr.qb_adj
    rows_ = []
    for t in fbs_list:
        mix = QB.S[QB.S.pos_team == t].groupby('passer_id').n.sum()
        for pid, n_ in mix.items():
            xq, _ = QB.x_for(t, pid)
            rows_.append({'team': t, 'passer_id': pid, 'name': QB.names.get(pid, str(pid)), 'dropbacks': int(n_), 'value': QB.value(pid),
                          'x': xq, 'incumbent': pid == cur[t][1], 'status_override': t in override and pid == override[t]})
    pd.DataFrame(rows_).to_csv(out / f'{season}_qbs.csv', index=False)
    QB.importance(fbs_list, lam).to_csv(out / f'{season}_qb_importance.csv', index=False)
pr = pr.sort_values('rating', ascending=False).reset_index(drop=True); pr.insert(0, 'rank', np.arange(1, len(pr) + 1))
pr.to_csv(out / f'{season}_power_ratings.csv', index=False)

# ---- each team's games: result, efficiency margin, and the margin the current ratings expect (game score) ----
hv = fit['home_values'].mean(0); hn = {t: i for i, t in enumerate(fit['home_names'])}
ths = th.mean(0)
def hedge(home, neutral):
    return 0. if neutral else hv[0] + (hv[hn[home]] if home in hn and hn[home] > 0 else 0.)
tg = []
for g in train.itertuples():
    h = hedge(g.home_team, g.neutral_site); m = g.home_points - g.away_points; e = g.eff
    for side, opp, sgn in ((g.home_team, g.away_team, 1), (g.away_team, g.home_team, -1)):
        site = 'neutral' if g.neutral_site else ('home' if sgn == 1 else 'away')
        # game score: the rating this single game implies = own margin + opponent's rating - own home edge
        tg.append({'team': side, 'week': g.week, 'opponent': opp, 'site': site, 'pf': g.home_points if sgn == 1 else g.away_points,
                   'pa': g.away_points if sgn == 1 else g.home_points, 'margin': sgn * m, 'eff_margin': sgn * e,
                   'opp_rating': ths[ix[opp]], 'home_edge': sgn * h,
                   'game_score': sgn * m + ths[ix[opp]] - sgn * h, 'game_score_eff': sgn * (0.75 * m + 0.25 * e) + ths[ix[opp]] - sgn * h})
pd.DataFrame(tg).sort_values(['team', 'week']).to_csv(out / f'{season}_team_games.csv', index=False)

# ---- prior table: each FBS team's preseason inputs and what each contributed ----
beta = info['v7_regression']['beta']; c = cov[cov.season == season].set_index('team')
pt = pd.DataFrame({'team': fbs_list}); pt['prior_mean'] = [prior['mean'].get(t, np.nan) for t in fbs_list]
has = pt.prior_mean.notna().to_numpy()                        # teams with a V7 prior (first-year FBS teams have the FCS one)
for col in V7_COLS:
    v = c[col].reindex(fbs_list).to_numpy(float); pt[col] = v
    pt[f'contrib_{col}'] = (v - np.nanmean(v[has])) * beta[col]   # so FBS average + contributions = prior mean
pt.to_csv(out / f'{season}_prior_table.csv', index=False)

np.savez_compressed(out / f'{season}_forecast_draws.npz', teams=np.asarray(teams), theta=th, home_values=fit['home_values'],
                    home_names=np.asarray(fit['home_names']), sigma=fit['sigma'], nu=fit['nu'], traj_mean=tm, traj_sd=tsd, theta_last=fit['theta_last'], q_draws=fit['q_draws'],
                    lam=(fit['lam'] if fit.get('lam') is not None else np.zeros(0)),
                    fbs=np.asarray(fbs_list), conference=np.asarray([conference[t] for t in teams]),
                    division=np.asarray([division[t] for t in teams]))
run = {'variant': VARIANT, 'season': season, 'qb_lambda': float(np.mean(fit['lam'])) if fit.get('lam') is not None else None, 'through_week': through, 'games_used': int(len(train)),
       'last_completed_kickoff_utc': str(pd.to_datetime(train.start_date, errors='coerce', utc=True).max()),
       'upcoming_games': int(len(up)), 'efficiency_scale_pts_per_logit': kk, 'prior_s': prior['s'], 's_posterior': fit['s_prev_post'],
       'drift_q_posterior': fit['q_post'], 'max_rhat_theta': fit['max_rhat_theta'], 'divergences': fit['divergences'],
       'draws': int(len(fit['sigma'])), 'sampler': [warm, keep, chains, seed], 'seconds': round(time.time() - t0),
       'prior_info': {k: v for k, v in info.items()}}
(out / f'{season}_forecast_run.json').write_text(json.dumps(run, indent=1, default=float))
print(json.dumps({k: v for k, v in run.items() if k != 'prior_info'}, indent=1, default=float))
