# Quarterback-adjusted power forecasts

The authoritative source is the supplied `mom_forecast_v7 2` packet. Six source
files are preserved byte-for-byte in `scripts/cfb_forecast/reference`, with
SHA-256 hashes. The power model adds `lam * (x_home - x_away)`, with
`lam ~ Normal(1, 0.5)`. It includes that term when rescaling predictive noise.
Neither the merit model nor the preseason or home-field specifications change.

## Quarterback values and starters

The supplied Gaussian mixed model separates passer, passer-season,
offense-season, defense-season, experience, and first-timer effects. REML
variance components use seasons 2021 through the season before the forecast;
the conditional QB posterior incorporates eligible current-season games.
This follows the executable `analysis/qb_value_fit.py`: the packet's prose
description of re-estimating variance components every week is less precise.

The exact supplied covariate is the starter's value minus the team's previous
dropback-weighted passer mix, multiplied by `(dropbacks + 27*3)/(games + 3)`.
Training uses the first passer in that game. The default forecast starter is
the most recent game's first passer. No current-season history means zero
adjustment, as in the handoff. Missing play-by-play is reported, not imputed
from another efficiency measure. QB values are conditional posterior means;
the power draws propagate uncertainty in `lam`, not in those QB means.

The daily availability collector reads ESPN's league injury feed and team QB
rosters, matching ESPN athlete IDs (including IDs recovered from injury-card
links). The default keeps the incumbent unless reported out, out for the season,
on injured reserve, or suspended. Questionable/doubtful/day-to-day retains him.
An absent injury entry means “not listed,” not “confirmed healthy.”

When the incumbent is out, choose a roster-listed QB who is not reported out,
ordered by most recent game appearance, then dropbacks in that game. This is
explicitly an **inferred replacement**, not a confirmed depth chart. Receivers'
trick passes do not qualify. With no supported replacement, report that limitation
and use the usual passer mix rather than continuing to project a known-out QB.
Current observations never enter historical reconstructions or training covariates.
No team-specific manual CSV override is used.

Inside expandable matchup details, readers can choose QB-specific scenarios.
Uncertain availability enables a two-QB blend with explicit reader-selected
weights (initially 50/50, labeled as an assumption, not a probability estimate).
Mixtures combine predictions and outcome distributions; they do not just average
interval endpoints or QB covariates. Two teams' scenario weights are independent.
Published game tables always retain the default forecast.

## Daily collection and caching

The existing projections workflow runs at 13:23 UTC daily (08:23 EST / 09:23
EDT), also after relevant pushes and rankings updates. GitHub may delay a
scheduled job. July automatically selects the next season.

The collector uses the current public sportsdataverse release feeds:

- [Classic CFBD-based cfbfastR play-by-play](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/cfbfastR_cfb_pbp): `play_by_play_<season>.rds`.
- [Season schedules](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/cfb_schedules): `cfb_schedules_<season>.csv.gz`.

The [official cfbfastR loader](https://github.com/sportsdataverse/cfbfastR/blob/master/R/load_cfb_pbp.R)
uses this release, which supersedes the handoff's raw-tree RDS location. This
is the classic CFBD-based EPA feed, not the separate ESPN EPA model. Schema
changes stop ingestion rather than substituting another statistic.
GitHub's HTTPS asset redirects are supported. It uses conditional HTTP requests
and reduces one season at a time.
Historical years are also checked for corrections; unchanged bodies are not
downloaded. No CFBD request is made by the QB collector and no reader visit
makes a data request beyond static site files.

`qb_availability.py` also checks the public ESPN [injury endpoint](https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries)
and one roster per saved Division I team daily. The [provider's wrapper documentation](https://py.sportsdataverse.org/docs/cfb/reference/site/team)
documents the roster endpoint. No additional API key, paid service, or AI call is
used. Only reduced QB identities/statuses are saved to `availability.json`;
raw responses are held one at a time in memory and capped at 4 MiB. Calls are
sequential, with same-day cache reuse and a five-minute roster-refresh limit.
Three consecutive roster failures defer remaining requests. Failed sources
retain previous observations and publish a warning with their observation date.
An empty league response cannot clear previously known injuries. This free feed
may lag announcements and does not supply confirmed depth-chart order.

The reducer preserves the passer-ID repair, sacks, EPA values, garbage-time
thresholds, first-play selection and grouping. It does not replace cfbfastR
EPA with CFBD PPA. Durable JSON contains only reduced passer-game sufficient
statistics, classification, names and source observation metadata. Raw RDS/CSV
downloads live under the job's disposable directory and are deleted immediately.
One RDS is capped at 128 MiB; one schedule at 8 MiB. The workflow's existing
1.5 GB task ceiling still applies. The schedule's decompressed size is also
bounded at 8 MiB. Numerical package downloads are isolated
to that GitHub job; no dependency is added to the website runtime.

Data-content hashes, rather than check times, invalidate calculations. REML
fits are cached by historical inputs and source. A changed training QB covariate
invalidates the power fit. A starter/status-only change updates forecasts using
the saved passing fit. Publication retains the last checked forecast on failure.
`qb-status.json` reports the daily check even if no new fit is needed.

## Published interpretation

The ranked power table remains strength with the usual passer mix, preserving
the handoff's rating and rank-uncertainty definitions. The main table shows
ratings and uncertainty. Clicking a team opens its details, including the
expected QB, adjustment and current-starter power. Matchup forecasts automatically
include each expected starter's contribution in the aligned posterior draws,
probabilities, margins, intervals and plots. QB controls and status explanations
are confined to expandable matchup details. The component breakdown is
expandable inside team details. Importance compares the
incumbent with the supplied recent-backup rule; it is not a medical assessment.
Snapshots that predate QB integration are identified once at the snapshot level;
missing QB fields do not create an “Unavailable” column for every team. Source
refresh diagnostics appear under Method & accuracy → Fit details.

## Validation boundary

`test_qb.py` checks extraction, starter versus in-game mix, likelihood,
joint-draw export and cache/status boundaries without sampling or network.
`test_qb_availability.py` checks parsing, daily reuse, outages and replacement
resolution with in-memory source responses. `check_qb_scenarios.cjs` checks
weighted margins, probabilities, scores, and distribution ranges without a DOM.
`check_qb_handoff.py` replays the supplied ratings and next-week forecasts;
`--values` also reconstructs the QB-value adapter from the packet's parquet.
`check_sampling.py --week 12 --qb-covariates <packet>/data/qb/x_2026.csv`
tests the supplied historical QB covariates with the production sampler.
This historical check does not establish that a current live-source fit ran.

The unchanged six-file reference hashes and replay of 138 supplied ratings and
69 next-week forecasts passed (maximum export difference `6.4e-14`). A full
four-chain fit through week 11 using the packet's frozen week-12 QB covariates
passed: 2,000 warmup and 2,000 retained draws per chain, maximum R-hat 1.0054,
minimum bulk ESS 410.8, minimum tail ESS 1178.4, zero divergences and zero
tree-depth hits. Sampling took 86.1 seconds on the local CPU. This is a measured
historical check, not the latest window or a live-ingestion result.

Direct mirror access and dependency installation were blocked by this local
session's network proxy. Live ingestion, parquet value reconstruction and
current-window end-to-end fitting require execution in an environment that
can read those inputs. No raw handoff data or private packet is committed.
Checking daily cannot make an upstream release arrive sooner. Missing game IDs
and retained-data warnings are shown so a fresh check cannot masquerade as
complete new play-by-play. Local injury-feed checks use fixtures: the network
proxy also blocks direct ESPN requests here, so a successful live refresh must
be verified in GitHub Actions after deployment.
