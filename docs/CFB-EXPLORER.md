# Posterior exploration and weekly archives

The CFB page has four views: Rankings, Rules, Posterior explorer, and Week by week. Rankings contains the standings and poll comparisons. Rules contains the sliders and focused team explanations, with a button back to the resulting rankings. All reads are static site files. No reader action calls CFBD, runs HMC, or requests an external chart service.

“Explain rank” opens Rules with one opponent selected: the team immediately above the selected team, or immediately below the number-one team. Changing the team resets that nearby comparison; any other opponent can be selected explicitly. Only the chosen pair's decisions are rendered. There is no all-opponents default or list of every protected pair between their ranks. A long blocking chain shows at most eight requirements, with the complete audit available as a deliberate download.

## Statistical output

`posterior_summary.py` reads integrity-checked merit, schedule, and full-fit arrays after the existing runner finishes. It does not change the model, LOO scoring, ranking policy, or the runner's numerical cache identity. Published snapshots now include:

- Merit, raw-rank, team-strength and schedule-strength distributions by team.
- Home advantage, residual Student-t scale and degrees-of-freedom distributions.
- Means, medians, sample standard deviations, 50% and 90% equal-tailed intervals, and draw counts.
- Empirical mass functions for raw midranks and degenerate samples; otherwise 40 equal-width histogram bins spanning **all** retained draws, with no dropped tails.

Summaries use all saved draws, not bins. Continuous CDFs interpolate within histogram bins and are labeled accordingly. Comparison plots use density so different bin widths are not confused with different probabilities. Degenerate distributions are identified as point masses, never continuous densities. Raw ranks use midranks for tied draws; existing top-K probabilities allocate tie probability fractionally.

Merit, schedule and raw-rank uncertainty retain the existing marginal-quantile LOO approximation. Strength and model parameters use the full-data posterior. Both distinctions are explicit. Sliders affect ordering only. Legacy snapshots lacking distributions show an unavailable message; no posterior is invented from their intervals.

The explorer exposes top-8/10/25 probabilities, actual paired merit probabilities, sampling diagnostics and exact-LOO counts. Pairwise merit probabilities are not future game-win probabilities. CSV exports include medians, SDs and raw-rank means.

## Historical fitting

After a successful current update, `cfb-rankings.yml` explicitly dispatches its `history` mode. It reuses saved season data, fetching missing seasons once (three requests per missing season), and enumerates closed regular-season weeks from 2024 onward. One worker handles one missing or stale week, initially favoring the latest closed week in each year so all seasons become browsable early.

Every fit uses only games through that week's calendar cutoff, the same model and scoring, and the usual MCMC/LOO/publication checks. It never reconstructs early rankings from the final-season posterior. Successful workers save immutable JSON/CSV snapshots and compact `seasons/YEAR/history.json` files, commit, and dispatch the next worker. The queue stops when complete or on failure. Resume through **Update and publish CFB rankings → Run workflow → mode: history**. Scheduled current updates also resume it.

There is one numerical worker at a time, with the existing 35-minute numerical limit and 1.5 GB disposable-directory ceiling. No new fits or dependency downloads ran during this implementation. Total backfill time has not been measured.

GitHub permits explicit `workflow_dispatch` calls using `GITHUB_TOKEN`; `actions: write` is granted for this. See [GitHub's token documentation](https://docs.github.com/en/actions/concepts/security/github_token). The finite missing-week queue and checked snapshot reuse terminate the dispatch sequence.

Coverage begins in 2024 because the specified undefeated Power Four rule assumes that conference era. Earlier seasons need an explicit historical conference policy. Reconstruction labels describe observed final scores filtered by historical kickoff/week cutoffs; they do not claim those rankings were published then or that exact historical final-status timestamps were archived.

## Browsing and comparisons

Primary navigation is **Season → Week of season**. The selected season's week grid is always visible, with one entry per week and missing fits explicitly marked. Changing seasons opens its latest available week; selecting a week opens its latest saved version. Earlier versions of that same week remain in a separate expandable selector. Links with `?season=2025&week=8` open that week's latest version; existing `snapshot` links still open the exact saved version. A requested week without a fit shows an unavailable state, never another week's rankings.

Public labels show weeks and dates (using America/New_York for a consistent date), without times of day. Exact timestamps and internal model identifiers remain in saved data for reproducibility. Public rule labels omit implementation version numbers. The rankings page uses the supplied 1671 × 696 banner at `assets/images/margin-of-merit-banner.png`, links to the CFB blog post for the full model and rationale, and provides an on-page plain-language guide to every column, posterior summaries, plots, controls, weekly trajectories, and diagnostics.

CFB styles and scripts share a build-time URL revision so new markup does not reuse older cached assets. The header image has no fixed HTML height; it retains its intrinsic proportions even before the CFB stylesheet loads.

Season trajectories use the latest snapshot per week, preserve gaps, and break official-rank lines when ordering policies change. Weekly movement requires the immediately preceding week with the same policy; another revision of the selected week or a more distant week is never a substitute. The ranking table puts movement last and shows arrows, an explicit zero for unchanged teams, New for a first ranking, or N/A with an explanation. Sliders apply the same selected rules to both weeks; a conflicting previous-week ordering makes movement unavailable without hiding the selected week's results. Snapshot season/week metadata must agree with the archive index before display.

## AP and CFP comparisons

Choose AP Top 25 or CFP, then a saved poll edition. Poll rank and the signed difference (`poll rank − displayed merit rank`) appear beside the team. Positive means higher in Margin of Merit; NR is outside the poll's Top 25, never an invented rank 26. An unavailable edition shows N/A, not NR. The Top 25 view includes teams in either ranking; poll rank and the difference are sortable. Weekly movement remains the far-right column and is independent of the poll comparison.

The [CFBD rankings endpoint](https://api.collegefootballdata.com/api/rankings) supplies season type, poll week, final flag and team IDs, but no release timestamps. The UI preserves those labels and suggests the regular-season poll week following the completed game week. This is an explicit, adjustable suggestion, **not verified release-date matching**. Missing suggestions never silently substitute another edition. All saved regular/postseason/final editions can be selected; final/postseason polls can reflect games excluded from this model. CFP may be unavailable early in a season or absent from the provider's current-season coverage. No claim of a matching information cutoff is made.

`sync_polls.py` uses one `/rankings?year=YEAR&seasonType=both` request per refreshed season. It validates IDs against the saved season roster (exact names only for older responses lacking IDs), preserves tied ranks and final editions, and rejects disappearing editions or malformed responses before replacing saved files. Raw responses with provenance live at `_cfb_data/seasons/YEAR/polls.json`; compact public editions at `assets/data/cfb/seasons/YEAR/polls.json`. Polls do not enter model inputs, fit keys or historical reconstruction queues.

The [CFBD Poll and PollRank schemas](https://api.collegefootballdata.com/api/~schemas#poll) allow null `isFinal` and `rank` values. Only explicit `isFinal: true` receives a final label; null or a legacy omitted flag means no final label. Null ranks and positions beyond 25 are excluded from the Top 25 comparison. Missing or malformed rank values still fail validation. The raw cached response retains the provider's null values unchanged. Invalid final flags or rank arrays identify the season, week and poll in the error.

The separate **Update AP and CFP comparisons** workflow runs after a source push and can be run manually. Scheduled refreshes are Sunday 5:17 p.m. Eastern in August–December and Wednesday 8:17 a.m. Eastern in November–December, with a February 1 archive refresh. It uses the existing `CFBD_API_KEY` secret and standard-library Python; no numerical installation or HMC. Initial sync fetches each already-saved season once; polls fetched after February 1 of the following year are thereafter reused. Active-season repeats within six hours reuse the cache. The browser fetches a static poll file only when a reader enables comparison and reuses it across weeks and poll choices. It never calls CFBD. Scheduled Actions must succeed and the site must rebuild before newly cached polls are visible.

Offline checks cover edition identity, ties, missing CFP, invalid/ambiguous records, source integrity, cache reuse and failure preservation; controller fixtures cover weekly selection and poll comparison without rendering a browser. They do not establish live API access or provider completeness.

## Validation and limitations

The season/week navigation has an offline controller check in `scripts/cfb/check_navigation.cjs`: week grouping (including week zero), revision selection, switching seasons, pending fits, exact and weekly links, and reuse of loaded snapshots. It uses a minimal DOM stub, not a rendered browser.

Performed locally:

- 3 distribution-summary tests: skewness, means/medians, ties, tail mass, quantiles and invalid samples.
- 4 history tests: closed weeks, reconstruction reuse, per-week revisions, and cutoff propagation into loading and fitting (fit mocked).
- 12 targeted publication tests, including LF-only CSV and preservation of existing snapshots.
- 2 saved-data cutoff tests: championship/Army–Navy handling and exclusion of future results while retaining the full roster.
- JavaScript syntax, HTML IDs/labels/panel references/control selectors, workflow YAML parsing, and Git whitespace checks.

The authorized rendered review was blocked: the browser tool failed to start, localhost bind was denied, and installed headless Chrome exited with SIGABRT. No desktop/mobile visual pass is claimed. The numerical array-to-export bridge and remote Actions chain were source-reviewed, not executed. Synthetic review fixtures were never placed in public data and were removed. The local public index was empty at the start; source changes do not establish that live or historical fits have completed.
