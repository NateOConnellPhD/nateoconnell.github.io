# Margin of Merit: model and automated updates

Status, 2026-11-20: the shared NumPyro model and a private 2024 refit entry point
are in source. Numerical dependencies are not installed and no new fit has been
run. Data ingestion, LOO scoring, policy ordering, automated publication, and
the public blog section are still to be implemented. The handoff archive remains
private and unchanged. Its 2024 results are a reference example, not the limit of
the historical archive and not results from the new specification.

## One model throughout each season

For completed eligible FBS games, the response is the actual home-minus-away
final score margin, not a betting spread:

```text
margin[g] ~ StudentT(nu, theta[home[g]] - theta[away[g]] + h * venue[g], sigma)
theta[i] ~ Normal(0, 14)
h ~ Normal(2, 2.5)
sigma = 8 + exp(eta_sigma)
eta_sigma ~ Normal(log(6), 0.75)
nu = 2 + exp(eta_nu)
eta_nu ~ Normal(log(5), 0.9)
```

Normal parameters above use standard deviations. `venue` is 1 for a home game
and 0 at a neutral site. Eight points is the lower bound on the Student-t scale,
not its standard deviation. The floor is an explicit modeling assumption.

`scripts/cfb/model.py` is the single model definition. Weekly, final, historical,
and exact leave-one-game-out fits must all call it with the canonical
specification. Only the eligible data change. Every season starts with the same
exchangeable team prior; prior-season team ratings are not inputs. A previous
fit can initialize a sampler but must not become a prior when refitting all
season-to-date games, which would count earlier games twice.

Two explicitly labeled research variants are available: the archived unfloored
`log(sigma) ~ Normal(log(14), 0.5)` prior, and a broader unfloored sensitivity
prior `log(sigma) ~ Normal(log(14), 0.75)`. Neither can silently replace the
canonical model in a published week. Compare all three with the same maintained
NUTS implementation to distinguish a prior change from a sampler change. The
broader sensitivity comparison changes both the floor and the distribution;
it is not an isolated causal estimate of the floor's effect.

## Recommended deployment

Keep the website on GitHub Pages. Run Python and NumPyro's NUTS sampler in a
scheduled background job, initially GitHub Actions. JavaScript handles the
table, filters, historical navigation, and charts. It does not fit a posterior
when someone opens the page. NumPyro already provides maintained adaptive HMC:
https://num.pyro.ai/en/stable/mcmc.html

Proposed update sequence:

1. Fetch current-season results and retain the raw response's provenance. Verify
   completed status, unique game IDs, final scores, venues, and season-specific
   FBS membership. Exclude FCS games and postseason bowls/CFP under the current
   scope; include eligible conference championships and Army–Navy.
2. Compare a canonical hash of the eligible game records and roster with the last
   successful fit. Include scores, venue, eligibility, model, policy, and code
   versions. A fetch timestamp or an unfinished game's changing score must not
   trigger inference. A corrected final score or venue must trigger it.
3. When inputs change, run one four-chain fit on all eligible season-to-date
   games. Coalesce overlapping requests; never start one fit per website visitor
   or one simultaneous fit per game. Cache normalized data and dependency
   downloads; keep successful fit results keyed by their complete input identity.
4. Check rank-normalized R-hat, bulk/tail ESS, divergences, tree depth, BFMI,
   and predictive behavior. Calculate PSIS-LOO game credits, with exact LOO fits
   for unreliable cases. Apply the versioned ranking policy and audit it.
5. Publish a small JSON/CSV result only after all applicable checks pass. Retain
   the last valid ranking if an update fails and show its actual data cutoff
   and update timestamp. Do not silently substitute approximate inference.
6. Keep a changing current-season result separate from dated weekly snapshots.
   A correction creates an explicit revision; it must not silently rewrite what
   an earlier post displayed. Candidate and failed runs are not official ranks.

Start with hourly checks during relevant game windows and a daily reconciliation
for corrections. Reassess after timing a real fit and measuring provider latency.
Scheduled Actions can be delayed or dropped, so this is automatic updating after
completed games, not a guarantee of instant/live-play rankings. A dedicated
worker becomes appropriate only if measured latency makes it necessary:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub-token commits do not trigger a Pages build automatically. The eventual
publication workflow must explicitly request a build, as the existing
publications workflow does. Concurrent publication jobs must handle repository
changes without force pushing or losing unrelated edits. No CFB workflow is
enabled yet. Model computation requires no OpenAI API calls.

## Historical and live data

Use CollegeFootballData's supported API instead of scraping HTML scoreboards.
Its published coverage lists games/scores from 1869 and season calendars from
2002, while explicitly warning that coverage ranges do not guarantee every
record or field is complete:
https://api.collegefootballdata.com/data-availability

Audit **2002 through the latest completed season** first, then extend backward
as far as verified scores, venues, membership, cutoffs, and the ranking policy
support. The 2024 private fixture is the first reproducibility case. The supplied
2002–2024 CSV alone cannot establish season-specific FBS membership or conference
affiliation. Do not present every row in it as an eligible FBS game.

Historical reconstruction needs a roster for each season, including teams with
no eligible games at a given cutoff. Maintain stable IDs separately from display
names and conference changes. Historical weekly cutoffs need dated games and
completion evidence; date-only inputs must be identified as a retrospective
reconstruction, not an exact reproduction of a contemporaneous live feed.

The modern undefeated-P4 protection needs an explicit policy for older eras
(including the former Power Five). Do not project today's conferences backward.
Seasons with tied final scores require an explicit tie-credit policy before
inclusion. These are historical policy decisions, not changes to the margin
likelihood. A season with unresolved eligibility or policy stays unpublished.

The provider currently lists 1,000 calls/month on its free tier, including core
games/teams and historical data. Cache rosters and backfills; fetch a season's
games in bulk rather than making requests per team. Verify actual endpoint
access and final-score latency with the selected key before promising an update
frequency. Live scoreboard access is listed separately in paid tiers:
https://collegefootballdata.com/api-tiers

## Numerical reference run

The available local Python is 3.9 without numerical packages. The reference
environment uses Python 3.12 plus the pinned direct dependencies in
`scripts/cfb/requirements.txt`. The owner approved downloading this environment
with a 1.5 GB ceiling under `.codex-tmp/cfb-refit`, followed by cleanup after the
analysis. However, this agent session's sandbox blocked access to
`api.github.com` and execution of the app's bundled Python. Approval has been
received; the remaining obstacle is the sandbox's access rules.

The owner can perform the approved setup from Terminal:

```sh
cd /Users/noconnell/Websites/Professional_Site &&
/Applications/Xcode.app/Contents/Developer/usr/bin/python3 -B scripts/cfb/setup_environment.py
```

This creates an isolated Apple Silicon Python 3.12 installation, checks the
runtime archive's SHA-256 against its GitHub release metadata, downloads binary
dependency wheels, and checks dependency consistency/imports. It records the
runtime build and complete resolved package versions, uses no global package
installation or cache, and runs no model fits. It refuses to overwrite an
existing task directory. A failed attempt stops its child process and removes
only the directory it created. Setup monitors its owned output, stops growth at
1.2 GB to leave headroom below the 1.5 GB approval ceiling, and rejects archives
whose expanded size would exceed that working budget. The archive checks and
existing-directory preservation have offline tests; actual downloads and
numerical execution remain unverified until setup runs successfully.

The resulting interpreter is
`.codex-tmp/cfb-refit/python/bin/python3`; subsequent fits use that executable.
No installation occurs when importing or reading source.

After environment approval, `scripts/cfb/refit_2024.py` accepts the original
`2024_observed_FBS_games_used.csv` path and `--variant canonical`, `unfloored`, or
`archived-prior`. Its SHA-256 check prevents accidentally fitting a modified
reference while labeling it as the archive comparison. This fixture-specific
entry point is not the future arbitrary-season importer.

It runs four sequential NUTS chains, default 1,000 warmup and 1,000 saved draws
per chain, with float64 arithmetic. Cache and output paths are contained in
`.codex-tmp/cfb-refit/`. Each run refuses to overwrite an existing run directory.
Posterior draws retain their chain/draw axes; reports record model/source/input
hashes, seed, dependency versions, diagnostic thresholds, and predictive
summaries. Sampling diagnostics are necessary but not sufficient for publication.
The command has no publishing capability.

The required 2024 comparison remains unfinished until the LOO scorer and unified
ranking policy consume the new draws. Report changes in merit ranks, top-8/10/25
membership and probabilities, 90% merit/rank intervals, SOS, and policy-driven
ordering. Evaluate Monte Carlo error before describing small differences as
substantive. Keep model adequacy, sampling convergence, and ranking stability
separate. Do not compare latent-strength ranks as if they were merit ranks.

The archive's marginal-quantile LOO transport is an approximation to joint
dependence. Preserve and disclose that limitation in any rank uncertainty
derived using it; PSIS validity for individual games does not make the joint
rank distribution exact.
