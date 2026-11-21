"""Exact source identities for the current model; no earlier-model cache bridge."""
import hashlib
from pathlib import Path

REFIT_GENERATION = 'margin-of-merit-2026-11-21'

SOURCES = ('model.py', 'refit_2024.py', 'loo_scoring.py', 'ranking_policy.py',
           'ranking_policy_v5.py', 'exact_order.py', 'sync_data.py', 'season_inputs.py',
           'home_history_inputs.py', 'historical_home.py', 'fit_saved_season.py',
           'requirements.txt', 'update_rankings.py', 'posterior_summary.py',
           'historical_rankings.py', 'cache_identity.py')


def source_identities():
    return ({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in SOURCES}, None)


def publication_sources(season):
    return source_identities()[0]


def runner_identity():
    return source_identities()[0]['fit_saved_season.py']
