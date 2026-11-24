# Supplied forecasting source

These four Python files are unchanged copies from the user's
`mom_forecast_v7/code` handoff. `provenance.json` records their hashes.

Runtime adapters call `forecast_model.forecast_model`,
`historical_home.robust_history_fit`, and `historical_home.current_home_prior`.
Annual rollover also calls `forecast_model.season_ratings` and
`priors_v7.di_ratings` with validated saved-data adapters. `make_forecasts.py`
and the filesystem entry point in `priors_v7.py` remain references; they are
not invoked as unattended filesystem scripts.

Do not independently rewrite the statistical functions. Changes to the supplied
model require a new user specification and an explicit comparison. Deployment,
saved-data schemas, diagnostics and presentation belong outside this directory.
