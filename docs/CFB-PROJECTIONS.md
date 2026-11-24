# Game projections

`/blog/cfb/#projections` is independent of earned-merit rankings. The predictive
specification is the frozen `V7LDe75` handoff, represented by `ForecastConfig`.
The public interface separates power ratings, game projections, and merit rankings.
The implementation audit is in [CFB-FORECAST-PORT-AUDIT.md](CFB-FORECAST-PORT-AUDIT.md);
the supplied model and historical estimator are executed directly from unchanged source.

## Model and data

- Preseason FBS means: OLS on early regular-season game margins from earlier
  seasons, using the eleven specified covariates. The older three-input
  regression supplies the prior spread and level alignment only.
- FCS priors: team deviations from prior-year full-Division-I ridge ratings,
  with a separate carryover slope and residual spread.
- Weekly latent-strength random walk with HalfNormal(1.5) step scale.
- Learned preseason spread, exchangeable conference effects, Student-t noise
  with the same eight-point scale floor, and the 75/25 margin/expectancy blend.
  Sparse windows (at most 30 usable probabilities) use the specified 4.5 slope.
  Expectancy comes from the FBS schedule; FCS-only games use actual margins,
  matching the supplied product instead of expanding the efficiency target.
- Home-field joint covariance comes from exactly three previous seasons.
- Week 1 uses the specified Gaussian prior approximation. Later windows use
  four sequential NUTS chains with 2,000 warmup/retained draws per chain and
  target acceptance 0.97, then a 4,000/4,000 attempt at 0.99 if
  diagnostics fail. The model and publication thresholds are unchanged.
  The identically-zero first-week walk coordinate is excluded from R-hat;
  every stochastic parameter is checked. JAX caches clear after each attempt.
- Postseason projections cover identified CFP games only. Unknown playoff
  labels and non-CFP bowls are not assumed to be playoff games.

`priors.py` is the single annual prior builder. `fit_window` in `publish.py`
serves current refreshes and historical forecast windows. Historical windows
must contain only earlier weeks and kickoffs strictly before the first game
being forecast. Postponed games that violate that condition fail explicitly.
No variant-string alternative models run in production.

## Evidence and availability

`_cfb_data/forecast_inputs/evidence.json` contains reviewed numeric preseason
inputs and historical rating summaries; `forecast_priors/2023.json` through
`2026.json` are their generated priors. These directories are excluded from the
website build. `import_v7.py` extracts only allowlisted numerical evidence from
an explicitly supplied handoff, checks the frozen prior, and recalculates the
accuracy summaries. The legacy cache reader only permits NumPy numeric scalars
and dtypes; no handoff script or arbitrary pickle object is executed.

The supplied covariates start in 2022, so the first supported forecast season is
2023. Do not fabricate portal data for 2002 or use the previous model as a
substitute. [CFBD coverage](https://api.collegefootballdata.com/data-availability)
lists talent from 2015, returning production from 2014, and portal data from
2021. Availability of a dataset does not establish complete team coverage or
that CFBD player-level portal data reproduce 247 team portal points.

The new 2026 CFBD returning-production and recruiting inputs are supplied;
Connelly/ESPN percentages are not substituted for CFBD offensive PPA shares.
Negative CFBD returning PPA shares are clipped at zero as specified. Missing
returning production and recruiting covariates use the specified league-average
values. Missing previous FBS strength gives no FBS team-specific prior.

Known limits:

- The supplied 2026 talent snapshot was collected in November. Coaching changes
  were collected in February. These are not perfect frozen preseason inputs.
- The 2026 product NPZ reports two divergent transitions and retains only partial
  diagnostics. It is **not imported as a validated production fit**. The older
  website fit remains available as an explicitly labeled earlier-model archive.
  The corrected supplied-code 2026 refit on November 23 passed all checks with
  8,000 retained draws: zero divergences/tree-depth hits, maximum R-hat 1.00796,
  minimum bulk ESS 489.21, minimum tail ESS 697.13, and minimum BFMI 0.87786.
  Sampling took 89 seconds locally, excluding diagnostics. It is saved in the
  public projections archive. The original 4,000-draw settings
  had zero divergences in the local reproduction but poor drift-scale mixing
  (q R-hat 1.02334, ESS 197.91); increasing target acceptance alone did not fix it.
  The supplied file lacks transition-level flags, so its two original divergent
  trajectories cannot be located retrospectively. New reports retain chain/draw
  positions, scale contexts, acceptance and step-size summaries, including on
  failure. The model and diagnostic thresholds were not changed.
- Current saved feeds support forecasting for 2025–2026. Fresh historical refits
  for 2023–2024 need their missing saved FCS feeds (and 2023 also needs 2020 home
  history). The supplied 2023–2025 evaluation is available without those refits.
- Future seasons assemble their inputs automatically beginning in July. The
  first forecast waits for complete source coverage (including the preseason AP
  poll) and the August home-history boundary. Missing data are reported, never
  replaced by another season or a different model.
- No injury or player-availability inputs. No play-by-play downloads are needed
  for the retained postgame-expectancy target.

## Publishing and caching

`Update CFB projections` runs daily at 13:23 UTC, follows the rankings workflow,
and runs when its own source changes. Daily requests use the existing
`CFBD_API_KEY` repository secret. The shared `cfb-data` concurrency group
serializes it with rankings and data collection. No secret enters static JSON.

The daily collector checks games, roster/calendar, talent, CFBD offensive
returning PPA, recruiting points, preseason AP votes, 247 transfer-team points,
and coaching records. It retains the handoff's definitions: AP includes others
receiving votes (the total must equal 325 times the ballot count); the complete
College Poll Archive table is the fallback when CFBD returns only the top 25.
Portal points come from all pages of the 247 team table, never player counts.
Coaching compares each season's opening coach with the prior season's opening
coach. Bulk coach identities avoid routine per-team calls; ambiguous seasons use
cached tenure dates. A midseason replacement does not redefine this covariate.
Sources: [CFBD API](https://api.collegefootballdata.com/api/coaches),
[247 transfer rankings](https://247sports.com/season/2026-football/transferteamrankings/),
and [the handoff's AP archive](https://collegepollarchive.com/football/ap/seasons.cfm?appollid=1268).
The collector repeats at most once per UTC date, including when a rankings run
also triggers forecasts. Sportsbook collection and comparisons have been removed
from the production workflow and public interface.

Live values are stored in `forecast_inputs/live/<season>.json`; their generated
priors are in `forecast_priors/live/`. Frozen handoff evidence and earlier priors
remain untouched. New annual training summaries call the supplied
`season_ratings` and `di_ratings` functions; completed-season feeds and summaries
are cached. Future-season historical inputs are frozen when incorporated into
the annual training set. Public snapshots retain their input observations and
their original prior values. Historical manual runs use the frozen prior and
do not refresh current covariates.

A failed covariate feed retains its last usable values and emits a workflow
warning and step summary. A new season with an unavailable required feed waits
and retries automatically the next day. Checked data are committed even if a
later fit fails; the last passing forecast remains published. Daily timestamps
alone trigger neither fitting nor large snapshot exports.

A changed schedule rebuilds the export but reuses the checked
posterior. A changed forecast model or training data triggers a new fit. Failed
fits are not published or cached as passing. Retained arrays omit duplicated
latent representations after diagnostics; caches keep only the current fit.
The task-storage guard remains in place. Snapshot archives preserve past forecasts;
a historical reconstruction cannot replace the latest current-season forecast.

Scheduled win probabilities and expected score differences use full-posterior summaries.
Exploratory matchup probabilities and charts use 1,000 aligned rounded draws. For horizon h, strength is `theta_last + sqrt(h) * innovation`.
This preserves the weekly random walk's marginal forecast variance; it is not a
joint simulation of an entire future schedule. Power summaries retain the original uncentered model scale and use all draws. There is no inference, API call, or charged service when browsing.

Team details show the regression inputs and prior contributions, posterior weekly
paths, and retrospective game evidence. Game-implied strength is descriptive,
not an additive attribution of the posterior. Game predictions show the expected
margin in points, both win probabilities and 80%/95% predictive intervals.
The supplied model predicts score differences, not separate team totals; these
intervals must not be presented as intervals for a team's final score.

## Commands and validation

After pushing, the projections workflow runs automatically. In Actions, use
**Update CFB projections → Run workflow**, season `current`, week blank, to retry.
The optional week field reconstructs that week's forecast (`99` means CFP).

```sh
python3 -B scripts/cfb_forecast/publish.py prepare --season 2026
# Inside the approved numerical environment:
python3 -B scripts/cfb_forecast/publish.py complete --season 2026
python3 -B scripts/cfb_forecast/publish.py complete --season 2025 --week 1
```

Targeted checks: `test_forecasts.py`, `test_v7.py`, `test_refresh.py`, and `check_projections.cjs`.
They cover frozen prior/evaluation replay, time boundaries, FCS scales, dynamic
likelihood, aligned forecast distributions, line consensus, and cache reuse.
They do not run HMC or a browser. Numerical test caches must be directed to the
approved task directory. Production sampling and rendered UI review require
separate task authorization locally.

The refresh/rollover checks use local simulated provider responses and saved
inputs, without API calls or annual/full-season fitting. The local network
rejected direct HTTP access to the provider pages, so unattended portal/AP
scraping and the repository-secret-backed refresh have **not** been verified
against live responses here. The first deployed run's feed summary must confirm
them; parse/coverage failures preserve saved inputs and are visible as warnings.

Historical accuracy reports the model's average absolute margin error against
actual results and an approximate 95% confidence interval using season-week
clustered SEs of the model's errors. This is not the SE of a paired comparison.
Development: 2,535 games in 2023–2025, model MAE 12.2008. Frozen 2026 reconstruction
through week 12: 822 games, model MAE 12.4643. These are pre-QB model checks on the
original handoff's fixed evaluation sample. One-week groups have no estimable
cluster SE; the display does not report a misleading zero. Rebuild the public
aggregate from existing saved evidence with `python3 -B scripts/cfb_forecast/evaluation.py`.
