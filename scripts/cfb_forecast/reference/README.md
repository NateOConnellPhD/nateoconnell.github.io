# Supplied forecasting source

These four Python files are unchanged copies from the user's
`mom_forecast_v7/code` handoff. `provenance.json` records their hashes.

Runtime adapters call `forecast_model.forecast_model`,
`historical_home.robust_history_fit`, and `historical_home.current_home_prior`.
`make_forecasts.py` and `priors_v7.py` are preserved as the original product and
prior-building reference. They are not invoked as unattended filesystem scripts.

Do not independently rewrite the statistical functions. Changes to the supplied
model require a new user specification and an explicit comparison. Deployment,
saved-data schemas, diagnostics and presentation belong outside this directory.
