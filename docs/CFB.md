# Margin of Merit: model and automated updates

Status, 2026-11-20: the three 2024 refits and independent LOO spot checks are
complete. The canonical and archived-prior refits have identical point ranks
for all 134 teams. A separate likelihood-weighting error was identified in the
saved archive; it must not be attributed to the new scale floor. See
[the numerical comparison](CFB-2024-COMPARISON.md) for results and limitations.
Maintained source now includes PSIS scoring, a reference ordering policy, and
comparison commands. A manual CFBD data-sync workflow is implemented and has
passed offline checks; live API access has not yet been tested. Exact-LOO
fallback, historical policy, scheduled updates, automated publication, and the
public blog section remain unfinished.
The updated private Margin of Merit v2 handoff has also been reviewed. It
replaces the intended production ordering policy, not the statistical model or
data importer. Its policy is specified below but is not yet integrated into the
maintained production code. Both handoffs stay private and unchanged; 2024 is
a reference, not the limit of the historical archive.

## First GitHub data sync

The owner has saved `CFBD_API_KEY` as a repository Actions secret. The workflow
reads it only through its environment; do not put the key in source or data files.
After pushing the source, open:
https://github.com/NateOConnellPhD/nateoconnell.github.io/actions/workflows/cfb-data.yml

Select **Run workflow**, use branch **main**, leave the season at **2024**, and
leave **Refresh the saved FBS team list and calendar** unchecked. Start the run
and inspect its summary. This checks the connection and saves data; it does not
run inference, publish rankings, or enable a schedule.

The first successful sync makes three API requests and commits four files under
`_cfb_data/seasons/2024/`:

- `teams.json`: the season-specific FBS roster and source provenance.
- `calendar.json`: the season calendar and source provenance.
- `games.json`: the season's returned game records and source provenance.
- `normalized.json`: normalized records, exclusion reasons, validation counts,
  and an eligible-data hash for the future model pipeline.

These are public football data saved in the repository, not the private handoff.
The data directory is excluded from the Jekyll website. Each source envelope
records its endpoint, query, retrieval time, and payload hash. A byte-identical
payload retains its original envelope rather than creating a timestamp-only
commit; the workflow log records the later check.

Later runs for that season reuse the saved roster and calendar and make only
**one games request**. Explicitly refreshing metadata adds two requests. The
importer validates the complete response before writing files, rejects missing
previously eligible final games, and does not commit a failed sync. It retains
scheduled/non-final games for inspection but excludes them from model inputs;
changing an in-progress score does not change the eligible-data hash. That hash
is not a complete fit identity: future fit caching must also include model,
policy, and implementation versions.

After the 2024 import succeeds, compare its eligibility and game set against the
reference before connecting inference. Use a separate manual run for season
**2026** to seed current-season files; that season's first run also needs three
requests. The eventual Sunday job will reuse these saved inputs. Visitors will
read published result files and will never call CFBD.

The importer uses Python's standard library, with no runtime or dependency
downloads. Its 13 focused offline tests cover request reuse, unchanged data,
corrections, rejected responses, input eligibility, and credential-safe errors.
Those checks do not establish that the real provider response or key works.

## Updated ranking policy: v2

The private `Margin_of_Merit_2026_Uncertainty_Ranking_V2` packet supersedes the
old hard head-to-head/common-opponent precedence and completed-round-robin
reordering procedure for future publication. `reference_policy.py` remains
only to reproduce the completed 2024 prior comparison; do not use it as the
production sorter. The comparison's numerical results have not been recomputed
under v2.

The v2 likelihood and priors match `model.py`, including the eight-point scale
floor. Its intended LOO game credit, season merit, and SOS definitions also
remain unchanged. The saved-data workflow can run independently of this policy
update, and a policy-only change does not itself require another HMC fit.

The intended official order is:

1. Start from decreasing posterior mean earned merit.
2. Protect pairwise merit precedence when its posterior probability is strictly
   greater than 90%. Exactly 90% is eligible for consideration, not an instruction
   to reverse a comparison.
3. Consider head-to-head first, then unambiguous common-opponent dominance, only
   for identical FBS win-loss records and unresolved merit comparisons. Split
   direct results do not create a direct preference. Common-opponent comparisons
   use win fractions, with no worse results against every shared opponent and
   strictly better results against at least one.
4. Treat those comparisons as finite preferences, not forced swaps. Reversing a
   baseline pair costs `max(0, 2*p - 1) + epsilon`, where `p` is the posterior
   probability that the baseline-higher team has greater merit. Every crossed
   team contributes a separate cost and its own confidence constraint.
5. Retain the separately disclosed undefeated-P4 exception: at least eight FBS
   games, no FBS losses, and precedence over teams with at least two FBS losses.
   Its historical conference policy still needs resolution.

The handoff's provisional editorial weights are 0.50 for head-to-head, 0.20 for
common-opponent preferences, and 0.04 per crossing. They are policy choices, not
estimated model parameters or probabilities. Its deterministic best-insertion
search evaluates every single-team insertion and stops at an insertion-local
optimum; it does not certify a global optimum.

Keep the official integer order separate from uncertainty about raw merit.
Rank intervals and top-K probabilities come from raw merit draws, not applying
the selected editorial rule to each draw. Public labels must say, for example,
`P(raw merit in top 8)`. These quantities retain the known approximate joint
dependence from per-game marginal quantile transport.

Integration/replay checks still needed:

- The supplied folder and ZIP contain policy code, tests, and result tables,
  but not the referenced `2026_merit_draws.npz` or
  `2026_FBS_completed_games.csv`. Reported 2026 rankings, weight sensitivity, and
  replay-test results have therefore not been independently reproduced here.
- Keep the maintained, checked LOO scorer. The new standalone runner uses the
  same `arviz_stats...psislw(-LL.T)` call pattern as the earlier archive. That
  alone does not establish its target or invalidate its outputs, but the earlier
  scoring discrepancy makes a numerical check necessary before reusing them.
- Explicitly handle tied merit draws, including teams with zero eligible games:
  the supplied pair matrix sets the reverse probability to `1 - P(A > B)`,
  which treats equality as strict superiority in the reverse direction.
- Check confidence locks in both directions even if mean and probability order
  disagree, and test feasibility when the P4 exception crosses an intermediate
  team's confidence lock. Do not silently relax an unrelated lock.
- Use the cached season-specific roster/conferences and stable IDs. Do not copy
  the standalone runner's team roster inferred only from completed games, its
  2026-specific filenames, or its separate data downloader into production.

Do not publish the packet's superseded hard-precedence tables. Its v2 tables
are reference material pending the checks above, not verified live output.

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
table, filters, historical navigation, and charts using saved result files.
Visitors never call the football-data API or trigger inference, including when
they select another season, week, or team. NumPyro provides maintained adaptive HMC:
https://num.pyro.ai/en/stable/mcmc.html

Persist the game data used by the fits, season-specific rosters/conferences,
data provenance, and validated weekly ranking/uncertainty summaries as versioned
files. Store model/policy versions, diagnostics, and explicit data cutoffs with
each result. A small index lists available seasons/weeks and points to the
latest valid snapshot. "Current" and "Historical" use the same saved results;
current means the latest successful **weekly** update, not live-game rankings.
These durable inputs/results must not depend on expiring Actions artifacts or
dependency caches. Large posterior arrays are not needed to browse the site.

Backfill missing historical inputs once, verify any reusable supplied data,
then compute historical weekly results once using only games available at each
cutoff. Browsing and scheduled current-season updates must not fetch or refit
completed historical seasons. Historical corrections or methodology revisions
are explicit maintenance operations with labeled result revisions.

Proposed update sequence:

1. Once each Sunday morning after Saturday's games, make one bulk current-season
   games request and retain the response and query provenance. The documented
   `/games` endpoint accepts a year with no week filter and returns a game array:
   https://api.collegefootballdata.com/api/games
   Refresh the season's saved game file so the same request captures newly
   completed games and corrections to earlier scores. Cache season metadata
   separately; initial roster/calendar setup and explicit error retries are
   additional calls, not visitor-driven requests. Verify
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
6. Advance the current-results pointer to the newly validated weekly snapshot.
   A correction creates an explicit revision; it must not silently rewrite what
   an earlier post displayed. Candidate and failed runs are not official ranks.

The owner selected a weekly Sunday refresh instead of hourly/daily polling.
With season metadata already stored, the normal in-season schedule uses one
games request per week (roughly four or five per month). If eligible data have
not changed, keep the prior result and skip inference. No routine off-season
polling or historical refresh is needed. Sunday/Monday games and provider-late
results enter the following scheduled update unless an explicit extra refresh
is requested; the page must show the actual cutoff instead of claiming a week
is complete. Allow an owner-triggered refresh for those exceptions/corrections.
The workflow's selected Sunday hour must specify its time zone. Scheduled
Actions can be delayed or dropped, so preserve the last valid result and its
timestamp if no successful update is available:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub-token commits do not trigger a Pages build automatically. The eventual
publication workflow must explicitly request a build, as the existing
publications workflow does. Concurrent publication jobs must handle repository
changes without force pushing or losing unrelated edits. The data-sync workflow
is manual only; no automatic CFB schedule is enabled yet. Model computation
requires no OpenAI API calls.

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
analysis. The owner ran the bootstrap from Terminal because this agent
session's sandbox blocked the runtime download. Installation and numerical
execution subsequently succeeded. Task-owned runtime/results are cleaned
after analysis; the retained results are in the comparison report.

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
existing-directory preservation have offline tests. Actual setup, imports,
dependency consistency, and the numerical reference fits have now succeeded.

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

`scripts/cfb/compare_2024.py` consumes the three new fits and the original
archive draws. It reports merit ranks, top-8/10/25 membership and probabilities,
90% merit/rank intervals, SOS, Monte Carlo error, and policy-driven ordering.
It holds the archived final-season policy fixed to isolate the prior comparison;
this reference policy is not the future general historical policy.
`scripts/cfb/check_exact_loo.py` independently omits three selected games and
refits the canonical model. `scripts/cfb/test_scoring.py` includes an analytical
normal-model check that catches reversed importance weights. Both comparison
commands accept the private handoff directory and write only to the approved
task directory. Neither publishes. Keep model adequacy, sampling convergence,
and ranking stability separate; latent-strength ranks are not merit ranks.

The archive's marginal-quantile LOO transport is an approximation to joint
dependence. Preserve and disclose that limitation in any rank uncertainty
derived using it; PSIS validity for individual games does not make the joint
rank distribution exact.
