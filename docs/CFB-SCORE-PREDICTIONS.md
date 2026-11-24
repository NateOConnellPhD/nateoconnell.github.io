# Individual final-score predictions

The supplied QB-adjusted power/margin implementation is unchanged. This is a
separate, explicitly new **conditional scoring extension**, not a claim that the
handoff already contained a team-score model. It is not a sportsbook model.

## Statistical specification

First draw a margin `M = home points − away points` using the existing power,
venue, QB, weekly drift and Student-t game-noise draws. The scoring extension
models `L`, the lower of the two final scores, conditional on `|M|`:

```
L | M, parameters ~ Normal(mu, s²), truncated to [0, infinity)
mu = alpha + season_effect + team_season_home + team_season_away
     + beta * (|M| − 14) / 14

alpha ~ Normal(20, 10²)
beta ~ Normal(−3, 6²)
season_effect ~ Normal(0, 3²)
team_season ~ Normal(0, 5²)
log(s) ~ Normal(log(10), 0.5²)

home points = L + max(M, 0)
away points = L + max(−M, 0)
```

All priors are independent. The slope prior allows either direction; it does
not force large-margin games to have a particular total. School-season effects
describe the shared scoring environment, not separately identified offense and
defense. They are independent across seasons: a new season's school effects
start pooled toward zero, with prior uncertainty. Historical games identify the
shared baseline, margin relationship and residual variability. The current
season updates its own school effects. Pooling scales are specified assumptions,
not estimated hyperparameters.

The factorization is modular: `p(M | margin data) × p(L | |M|, score data)`.
Score data do not feed back into the supplied margin posterior. This deliberately
preserves the requested power ratings and win probabilities, rather than claiming
a fully joint refit of the original handoff. Actual final-score differences are
the conditioning covariate during scoring training; simulated final margins are
used during prediction. There is no future outcome covariate at prediction time.

Every simulated score pair has exactly the original simulated margin and winner.
Means, medians and 80%/95% equal-tail **predictive** ranges include both parameter
uncertainty and game variation. They are not confidence intervals for the mean
score. Marginal score intervals cannot be subtracted to obtain margin intervals.
Scores are continuous approximations, like the supplied margin distribution;
they do not enumerate football's discrete scoring plays or overtime rules.
Displayed whole-point predictions round each mean separately. Medians and rounded
means need not imply the reported mean margin; finite simulation adds small
Monte Carlo differences too. A rounded tie does not mean 50/50 win probability.

## Inference and checks

`scores.py` optimizes the proper truncated-normal log posterior and uses its
observed Hessian for a Laplace approximation. The normalization term is included
in the likelihood, gradient and Hessian. This is **approximate Bayesian inference**,
not HMC and not the original handoff's sampling diagnostics. Publication requires
optimizer convergence, maximum absolute gradient below 0.001, finite values and
positive-definite full and exported posterior covariance. No Hessian jitter or
relaxed thresholds turn a failed approximation into a passing fit.

The current-season marginal covariance retains dependence among both teams,
baseline, slope, season effect and residual log scale. A deterministic independent
draw stream combines that posterior with the existing 1,000 aligned margin
draws and two game-noise replicates (2,000 paired outcomes per matchup).
Inverse-survival sampling keeps truncation stable for very negative latent means.
The browser uses the same exported coefficients, uniforms and margin noise as
scheduled predictions. QB, venue and horizon controls recompute paired scores
locally. Neither the scoring model nor its browser export changes the supplied
six reference source files.

These are new modeling assumptions. Numerical checks do **not** establish
out-of-sample calibration. The existing historical accuracy panel evaluates the
older margin model, not these team-score intervals. A future rolling-origin
evaluation should assess each team's score error and 80%/95% predictive coverage,
including season phase and FBS/FCS matchups. No separate possession, weather or
injury model is implied. QB/venue scenarios enter through the margin only.

## Pullable data, daily refresh and caching

No new endpoint, key, private handoff file or manual input is required. Each
validated current-season game already contains both final scores. The preceding
three seasons' FBS–FBS games are already stored for the home-advantage estimator.
The scorer uses those validated game IDs to recover their separate scores from
the same saved CFBD response and verifies IDs and margins. Cancelled, unfinished
and excluded games cannot enter through an unfiltered raw season. Current-season
Division I games come from the same eligible, cutoff-filtered list as the power
fit. Previous seasons' FCS-only games are not assumed available.

Historical forecast windows use the power loader's earlier-week/kickoff cutoff;
the scorer never loads later current-season results. These are reconstructions
from saved results, not proof of historical provider availability at the time.

The existing daily workflow collects changed final scores and recomputes as
needed. Score-only corrections that leave the margin unchanged invalidate the
score publication and fit, but not the power fit. Schedule/QB-status-only changes
reuse the scoring fit. Its key includes actual score pairs, seasons, team IDs,
source and numerical versions; check timestamps alone do not invalidate it.
Only the latest passing disposable score cache is kept. A failed score fit stops
publication before writing a new snapshot; the previous forecast stays available.
The next season uses the existing automatic rollover and data-readiness checks.

All public pages load static, content-addressed JSON. Browsing, comparing teams
and changing a QB make no football-data or model API request and run no fit.
Older snapshots remain available and explicitly say when individual scores are
absent, rather than inventing missing results.

## Local validation, November 23, 2026

Eight focused numerical/data checks passed: truncated-normal likelihood,
finite-difference gradient/Hessian agreement, synthetic parameter recovery,
cutoff selection, score-only correction/cache behavior, paired-score invariants,
Python/JavaScript agreement (including extreme tails and QB/horizon scenarios),
and invalid-input rejection. A separate mocked-publication check passed for
idempotence and reusing the margin fit after schedule or score-only changes.
That check did not run HMC.

The scorer also fit the saved 2026 window through week 12 using 3,736 games
(1,472 current-season Division I games plus preceding-season FBS history).
One Newton refinement after L-BFGS reduced the maximum gradient to
`3.07e-7`; the full Hessian and exported covariance passed Cholesky checks.
Loading, fitting and preparing 1,000 draw sets took about 0.74 seconds locally;
the score draw JSON was about 3.1 MB. These measurements are not a guarantee
for GitHub's runner. No power refit, live API, dependency download, website
publication or browser/UI test was performed. Temporary output was removed.
