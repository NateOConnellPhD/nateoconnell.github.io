# 2024 v2 numerical validation — 20 November 2026

The saved-data command completed the canonical fit, checked PSIS-LOO scoring,
and v2 ordering for all 134 teams and 752 eligible games. Sampling and LOO
diagnostics passed. A second invocation reused both numerical caches and
produced a byte-identical ranking candidate. No model or policy changes were
needed during this validation.

This is a reviewed local candidate, not a published website snapshot. No CFBD
or OpenAI requests, website builds, or publishing were performed.

## Inputs and reproducibility

Source commit: `7ca2407acd861a8bd44b76ef055f53893191678a`.
Inputs are the saved 2024 CFBD responses and the 16 reviewed venue corrections
described in [the input audit](CFB-2024-DATA-AUDIT.md). The saved observation
time/cutoff is `2026-11-20T20:08:34.376888+00:00`; this is a retrospective
regular-season reconstruction, including conference championships and
Army–Navy, excluding FCS opponents and postseason games.

```text
fit_input_sha256: eb45d0f24fced50d8f73267b170d045cc23f4aba9fd181b5e56b815c2af47c94
fit_cache_key: 18d50a361895269f10305eb56d574f83194490c270467f63c56187bedb4992d9
score_cache_key: ab7fd27ba5fa8b47d8c9c22803388f5645f469dc09a6b9e988c3c4f4900c7fe1
ranking_identity: 976b5ff684184c3b3a43b87b86212e59fd08f6bbae9b9accb5effb1f1722b4a3
candidate_sha256: 66f2222b9085e3a7dd6a8dc5ad1bbe6484cbce9c1b7f055ada54afebcb0126da
```

Environment: Apple Silicon CPU, Python 3.12.16 (standalone release 20261110),
NumPy 2.2.6, SciPy 1.15.3, JAX/JAXlib 0.6.2, NumPyro 0.19.0, ArviZ 0.22.0.
The canonical model retains the eight-point residual-scale floor. Sampling
used seed 20261120, four sequential NUTS chains, and 1,000 warmup plus 1,000
retained draws per chain. The v2 policy used confidence 0.90, head-to-head
bonus 0.50, common-opponent bonus 0.20, and crossing friction 0.04.

Reproduction command, after separately authorized environment setup:

```bash
.codex-tmp/cfb-refit/python/bin/python3 -B scripts/cfb/fit_saved_season.py --season 2024
```

## Numerical checks

| Check | Result |
| --- | --- |
| Maximum rank-normalized R-hat | 1.00368 |
| Minimum bulk / tail effective sample size | 3,042 / 2,393 |
| Divergences / tree-depth-limit hits | 0 / 0 |
| BFMI across four chains | 0.926, 0.920, 0.873, 1.031 |
| Maximum PSIS Pareto k / cutoff | 0.57838 / 0.70 |
| Games requiring exact LOO | 0 of 752 |
| Maximum marginal-transport mean discrepancy | 0.000179 |

Posterior mean residual scale was 13.518 (90% interval 12.667–14.330),
home advantage 3.327 (2.500–4.169), and degrees of freedom 24.392
(9.967–52.360). Observed mean margin, margin standard deviation, and fraction
of absolute margins above 28 each fell within their posterior-predictive 90%
intervals. These limited checks do not establish complete model adequacy.

All four NumPy bridge tests passed: tied-draw probabilities, separation of
official order from raw rank uncertainty, unranked no-game teams, and invalid
draw rejection. The earlier seven input and fifteen policy checks were not
repeated. Additional candidate inspection confirmed 134 unique consecutive
ranks, matching order/team rows, 752 games, passing stored diagnostics, and
top-8/10/25 probabilities summing to 8/10/25.

## Ordering results

The raw-merit top 25 remained unchanged by v2. The first ten were Oregon,
Notre Dame, Texas, Ohio State, Penn State, Indiana, Georgia, SMU, Tennessee,
and Boise State. These are regular-season results, not post-CFP rankings.

Three adjacent swaps changed six teams' official positions relative to raw
posterior-mean merit:

| Team | Raw rank | Official rank | Preference |
| --- | ---: | ---: | --- |
| North Carolina | 70 | 69 | Common opponents |
| California | 69 | 70 | Counterpart of the same swap |
| Charlotte | 99 | 98 | Common opponents |
| Florida International | 98 | 99 | Counterpart of the same swap |
| Middle Tennessee | 130 | 129 | Head-to-head |
| Kennesaw State | 129 | 130 | Counterpart of the same swap |

The internal ordering audit retained all 8,165 strong-merit pair constraints.
Oregon qualified for undefeated-P4 protection; no opposing confidence lock
needed an exception. The final objective was 4.423. The optimizer certifies
an insertion-local optimum, not a global optimum. Small preference margins
and Monte Carlo variation mean these lower-table swaps are not a claim of
seed-independent certainty.

## Cache reuse and cleanup

The first invocation reported 17.71 seconds; the repeat reported 0.74 seconds
with both `fit_reused` and `scores_reused` true. These are the runner's internal
elapsed times after input preparation and package imports, not complete
process-startup times or cloud runtime estimates.

The posterior and merit arrays and their reports retained identical SHA-256
hashes and modification times. The candidate was rewritten with identical
bytes. Thus this repeat reused HMC and LOO results; it did not perform another
fit or another LOO calculation. This checks identical-input cache reuse, not
every possible cache-invalidation case.

Observed task storage was about 546 MB, including the 533 MB environment,
below the approved 1.5 GB ceiling. The disposable environment, arrays,
candidate, logs, and library caches under `.codex-tmp/cfb-refit/` were removed
after retaining this report. Saved source data and private handoffs were
preserved. These validation caches are not a durable archive.

## Remaining work

The candidate remains `publication_ready: false`. Exact-LOO fallback for
unreliable future games, current-season input checks, pre-2024 conference
policy, durable weekly snapshots, scheduled fitting/publication, and the
public browsing interface remain separate implementation work. The missing
2026 draw/game files from the private handoff still prevent replaying its
reported results. Joint merit uncertainty continues to use the disclosed
marginal-quantile transport approximation.
