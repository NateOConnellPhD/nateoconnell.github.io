# 2024 Margin of Merit refit — 20 November 2026

The canonical eight-point scale-floor model was fitted successfully to the
private 752-game, 134-team reference fixture. Using the same maintained NUTS
sampler and corrected leave-one-game-out (LOO) scoring, its point ranks match
the archived-prior refit's ranks for **all 134 teams**. The broader unfloored
sensitivity only swaps Arizona and New Mexico at ranks 96 and 97. This supports
using one canonical specification throughout the season, but does not establish
that the floor is appropriate for every season or early-season sample.

A separate error was discovered in the saved archive's LOO calculations.
Reweighting its original draws by the **likelihood**, rather than the inverse
likelihood needed to omit a game, reproduces every saved point rank and matches
merit scores to within 0.00001255. Correcting the weights on those *same draws*
changes 44 point ranks, by at most three places. This is a scoring correction,
not an effect of the new scale prior. The supplied packet remains unchanged.

These are research results, not published website rankings. No deployment,
scheduled fetch, historical backfill, or public CFB page was enabled.

Subsequent policy update: the private v2 handoff replaces the ordering policy
used in this comparison for future production rankings. The results below
remain the original prior/scoring comparison under the archived policy; they
are not v2 rankings. See [the current integration plan](CFB.md#updated-ranking-policy-v2).

## What was held fixed

All three new fits use the shared `scripts/cfb/model.py`, the same data, team
prior, home advantage prior, degrees-of-freedom prior, and sampling settings.
Only the residual-scale parameterization/prior differs:

| Fit | Scale prior | Mean sigma | Central 90% interval |
| --- | --- | ---: | --- |
| Canonical | `8 + exp(N(log(6), 0.75²))` | 13.506 | 12.639–14.338 |
| Archived prior, new NUTS fit | `exp(N(log(14), 0.5²))` | 13.535 | 12.660–14.383 |
| Unfloored sensitivity | `exp(N(log(14), 0.75²))` | 13.529 | 12.650–14.377 |

The canonical home advantage is 3.320 points (90% interval 2.510–4.170).
Canonical mean nu is 24.484 (10.039–54.974). Sigma is a Student-t **scale**, not
its standard deviation. The sensitivity changes both the floor and the prior
distribution, so it is not an isolated causal estimate of removing the floor.

The archive's final-season policy was reproduced for this comparison: equal
FBS W–L records, observed head-to-head/common-opponent constraints, completed
neutral round-robin ordering for unresolved cases, archived cycle release,
and its explicit Oregon protection. The policy audit has 119 candidate edges,
114 applied. Each rank draw is a permutation; all active precedence constraints
hold, and posterior top-K probabilities sum to K. These checks were performed
for all five scored cases, including the two archive-draw reconstructions.

This is deliberately not a new historical conference-membership policy or a
validation of the subsequently supplied v2 ordering. Policy and sampler changes
must not be conflated with the scale-prior comparison.

## Ranking and uncertainty sensitivity

All three new fits have this top ten: Oregon, Notre Dame, Texas, Ohio State,
Penn State, Indiana, Georgia, SMU, Boise State, Tennessee. Their top-8, top-10,
and top-25 membership sets are identical.

| Canonical compared with | Archived-prior refit | Unfloored sensitivity |
| --- | ---: | ---: |
| Teams with changed point rank | 0 | 2 |
| Largest absolute merit-mean difference | 0.01315 | 0.01375 |
| Largest absolute SOS-mean difference | 0.00134 | 0.00134 |
| Largest change in 90% merit-interval width | 0.04448 | 0.05898 |
| Largest change in 90% rank-interval width | 1 place | 1 place |
| Largest change in P(top 8) | 0.83 percentage points | 0.63 percentage points |
| Largest change in P(top 10) | 0.63 percentage points | 1.05 percentage points |
| Largest change in P(top 25) | 1.38 percentage points | 1.13 percentage points |

No team-level merit difference exceeds 1.90 combined estimated Monte Carlo
standard errors in the archived-prior comparison, or 1.34 in the broader
sensitivity comparison. These small differences are not resolved effects at
this simulation precision. The comparisons use the same seed across priors;
combining MCSEs by quadrature is an approximate diagnostic, not a formal
independence claim or hypothesis test.

For scale, canonical Oregon merit is 8.639 (90% interval 7.840–9.357), while
SMU merit is 5.603 (4.913–6.252). SMU's P(top 8) is 0.335, despite its point
rank of 8. A point ranking is not a claim of certainty about that placement.

Rank intervals and top-K probabilities use the handoff's **marginal quantile
transport approximation** to cross-game dependence. Valid per-game PSIS does
not make that joint distribution exact. MCSEs of transported totals and
interval-width comparisons should be interpreted with this limitation.

## Independent check of the archive discrepancy

For ordinary LOO importance sampling, a full-data posterior draw has weight
proportional to `1 / p(y_g | parameters)`. Multiplication by `p(y_g | parameters)`
instead counts that game's likelihood again. The maintained scorer uses
`arviz==0.22.0`'s `psislw(-log_likelihood)`, whose input is log importance ratios;
see the [ArviZ API example](https://python.arviz.org/en/v0.22.0/api/generated/arviz.psislw.html).

The archived script instead calls `arviz_stats.base.array.array_stats.psislw`
with `-LL`. The packet reports arviz-stats 1.1.0. Its original numerical
environment was not executed here, so the internal library behavior/provenance
is not independently established. The saved-output diagnosis is stronger than
a guess from the function name: **positive-likelihood weights on the original
draws reproduce all 134 ranks**, while inverse-likelihood weights do not.
The two similarly named APIs must not be treated as interchangeable.

Three additional canonical NUTS fits omitted individual games completely:
the first neutral game, first home game, and largest-Pareto-k game under
`reff=1`. The table shows home-team credits; away-team credits and both SOS
quantities were checked as well.

| Omitted game | Correct PSIS | Independent exact-LOO fit | Likelihood-weighted target |
| --- | ---: | ---: | ---: |
| Georgia Tech–Florida State | 0.12739 | 0.12789 | 0.15317 |
| Nevada–SMU | -0.54629 | -0.54934 | -0.62556 |
| Virginia–North Carolina | -0.99686 | -0.99678 | -0.99348 |

All 12 checked quantities agree between correct PSIS and the omitted-game fits
within 1.07 combined estimated MCSEs. For North Carolina's away credit, for
example, correct PSIS gives 0.91901, the omitted-game fit gives 0.91898, and
likelihood weighting gives 0.86368. The exact-refit checks used independent
seeds and a ratio-estimator approximation to PSIS MCSE. They are three spot
checks, not exact refits of all 752 games. A separate conjugate-normal test
also recovers the analytically known omitted-observation mean and variance.

Holding the original archived posterior draws fixed, correcting the weight
direction has these consequences:

- The top eight remain unchanged. Boise State moves 10→9 and Tennessee 9→10.
- Syracuse moves 26→23, LSU 23→24, Tulane 24→25, and Iowa State 25→26.
- The largest merit-mean change is 0.34944, versus roughly 0.013 for the new
  scale-prior comparisons.
- Boise State's P(top 8) changes from 0.2025 to 0.3346 and P(top 10) from
  0.4757 to 0.6343. Tulane's P(top 25) changes from 0.6889 to 0.5511.
- Maximum changes in merit-interval width and rank-interval width are 0.1513
  and two places, respectively.

Comparing the *new sampler* with the original draws, both correctly scored,
produces some additional differences: up to 0.0426 in merit and 12 rank places.
The latter occurs inside an equal-record group, where the ordering policy can
amplify small changes in the completed-round-robin ordering. Those differences
are not attributable solely to the scale floor. The clean prior comparison is
the one using the same new sampler on both sides, reported above.

## Sampling checks and timing

Each full fit used four sequential float64 NUTS chains, 1,000 warmup plus
1,000 saved draws per chain, target acceptance 0.9, and maximum tree depth 10.
No parallel chains or remote compute were used.

| Fit | Fit + diagnostic seconds | Max rank-normalized R-hat | Min bulk ESS | Min tail ESS | Max PSIS k |
| --- | ---: | ---: | ---: | ---: | ---: |
| Canonical | 18.86 | 1.0041 | 2,754 | 2,208 | 0.5703 |
| Archived-prior refit | 20.14 | 1.0037 | 3,137 | 2,294 | 0.5408 |
| Unfloored sensitivity | 20.57 | 1.0044 | 2,621 | 2,211 | 0.5260 |

All full fits had zero divergences and tree-depth-limit hits; minimum chain
BFMI across them was 0.805. All three exact-LOO fits also passed these sampling
gates. All full-fit PSIS diagnostics passed the 0.7 cutoff. Scoring estimates
relative MCMC efficiency; the independent spot checks use `reff=1`, giving
a maximum k of 0.6177 for Virginia–North Carolina. These are different
diagnostic settings, not contradictory results.

The five-case scoring/ranking comparison took 45.39 seconds total. This is a
local measurement including repeated scoring, policy ordering, and reporting;
it is not a cloud-service latency guarantee or a per-visitor operation.
Import/setup, data fetching, deployment, and scheduling delays are separate.

Three coarse posterior-predictive summaries (mean margin, margin SD, fraction
with absolute margin over 28) placed observed values inside their central 90%
replicate intervals in all full fits. This is a limited sanity check, not a
complete assessment of model adequacy or out-of-sample calibration.

## Reproducibility and retained evidence

The immutable fixture SHA-256 is
`18274603de63d2b98e911538c4f304c17d8e4b79ae2bfb49bc1d9c05efa24572`.
Full-fit seed: `20261120`. Omitted-game indices/seeds: `0/20261220`,
`1/20261221`, and `423/20261643` (zero-based fixture indices).

Runtime: CPython 3.12.16, python-build-standalone release 20261110, Apple Silicon;
NumPy 2.2.6, SciPy 1.15.3, JAX/JAXLIB 0.6.2, NumPyro 0.19.0, ArviZ 0.22.0.
Runtime archive SHA-256:
`2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd`.
Direct dependency versions are pinned in `scripts/cfb/requirements.txt`.

Maintained commands are `refit_2024.py` for each of the three variants,
`compare_2024.py` for the ranking/uncertainty/forensic comparison, and
`check_exact_loo.py` for the three independent refits. The latter two accept the
private handoff directory. All refuse to overwrite their existing result
directories. `test_scoring.py` passed 12 focused mathematical/policy checks.
No website build, browser review, broad test suite, live data request, or paid
API call was part of this numerical validation.

Raw draws, intermediate CSV/JSON reports, runtime, and caches are disposable
and are removed after this report is committed. The original private handoff
is preserved. This report and the commands are the retained reviewable result;
recreating raw draws requires the private fixture and a numerical environment.

## Remaining production work

Implement and audit season-specific data ingestion/eligibility, versioned
historical policy, selective exact-LOO fallback, early-season readiness gates,
weekly snapshots/revisions, scheduled publishing, and the public blog section.
The current comparison scorer stops on unreliable PSIS rather than publishing
a result. Historical conference definitions and any tie-game policy must be
resolved before claiming support for those seasons. The numerical result here
does not by itself complete those deployment steps.
