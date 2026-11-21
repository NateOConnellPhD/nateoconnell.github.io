# Margin of Merit: current rules and full-archive refit

## One methodology for every season and week

Every season from 2002 onward and every completed weekly cutoff must receive a
fresh joint FBS/FCS fit, checked LOO scoring, and the current v5 ordering. The
website must not offer old-policy replay, mix old fits into the current archive,
or merely relabel or reorder FBS-only posterior draws.

`margin-of-merit-v5-fcs-refit` identifies this migration in posterior cache keys,
public snapshots and the archive index. The separate Actions cache prefix
prevents restoration of pre-migration numerical arrays. Once a cutoff has a
checked fit from this migration, retries can reuse it; visitor requests never
run inference. Previous source and results remain recoverable through Git.

The public loader accepts only this migration's snapshots. Existing weeks are
shown as awaiting refits until replacement results pass. Previous-policy rows
are removed from the active index when it is next written. Old data files are
not used as fallback results. The supplied November 19 example is partial-week
research evidence, not a public weekly result.

## Statistical inputs and scoring

- Save the FBS roster, calendar, FBS games and FCS games per season. The first
  import uses four CFBD requests; a scheduled refresh uses two game requests.
  Historical weekly fits reuse these files. Conflicting shared game records,
  missing feeds or invalid final scores stop publication.
- Fit regular-season FBS–FBS, FBS–FCS and FCS–FCS margins jointly, with the same
  Student-t likelihood, priors, home advantage and eight-point residual-scale
  floor throughout the season. Venue corrections and weekly cutoffs are applied
  to both feeds. No model assumptions change between early and final fits.
- Use the posterior 25th-strongest **FBS** team as reference. Score games involving
  FBS teams, including FCS opponents; FCS–FCS games inform strength estimates.
  Only FBS teams appear in rankings, raw-rank uncertainty and top-K probabilities.
- Preserve inverse-likelihood PSIS weights. With the pinned ArviZ `psislw` API,
  the input is negative log likelihood. Unreliable games require checked exact
  omitted-game refits. There is no full-data scoring fallback.
- Overall W–L includes FCS games. The shared-opponent pool remains FBS-only, and
  the retained hard P4 rule still requires eight FBS wins with zero overall
  losses. It applies only against teams with two or more overall losses; a
  one-loss team may rank above an undefeated team.

## Ordering and reader controls

Freeze the raw descending mean-merit order and strict paired probabilities
`P(M_i > M_j)`. A decisive direct result or common-opponent dominance qualifies
when the opposing probability is strictly below its threshold **or** the raw
rank gap is within the proximity window. The default window is two places;
zero disables proximity. Exact equal overall records are required by default.
Any direct meeting blocks common-opponent fallback, including split series.

Subject to the retained hard requirements, optimize these objectives in order:

1. Maximize satisfied head-to-head requirements.
2. Maximize satisfied common-opponent requirements.
3. Maximize satisfied merit-protection requirements (probability at least 90%).
4. Minimize pairwise inversions of the frozen raw order.
5. Choose the lexicographically smallest stable-team-ID sequence.

Each objective is fixed before optimizing the next. No scalar weights, manual
swaps or approximate incumbent are substituted. Audits record eligibility,
actual game evidence, raw/final ranks, overridden requirements and the exact
objective. Three independent probability sliders, proximity, and record/P4
switches use saved probabilities; they do not change merit, SOS or posteriors.

The browser runs the ordering in a worker, cancels superseded work and retains
six recent settings/results in memory. Small blocks use exact subset dynamic
programming. Larger blocks lazily load the pinned HiGHS 1.16.0 JavaScript/WASM
build from jsDelivr. This path has not been runtime-verified. A failed or timed-out
calculation leaves the checked official ranking visible with an explicit error.

## Publication and complete backfill

After this source is pushed to `main`, **Update and publish CFB rankings** starts
with the latest completed current-season week. A successful job starts the
historical queue. Every old cutoff is pending under the new request identity;
the queue selects one missing fit per job and continues automatically through
2002. It initially prioritizes the latest week in each season, then works
backward across weeks, so seasons become browsable progressively.

Only closed calendar weeks can publish. Both game feeds must have been observed
past the week end. A failed sampling, LOO, optimizer or publication check stops
the affected run and preserves checked v5 results. It does not fill the gap with
old rules or skip it as complete. Resume the **history** workflow after resolving
a failed check. The 45-minute job / 35-minute numerical / 1.5 GB limits remain;
the larger joint model has not yet been timed against those limits.

## Validation actually performed

Before the source-only instruction, ten focused v5 policy tests passed, including
small-case brute-force optimality and Python/JavaScript parity. The supplied
138-team frozen-draw example also matched in both languages, including complete
decision audits and objective counts. [The replay report](cfb-v5/README.md)
records that result separately from production fits.

After the instruction, only source and Git diff review were performed. New
FCS ingestion/scoring/publication checks and migration checks were updated in
source but not run. No dependencies were downloaded, no HMC or API calls were
run, and no browser UI or larger integer-program validation was performed.
No current or historical production refit is claimed complete by this change.
