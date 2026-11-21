"""Prepare posterior draws for the canonical-vs-archive 2024 comparison.

This is a research fitting command, not a publisher or a ranking generator.
It verifies the private reference fixture before fitting and never imports or
executes its archived scripts. Run only in an approved numerical environment.
"""

import argparse
import csv
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import time

from model import ARCHIVED_PRIOR, CANONICAL, UNFLOORED_SENSITIVITY, fit


PROJECT = Path(__file__).resolve().parents[2]
TASK = PROJECT / ".codex-tmp" / "cfb-refit"
FIXTURE_SHA256 = "18274603de63d2b98e911538c4f304c17d8e4b79ae2bfb49bc1d9c05efa24572"
VARIANTS = {"canonical": CANONICAL, "unfloored": UNFLOORED_SENSITIVITY, "archived-prior": ARCHIVED_PRIOR}


def read_reference(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError("The 2024 reference differs from the supplied 752-game fixture; review it before fitting")
    games = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    teams = sorted({g[k] for g in games for k in ("home_team", "away_team")})
    if len(games) != 752 or len(teams) != 134:
        raise ValueError("Unexpected reference fixture dimensions")
    ids = {name: i for i, name in enumerate(teams)}
    neutral = {"True": 0, "False": 1}
    return teams, {
        "home": [ids[g["home_team"]] for g in games],
        "away": [ids[g["away_team"]] for g in games],
        "venue": [neutral[g["neutral_site"]] for g in games],
        "margin": [int(g["home_points"]) - int(g["away_points"]) for g in games],
    }


def describe(sampler):
    import arviz as az
    import numpy as np

    idata = az.from_numpyro(sampler)
    parameters = ["theta", "home_adv", "sigma", "nu", "eta_sigma", "eta_nu"]
    if 'home_effect' in idata.posterior:
        parameters += ['home_effect', 'home_z']
    if 'mu_fcs' in idata.posterior:
        parameters += ['mu_fcs', 'tau_division', 'tau_conf', 'theta_z', 'conference_z', 'conference_effect']
    rhat = np.concatenate([np.asarray(v).ravel() for v in az.rhat(idata, var_names=parameters, method="rank").data_vars.values()])
    bulk = np.concatenate([np.asarray(v).ravel() for v in az.ess(idata, var_names=parameters, method="bulk").data_vars.values()])
    tail = np.concatenate([np.asarray(v).ravel() for v in az.ess(idata, var_names=parameters, method="tail").data_vars.values()])
    extra = sampler.get_extra_fields(group_by_chain=True)
    samples = {k: np.asarray(v) for k, v in sampler.get_samples(group_by_chain=True).items()}
    energy = np.asarray(extra["energy"])
    bfmi = np.mean(np.diff(energy, axis=1) ** 2, axis=1) / np.var(energy, axis=1)
    diagnostics = {
        "parameters_checked": parameters,
        "max_rank_normalized_rhat": float(np.max(rhat)),
        "min_bulk_ess": float(np.min(bulk)), "min_tail_ess": float(np.min(tail)),
        "divergences": int(np.sum(extra["diverging"])),
        "tree_depth_limit_hits": int(np.sum(np.asarray(extra["num_steps"]) >= 2**10 - 1)),
        "bfmi_by_chain": bfmi.tolist(),
    }
    finite = all(np.isfinite(x).all() for x in (rhat, bulk, tail, bfmi))
    diagnostics["sampling_checks_passed"] = bool(
        finite and diagnostics["max_rank_normalized_rhat"] <= 1.01
        and diagnostics["min_bulk_ess"] >= 400 and diagnostics["min_tail_ess"] >= 400
        and diagnostics["divergences"] == 0 and diagnostics["tree_depth_limit_hits"] == 0
        and np.min(bfmi) >= 0.3
    )
    summaries = {}
    for name in ("theta", "home_adv", "sigma", "nu", "home_effect", "mu_fcs", "tau_division", "tau_conf", "conference_effect"):
        if name not in samples: continue
        values = samples[name].reshape((-1,) + samples[name].shape[2:])
        summaries[name] = {"mean": np.mean(values, axis=0).tolist(),
                           "lo90": np.quantile(values, 0.05, axis=0).tolist(),
                           "hi90": np.quantile(values, 0.95, axis=0).tolist()}
    return samples, diagnostics, summaries


def predictive_summary(samples, data, seed):
    import numpy as np
    from loo_scoring import flatten, venue_effect
    th = samples["theta"].reshape(-1, samples["theta"].shape[-1])
    sig = samples["sigma"].ravel()
    nu = samples["nu"].ravel()
    mu = th[:, data["home"]] - th[:, data["away"]] + venue_effect(flatten(samples), data)
    rng = np.random.default_rng(seed)
    replicated = mu + sig[:, None] * rng.standard_t(nu[:, None], size=mu.shape)
    observed = np.asarray(data["margin"])
    stats = {"mean_margin": lambda x: np.mean(x, axis=-1),
             "sd_margin": lambda x: np.std(x, axis=-1),
             "fraction_abs_margin_over_28": lambda x: np.mean(np.abs(x) > 28, axis=-1)}
    return {name: {"observed": float(fn(observed)),
                   "predictive_lo90": float(np.quantile(fn(replicated), .05)),
                   "predictive_hi90": float(np.quantile(fn(replicated), .95))}
            for name, fn in stats.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--variant", choices=VARIANTS, default="canonical")
    parser.add_argument("--seed", type=int, default=20261120)
    parser.add_argument("--warmup", type=int, default=1000)
    parser.add_argument("--draws", type=int, default=1000)
    args = parser.parse_args()
    teams, data = read_reference(args.fixture)
    spec = VARIANTS[args.variant]
    if spec.historical_home:
        parser.error('The current model requires saved FBS/FCS inputs and the exact historical home window. '
                     'Use fit_saved_season.py --season 2024; the old FBS-only fixture cannot fit the current model.')
    destination = TASK / f"{args.variant}-{args.seed}-{args.warmup}-{args.draws}"
    if destination.exists():
        raise ValueError("This run already exists; use a different seed rather than overwrite it")

    # Contain libraries' disk caches as well as our own output. No downloads.
    for key, leaf in (("XDG_CACHE_HOME", "cache"), ("MPLCONFIGDIR", "matplotlib"),
                      ("JAX_COMPILATION_CACHE_DIR", "jax-cache"), ("TMPDIR", "tmp")):
        os.environ[key] = str(TASK / leaf)
    os.environ["JAX_PLATFORMS"] = "cpu"
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    # Verify availability before creating disposable output.
    packages = {name: version(name) for name in ("numpy", "scipy", "jax", "jaxlib", "numpyro", "arviz")}
    import numpy as np
    for leaf in ("cache", "matplotlib", "jax-cache", "tmp"):
        (TASK / leaf).mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    started = time.monotonic()
    sampler = fit(len(teams), **data, specification=spec, seed=args.seed,
                  warmup=args.warmup, draws=args.draws)
    samples, diagnostics, summary = describe(sampler)
    report = {
        "status": "research_fit_only_not_publishable",
        "model": asdict(spec), "model_sha256": spec.fingerprint,
        "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ("model.py", "refit_2024.py", "requirements.txt")},
        "fixture_sha256": FIXTURE_SHA256, "teams": teams,
        "games": len(data["margin"]), "chains": 4, "draws_per_chain": args.draws,
        "warmup_per_chain": args.warmup, "seed": args.seed, "packages": packages,
        "seconds": round(time.monotonic() - started, 2),
        "diagnostics": diagnostics, "parameters": summary,
        "posterior_predictive": predictive_summary(samples, data, args.seed + 1),
        "remaining": "PSIS/exact LOO, merit scoring, ranking-policy audit, and archive comparison",
    }
    # Chain/draw axes stay intact for ESS and LOO diagnostics downstream.
    np.savez_compressed(destination / "posterior.npz", teams=np.asarray(teams), **samples)
    (destination / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"report": str(destination / "report.json"), "diagnostics": diagnostics}, allow_nan=False))
    return 0 if diagnostics["sampling_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
