# Power projections

The **Projections** tab at `/blog/cfb/#projections` is independent of the merit
rankings. It forecasts margins and win probabilities using the November 22
forecast handoff's preseason/talent/AP prior, learned prior spread, and 75/25
margin/efficiency blend. It does not use a merit reference rank, ordering rules,
earned-credit draws, or leave-one-game-out fits.

## Initial release

`scripts/cfb_forecast/import_handoff.py` reads the supplied 2026 NPZ with
`allow_pickle=False`, power CSV, run record, and aggregate backtest summaries.
It does not execute handoff code, deserialize the pickle cache, copy the private
folder, or publish embedded dashboard source. Team names are resolved against
the saved season roster and checked against division membership.

The supplied fit contains 4,000 draws and 1,395 games through November 21.
Its report has theta R-hat 1.0043 and zero divergences; full chain diagnostics
were not supplied. The page labels this provenance rather than asserting that
it passed the production pipeline's broader checks. The schedule is filtered
using the later saved feed: completed games, past unfinished games,
cancellations, and non-Division-I opponents are not shown as upcoming.

Only reviewed derived values are tracked in `_cfb_data/forecast_priors/2026.json`
and `assets/data/cfb/projections/`. The handoff remains excluded from Git.
The 2026 talent input is a mid-November snapshot; this limitation is visible.

## Updates and caching

`.github/workflows/cfb-projections.yml` runs after the existing ranking workflow
finishes, on changes to projection source/priors, or manually. It reads the
saved current FBS/FCS game feeds and exact three preceding home-history seasons.
There are **no additional football-data requests**. A failed merit LOO fit does
not prevent projections from using newly saved, valid game feeds.

The standard-library `prepare` step compares relevant inputs before installing
packages. Identical inputs cause no fit or new snapshot. A schedule-only change
reuses the saved posterior; model inputs, efficiency observations, priors, home
history, numerical package versions, and model source identify the fit cache.
Export-only changes do not invalidate that posterior. Each successful update
keeps the current fit cache and archives small public snapshot/draw files.

Production uses four sequential NUTS chains, first 1,000 warmup/1,000 retained
draws per chain, with the existing bounded 2,000/2,000 retry if needed. All
retained parameters are checked: rank R-hat ≤ 1.01, bulk/tail ESS ≥ 400, zero
divergences and depth hits, and chain BFMI ≥ 0.3. Failed fits do not replace the
index. No prediction update writes merit ranking files. The numerical job
uses the existing 35-minute/1.5-GB CI guard in its isolated runner directory.

Training uses the audited regular-season Division-I inputs, with no FCS-playoff
games. Postseason matchups are forecast from the completed regular season.
Missing postgame expectancy falls back to actual margin. Its logit-to-points
slope is learned on eligible training games only; sigma is then rescaled to
actual-margin residuals. The FCS prior mean is estimated once from the saved
previous season's completed FBS-involving games, including bowls, using the
handoff's Gaussian empirical Bayes calculation. School home offsets and their
covariance reuse the maintained three-season home-prior calculation.

The supplied preseason mean vector and its regression coefficients are frozen
for 2026, not relearned each week. **A new season requires a reviewed prior file**
with earlier training seasons, stable school IDs, and provenance. Missing
priors stop clearly; the previous season's prior is never silently recycled.

## Public calculations

- Power is centered on the mean FBS strength in each joint posterior draw.
  This does not alter pairwise differences, lines, or win probabilities.
- For home H and away A, margin location is `theta_H - theta_A + h_H`;
  neutral fields omit all home effects. The displayed home line is its negative.
- Scheduled-game win probability averages the Student-t CDF over all draws.
  It is not the probability that one team's latent strength exceeds another's.
- The browser lazily downloads one cached draw payload only on opening
  Projections. It keeps 1,000 aligned draws, five-decimal values, and two seeded
  predictive residuals per draw. Full-draw means make every hypothetical line
  agree with the full posterior. Arbitrary matchup probabilities and charts are
  thinned approximations; a scheduled matchup retains its full-draw probability.
- The expected-margin interval measures parameter uncertainty. The final-margin
  range also includes game variability. Neither is a merit interval or a
  probability of playoff selection.
- Upcoming games can be selected directly; neutral/home venue and team selectors
  work locally without requests, refits, cloud environments, or API charges.
- Forecast snapshots have their own selector. A selected historical merit week
  does not relabel the latest forecast as though it were available that week.

The supplied 2022–2025 backtest is displayed as development-period evidence.
It used shorter chains and the same seasons for variant selection, so it is not
presented as an independent prospective evaluation. Current sportsbook lines
are unavailable in the supplied feed and are not invented.

## Focused checks

`test_forecasts.py` checks analytic predictive calculations, covariance and
venue handling, the efficiency blend, invalid inputs, schedule filtering,
model log density without sampling, and publication/cache reuse with a mocked
sampler. `check_projections.cjs` checks Student-t probabilities, symmetric
neutral matchups, full-draw lines, tab isolation, chart output, and cache reuse
with an offline DOM fixture. These are not a rendered browser review or a new
season fit.
