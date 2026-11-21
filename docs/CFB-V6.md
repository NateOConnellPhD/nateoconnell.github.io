# Rolling historical home-field model

The current model uses the supplied historical-home specification. The v5
ordering rules remain unchanged. Every season and completed week requires a
new fit; older posterior draws and published rankings are not treated as v6.

## Statistical specification

For season t, fit the home prior using exactly t−3, t−2 and t−1. The historical
likelihood uses completed FBS–FBS regular-season and conference-title games,
excluding bowls and playoff games. Membership comes from each season's CFBD
FBS roster, with stable school IDs instead of name or appearance heuristics.

Historical margins have Student-t scale 14 and degrees of freedom 12. Each
team has a separate strength in each historical season, with independent
N(0,14²) priors. A shared national home effect has prior N(2,2.5²); school
offsets have independent N(0,2²) priors. The robust MAP is calculated by IRLS.
The home block of the inverse full local information matrix marginalizes the
nuisance strengths and retains national/school correlations. This is an
**IRLS Gaussian approximation**, not a full historical HMC posterior or an
exact-Hessian Laplace approximation. Assessing its accuracy remains part of
the packet's numerical acceptance work.

Transfer only the home means and covariance. Add independent drift variances
0.25² for the national effect and 0.75² for each school. Schools with no
historical FBS evidence receive a zero-centered offset with variance 2² before
drift. No historical team strengths transfer into current-season priors.

The current-season joint FBS/FCS model is

\[
M_g\sim t_\nu\{\theta_h-\theta_a+z_g(h_0+u_h),\sigma\},
\qquad \theta_i\sim N(0,14^2).
\]

The correlated historical home distribution is a prior that current-season
data **can update**. This follows the packet's joint model; it is not its
mean-only frozen sensitivity or a modular/cut posterior. For an FCS host,
the offset is zero and only the national effect applies. Neutral sites have
zero home effect. The residual model remains
σ=8+exp(ησ), ησ~N(log6,0.75²), and ν=2+exp(ην), ην~N(log5,0.9²).

Production uses the existing four sequential NUTS chains, 1,000 warmup and
1,000 retained draws per chain. Sampling diagnostics now include the home
offsets and their non-centered latent variables. Existing Rhat, ESS, BFMI,
divergence and tree-depth gates remain in force.

## LOO scoring and presentation

The likelihood and reference-team CDF both use the actual game's host effect:
add it for the home reference, subtract it for the visiting reference. The
visiting school's own home offset is irrelevant. Exact game-deletion refits
hold the historical prior and roster fixed while reestimating current-season
strengths and home effects. The 25th-FBS reference, FCS scoring, merit bounds,
SOS, PSIS checks and disclosed approximate joint LOO transport are unchanged.

The posterior explorer adds school home offsets and total school home
advantages, with empirical distributions, means, medians and intervals.
These are full-data posteriors, like team strength; they are not LOO merit.
Public explanations do not expose internal version labels.

## Data, caching and migration

- 2026 requires actual 2023–2025 data. The packet's 2022–2024 proxy draws are
  private research results and cannot satisfy publication validation.
- `home_history_inputs.py` reads cached raw scores and season rosters. A
  missing home-history season needs two requests, one each for roster and
  games. A completely absent three-year window needs six. Existing files are
  reused; a prior-season game feed observed before the following August is
  refreshed once to establish a completed-season observation.
- Historical home fitting does not require weekly calendars. The 2002
  ranking therefore requests 1999–2001 scores/rosters, subject to verified
  data availability. It does not fabricate pre-2002 weekly cutoffs. The target
  season still uses the normal completed-week calendar rules.
- `historical_home.py` caches the prior under `.codex-tmp/cfb-refit/home`, keyed
  by historical inputs, current FBS IDs, prior specification and source.
  Weekly score changes reuse it. Corrections to history or home methodology
  invalidate it. Arrays, historical inputs and source identities also enter
  the downstream fit/publication keys.
- GitHub saves raw sources in `_cfb_data/seasons` and publishes static
  snapshots only after validation. Browsing rankings makes no football API
  requests and runs no inference. Numerical caches remain disposable.
- The new methodology marker makes every old season/week pending until its
  new fit succeeds. No source-hash bridge or old-posterior fallback is used.

## Validation scope

Local source-stage checks on November 21, 2026: 28 offline window, cache,
publication and archive-boundary checks passed; Python syntax and Git
whitespace checks passed. The real saved 2023, 2024 and 2025 input windows
loaded successfully with 750, 752 and 762 eligible FBS–FBS games respectively,
without API calls. Numerical dependencies were absent; the numerical checks
and sampler had not run at this source-review stage.

`test_home_history_inputs.py` covers exact windows, missing/proxy history,
stable cached reuse, stale observations, score/venue corrections, no-calendar
historical inputs and current host indexing. Publication tests reject proxy,
missing and changed home priors. `test_historical_home.py` checks independent
historical strengths, marginal covariance against a dense solve, correlated
priors, new schools, cache invalidation, host-specific likelihoods/CDFs and a
NumPyro model trace. The workflow runs these before producing rankings.

These synthetic checks are not evidence that a full current-season fit has
converged. Full refits, historical approximation assessment, and comparisons
of national/school effects, merit, SOS and uncertainty require actual saved
data and numerical execution. No packet proxy outputs are published by this
source update.
