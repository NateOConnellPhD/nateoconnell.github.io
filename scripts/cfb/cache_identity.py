"""Preserve checked caches across the historical date-range extension only.

The manifest records exact before/after source hashes. This extension changes
no numerical calculations or previously supported ranking results. Any later
source edit disables this compatibility bridge rather than masking a change.
"""
import hashlib
import json
from pathlib import Path

REFIT_GENERATION = 'margin-of-merit-v5-fcs-refit'

SOURCES = ('model.py', 'refit_2024.py', 'loo_scoring.py', 'ranking_policy.py',
           'ranking_policy_v5.py', 'exact_order.py', 'sync_data.py', 'season_inputs.py', 'fit_saved_season.py', 'requirements.txt', 'update_rankings.py',
           'posterior_summary.py', 'historical_rankings.py', 'cache_identity.py')


def source_identities():
    current = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
               for name in SOURCES}
    manifest = json.loads(Path(__file__).with_name('history_cache_compatibility.json').read_text())
    previous = manifest['previous'] if current == manifest['current'] else None
    return current, previous


def publication_sources(season):
    current, previous = source_identities()
    # There were no published pre-2024 results to reuse. Give them the new
    # complete identity, while keeping existing checked weeks reusable.
    return previous if previous is not None and season >= 2024 else current


def runner_identity():
    current, previous = source_identities()
    # The runner's year guard and identity lookup changed, not its HMC/LOO
    # calculations. Avoid invalidating those arrays for this exact revision.
    return (previous or current)['fit_saved_season.py']
