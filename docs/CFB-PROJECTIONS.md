# Game projections

`/blog/cfb/#projections` is independent of earned-merit rankings. The predictive
specification is the frozen `V7LDe75` handoff, represented by `ForecastConfig`.
The public interface calls this game projections, without development labels.

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
  diagnostics. It is **not imported as a validated production fit**. The next
  workflow must produce a passing fit; the old saved forecast is visibly labeled
  as an earlier-model archive until then.
  A local 2026 refit on November 23 passed all checks with 8,000 retained draws:
  zero divergences/tree-depth hits, maximum R-hat 1.00552, minimum bulk ESS 482.81,
  minimum tail ESS 525.50, and minimum BFMI 0.85069. Sampling took 91 seconds on
  the local machine, excluding diagnostics. The original 4,000-draw settings
  had zero divergences in the local reproduction but poor drift-scale mixing
  (q R-hat 1.02334, ESS 197.91); increasing target acceptance alone did not fix it.
  The supplied file lacks transition-level flags, so its two original divergent
  trajectories cannot be located retrospectively. New reports retain chain/draw
  positions, scale contexts, acceptance and step-size summaries, including on
  failure. The model and diagnostic thresholds were not changed.
- Current saved feeds support forecasting for 2025–2026. Fresh historical refits
  for 2023–2024 need their missing saved FCS feeds (and 2023 also needs 2020 home
  history). The supplied 2023–2025 evaluation is available without those refits.
- Each future season needs its reviewed preseason inputs and regenerated prior;
  annual feature definitions cannot silently be swapped for another provider.
- No injury or player-availability inputs. No play-by-play downloads are needed
  for the retained postgame-expectancy target.

## Publishing and caching

`Update CFB projections` follows the rankings workflow and also runs when its own
source changes. It consumes existing saved game feeds, without making additional
game requests. An optional single `/lines?year=…&seasonType=both` request is cached
per changed game-feed payload, using the existing `CFBD_API_KEY` repository
secret. A provider failure leaves the old dated comparison available; it never
blocks the model. No secret enters static JSON.

A changed schedule or market feed rebuilds the export but reuses the checked
posterior. A changed forecast model or training data triggers a new fit. Failed
fits are not published or cached as passing. Retained arrays omit duplicated
latent representations after diagnostics; caches keep only the current fit.
The task-storage guard remains in place. Snapshot archives preserve past forecasts;
a historical reconstruction cannot replace the latest current-season forecast.

Browser matchup probabilities, intervals, and scheduled games use the same 1,000
aligned rounded draws. For horizon h, strength is `theta_last + sqrt(h) * innovation`.
This preserves the weekly random walk's marginal forecast variance; it is not a
joint simulation of an entire future schedule. Full-draw power summaries remain
separate. There is no inference, API call, or charged service when browsing.

Team details show the regression inputs and prior contributions, posterior weekly
paths, and retrospective game evidence. Game-implied strength is descriptive,
not an additive attribution of the posterior. Opening and latest market lines
are median home spreads across available books; negative means home favored.
Latest available lines are not labeled closing lines before the game is finished.

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

Targeted checks: `test_forecasts.py`, `test_v7.py`, and `check_projections.cjs`.
They cover frozen prior/evaluation replay, time boundaries, FCS scales, dynamic
likelihood, aligned forecast distributions, line consensus, and cache reuse.
They do not run HMC or a browser. Numerical test caches must be directed to the
approved task directory. Production sampling and rendered UI review require
separate task authorization locally.

Historical comparisons report the opening line as primary and the close as
secondary, with season-week clustered SEs. Development: 2,535 games in 2023–2025,
model MAE 12.2008 versus opener 12.1256. Frozen 2026 reconstruction through week
12: 822 games, model 12.4643 versus opener 11.9836. One-week groups have no
estimable cluster SE; the display does not report a misleading zero.
