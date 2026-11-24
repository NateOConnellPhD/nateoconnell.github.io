#!/usr/bin/env python3
"""Historical-only, hierarchical structural home effects for Margin of Merit.

Training target: home-field nuisance terms (global h and host u). Every
historical team has a distinct strength in each season; no historical theta is
used as an input/mean for current-season theta. No polls, recruiting, crowds,
conference power or opponent-quality weights.

Historical FBS membership: prefer externally verified season roster; supplied
archive uses documented >=5 game appearance filter, validated for 2024 fixture.
For 2026, production policy must use the actual prior seasons 2023,24,25; the
supplied 2002-2024 archive supports only the PROXY 2022,23,24 run.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix,diags
from scipy.sparse.linalg import spsolve,splu

# Verified name normalization between the two frozen naming conventions.
# Only stadium/host identity is shared, NEVER historical team-strength draws.
CURRENT_TO_HISTORICAL = {
    'App State':'Appalachian State',
    'Florida International':'FIU',
    "Hawai'i":'Hawaii',
    'Louisiana':'UL-Lafayette',
    'Miami':'Miami (FL)',
    'Sam Houston':'Sam Houston State',
    'San José State':'San Jose State',
    'South Florida':'USF',
    'UConn':'Connecticut',
    'UL Monroe':'UL-Monroe',
}

SIGMA_HIST=14.0
NU_HIST=12.0
STRENGTH_PRIOR_SD=14.0

def load_historical(path, years, verified_membership=None, additional=None):
    """Load scores; no postseason. `additional` must be an independently checked
    CSV with same columns (e.g. 2025). Never silently substitute missing years.
    """
    path=Path(path)
    raw=pd.read_csv(path)
    if additional is not None:
        extra=pd.read_csv(additional)
        raw=pd.concat([raw,extra],ignore_index=True)
    required={'season','home_team','away_team','home_points','away_points','neutral_site','postseason'}
    if required-set(raw):raise ValueError(f'Historical data missing {sorted(required-set(raw))}')
    if raw.duplicated(['season','date','home_team','away_team']).any():
        raise ValueError('Duplicate historical game rows')
    actual=set(raw.season.dropna().astype(int))
    if set(years)-actual:raise ValueError(f'Missing requested historical seasons: {sorted(set(years)-actual)}')
    out=[];audit=[]
    for season in years:
        g=raw.loc[(raw.season.astype(int)==season)&(~raw.postseason.astype(bool))].copy()
        if verified_membership is not None:
            fbs=set(verified_membership[season])
        else:
            # Season-specific FBS approximation in archived score file; never use
            # FCS's occasional one-off FBS appearance as an FBS roster member.
            n=pd.concat([g.home_team,g.away_team]).value_counts()
            fbs=set(n[n>=5].index)
        g=g[g.home_team.isin(fbs)&g.away_team.isin(fbs)].copy()
        if len(g)<100: raise ValueError(f'Only {len(g)} historical FBS games for {season}')
        for col in ['home_points','away_points']:
            g[col]=pd.to_numeric(g[col],errors='raise')
        if not np.isfinite(g[['home_points','away_points']].to_numpy(float)).all():
            raise ValueError('Nonfinite historical final scores')
        g['neutral_site']=g.neutral_site.fillna(False).astype(bool)
        g['margin']=(g.home_points-g.away_points).astype(float)
        if (g.margin==0).any():raise ValueError('Tied historical final score')
        out.append(g)
        audit.append({'season':season,'fbs_teams_inferred':len(fbs),'fbs_fbs_games':len(g),
                      'membership_source':'verified' if verified_membership is not None else 'archived >=5 games heuristic'})
    return pd.concat(out,ignore_index=True),audit


def design_historical(g):
    seasons=sorted(g.season.unique().astype(int))
    strength_names=sorted({(int(y),str(t)) for y,t in zip(g.season,g.home_team)}|
                          {(int(y),str(t)) for y,t in zip(g.season,g.away_team)})
    hosts=sorted(set(map(str,g.home_team))|set(map(str,g.away_team)))
    theta_ix={key:i for i,key in enumerate(strength_names)}
    ntheta=len(strength_names);h_ix=ntheta
    host_ix={t:ntheta+1+i for i,t in enumerate(hosts)}
    n=len(g);i=np.arange(n)
    hi=np.array([theta_ix[(int(y),str(t))] for y,t in zip(g.season,g.home_team)])
    ai=np.array([theta_ix[(int(y),str(t))] for y,t in zip(g.season,g.away_team)])
    nonneutral=np.flatnonzero(~g.neutral_site.to_numpy(bool))
    r=np.r_[i,i,nonneutral,nonneutral]
    c=np.r_[hi,ai,np.full(len(nonneutral),h_ix),
             np.array([host_ix[str(g.home_team.iloc[j])] for j in nonneutral])]
    v=np.r_[np.ones(n),-np.ones(n),np.ones(len(nonneutral)),np.ones(len(nonneutral))]
    X=coo_matrix((v,(r,c)),shape=(n,ntheta+1+len(hosts))).tocsr()
    return X,ntheta,hosts


def robust_history_fit(g,venue_sd=2.0,prior_global_h=2.0,global_sd=2.5,
                       historical_sigma=SIGMA_HIST,historical_nu=NU_HIST):
    """Robust Student-t penalized posterior mode and Gaussian Laplace moments.

    Sigma hyperparameters are prespecified research values; host SD can be
    re-evaluated using rolling held-out tests. Laplace covariance uses IRLS
    expected local information, NOT full HMC; label it as an approximation.
    """
    X,ntheta,hosts=design_historical(g)
    nparam=X.shape[1]
    m=np.r_[np.zeros(ntheta),prior_global_h,np.zeros(len(hosts))]
    sd=np.r_[np.full(ntheta,STRENGTH_PRIOR_SD),global_sd,np.full(len(hosts),venue_sd)]
    precision=(historical_sigma/sd)**2
    y=g.margin.to_numpy(float)
    b=m.copy()
    for iteration in range(80):
        r=y-X@b
        wt=(historical_nu+1)/(historical_nu+(r/historical_sigma)**2)
        H=(X.T@diags(wt)@X+diags(precision)).tocsc()
        new=spsolve(H,np.asarray(X.T@(wt*y)).ravel()+precision*m)
        if not np.all(np.isfinite(new)):raise ValueError('Historical home fit nonfinite')
        if np.max(abs(new-b))<1e-8:
            b=new;break
        b=new
    r=y-X@b
    wt=(historical_nu+1)/(historical_nu+(r/historical_sigma)**2)
    H=(X.T@diags(wt)@X+diags(precision)).tocsc()
    # Parameter block covariance computed by solving only for home columns;
    # nuisance season-specific team strengths are correctly marginalized.
    lu=splu(H)
    home_indices=np.arange(ntheta,nparam)
    E=np.zeros((nparam,len(home_indices)))
    E[home_indices,np.arange(len(home_indices))]=1
    C=historical_sigma**2*lu.solve(E)[home_indices,:]
    C=(C+C.T)/2
    ev=np.linalg.eigvalsh(C)
    if min(ev)<-1e-7:raise ValueError('Historical home covariance not PSD')
    C+=np.eye(len(C))*max(1e-9,-min(ev)+1e-9)
    home_names=['__national__']+hosts
    return {'names':home_names,'mean':b[home_indices], 'covariance':C,
            'posterior_mode_theta_historical_only':b[:ntheta],
            'residual_scale_assumed':historical_sigma,
            'df_assumed':historical_nu,
            'n_games':len(g),'n_strength_season_parameters':ntheta,
            'fit_iterations':iteration+1,'venue_sd_prior':venue_sd,
            'host_names':hosts,'historical_years':sorted(g.season.unique().astype(int).tolist()),
            'mean_abs_residual':float(np.mean(abs(r)))}


def current_home_prior(hist_fit, current_teams, current_fbs,
                       drift_global_sd=0.25, drift_host_sd=0.75):
    """Current home prior: historical posterior moments plus structural drift.
    Only FBS hosts get a school term, FCS hosts use shared national h.
    h and u are correlated through the historical estimation network.
    """
    current_fbs=set(current_fbs)
    names=['__national__']+sorted(current_fbs)
    old={t:i for i,t in enumerate(hist_fit['names'])}
    lookup=[CURRENT_TO_HISTORICAL.get(t,t) for t in names]
    if len(set(lookup)) != len(lookup):
        raise ValueError('Historical identity alias mapping is not one-to-one')
    mu=np.zeros(len(names));C=np.zeros((len(names),len(names)))
    old_cov=np.asarray(hist_fit['covariance'])
    for i,t in enumerate(lookup):
        if t in old:
            mu[i]=hist_fit['mean'][old[t]]
            for j,tt in enumerate(lookup):
                if tt in old:C[i,j]=old_cov[old[t],old[tt]]
        elif t=='__national__':raise ValueError('Missing national home effect')
        else:C[i,i]=hist_fit['venue_sd_prior']**2
    C[0,0]+=drift_global_sd**2
    C[1:,1:]+=np.eye(len(names)-1)*drift_host_sd**2
    C=(C+C.T)/2
    C+=np.eye(len(names))*1e-8
    chol=np.linalg.cholesky(C)
    return {'names':names,'mean':mu,'chol':chol,'covariance':C,
            'matched_home_school_aliases':{current:historical for current,historical in zip(names,lookup) if current!=historical and historical in old},
            'new_or_unmatched_fbs_hosts':[current for current,historical in zip(names[1:],lookup[1:]) if historical not in old],
            'history_years':hist_fit['historical_years'],
            'drift_global_sd':drift_global_sd,'drift_host_sd':drift_host_sd}


def save_history(out,fit,prior,audit,input_path):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'historical_home_prior.npz',
        names=np.asarray(prior['names']), mean=prior['mean'],chol=prior['chol'],
        covariance=prior['covariance'], years=np.asarray(prior['history_years']),
        historical_names=np.asarray(fit['names']),historical_means=fit['mean'],
        historical_cov=fit['covariance'])
    info={'historical_years':fit['historical_years'],'n_games':fit['n_games'],
          'n_season_specific_historical_strength_parameters':fit['n_strength_season_parameters'],
          'n_school_effects':len(fit['host_names']),
          'n_pooled_current_fbs_hosts':len(prior['names'])-1,
          'h0_history_posterior_mean':float(fit['mean'][0]),
          'h0_history_approx_sd':float(np.sqrt(fit['covariance'][0,0])),
          'h0_current_prior_sd_with_drift':float(np.sqrt(prior['covariance'][0,0])),
          'venue_sd_prior':fit['venue_sd_prior'],
          'drift_global_sd':prior['drift_global_sd'],'drift_host_sd':prior['drift_host_sd'],
          'history_input_sha256':hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
          'fbs_roster_audit':audit,
          'matched_home_school_aliases':prior['matched_home_school_aliases'],
          'new_or_unmatched_fbs_hosts':prior['new_or_unmatched_fbs_hosts'],
          'important':'Historical robust MAP + Gaussian Laplace covariance; not historical HMC. Historical theta not transferred.',
          '2026_is_actual_2023_2025_window':fit['historical_years']==[2023,2024,2025]}
    (out/'historical_home_provenance.json').write_text(json.dumps(info,indent=2))
    return info
