# Forecast implementation audit — November 23, 2026

The supplied `mom_forecast_v7` implementation is authoritative. The previous
port was not verified adequately against it.

## Differences found

| Area | Previous website implementation | Supplied implementation / correction |
| --- | --- | --- |
| Displayed snapshot | Older fit: 1,395 games, last kickoff November 21 at 21:00 UTC | Supplied current fit: 1,472 games, last kickoff November 22 at 03:30 UTC. This was stale website output, not stale user data. |
| Rating scale | Subtracted the FBS mean separately in every draw | Reports raw model draws. Recentring changed both ratings and marginal uncertainty intervals. Removed. |
| Efficiency input | Used probabilities from both FBS and FCS game feeds | The supplied product joins the FBS schedule. Its 650 FCS-only games use actual margins. Restored that input scope. |
| Model implementation | Independently translated NumPyro function | Calls the unchanged supplied `forecast_model()` directly. |
| Home estimator | Independently translated robust historical estimator | Calls the supplied `robust_history_fit()` and `current_home_prior()` directly, with ID/data adapters. |
| Scheduled forecast summaries | Dynamic lines/probabilities used 1,000 browser draws | Restored full-posterior means and scheduled win probabilities. Browser charts and arbitrary-matchup probabilities remain explicitly identified numerical approximations. |
| Sampling | Originally 4 × 1,000 warmup/retained at 0.9 | Separately disclosed diagnostic recovery: 4 × 2,000 at 0.97, then 4,000 at 0.99 if necessary. This changes computation, not the statistical model. |

## Reproduction checks

`scripts/cfb_forecast/reference/` contains byte-identical copies of four supplied
source files and their SHA-256 manifest. The model and historical estimator are
executed from those files. The product script and prior builder are also retained
for comparison; the website's saved-data adapter does not execute their filesystem
entry points or load their pickle files.

`check_handoff.py` compares the exporter with all 138 supplied FBS rows, using the
supplied NPZ with pickle loading disabled. Means, 80%/95% endpoints, strength
probabilities and ordering match exactly (maximum numerical difference: zero).
This is an export replay, **not** evidence that a new sampler reproduces every
rounded rating or that the supplied draws passed production diagnostics.

The 1,472 current training-game IDs, final scores, weeks, team divisions and
conferences match the packet. Preseason team means agree to about 6e-14 points.
The restored fitting-target scale is 4.846067826344272, versus the supplied
4.846067826344269, using 822 games with expectancy and 650 FCS-only raw margins.

## Remaining source-data differences

The saved provider feeds mark Harvard–Yale (401867844) and
Bethune-Cookman–Florida A&M (401868947), both November 21, 2026, as neutral;
the supplied completed-game CSV marks them non-neutral. In the historical home
data, the saved feed marks 2023 Michigan State–Penn State (401520435) neutral,
while the supplied archive marks it non-neutral. The other 2,263 historical
likelihood contributions agree after accounting for reversed home designations
at neutral sites.

These are input differences, not different model equations. The saved feeds are
not silently overwritten to force agreement with a desired ranking. An exact
same-input reproduction must use the supplied venue flags as well. Fresh NUTS
runs also have Monte Carlo variation; differences must be interpreted against
their simulation error, not dismissed without comparison.

## Corrected production-input run

The supplied model function was run on the saved 1,472-game feed with the
restored expectancy scope. Four chains with 2,000 warmup and 2,000 retained
draws passed: zero divergences and tree-depth hits, maximum R-hat 1.00796,
minimum bulk ESS 489.21, minimum tail ESS 697.13, minimum BFMI 0.87786.
Sampling took 89 seconds locally, excluding diagnostics.

All top-25 positions match the supplied table. The largest top-25 mean-rating
difference is 0.239 points; across all 138 teams it is 0.290. This is a fresh
sample with the explicitly recorded venue differences, not an exact-draw replay.
The public snapshot is `5dc19ea0e0d59ffe`; it preserves the older snapshot in the
archive. Its full-posterior means reproduce the reported rating and line means
to 1.3e-14 after the final export-format adjustment. No raw sampler binaries or
private handoff files are published.

## Commands

```sh
python3 -B scripts/cfb_forecast/check_handoff.py context_not_for_upload/mom_forecast_v7
```

This audit uses existing numerical dependencies, makes no network requests and
does not publish. Sampling diagnostics can be run separately with
`check_sampling.py`; outputs are restricted to `.codex-tmp`.
