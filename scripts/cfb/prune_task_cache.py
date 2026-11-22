"""Keep only reusable numerical work for this job's cutoff before installing.

Standard library only. Run solely on the job-owned disposable cache restored
by Actions, never on published snapshots or saved football data.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil

from cache_identity import REFIT_GENERATION
from historical_home import CANONICAL as HOME
from reference_config import REFERENCE_RANKS
from run_bounded import ROOT, storage_report
from season_inputs import load_fit_inputs
from sync_data import digest

HASH = re.compile(r'[0-9a-f]{64}')


def source_hash(name):
    return hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()


def read_report(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def entries(root, leaf):
    folder = root / leaf
    if folder.is_symlink():
        raise ValueError('Refusing a linked cache directory: ' + str(folder))
    return list(folder.iterdir()) if folder.exists() else []


def prune(root, inputs):
    """Do not prune a running fit. Called once, between restore and install."""
    before = storage_report(root)
    model_data = {'team_ids': [t['id'] for t in inputs['teams']], 'data': inputs['data'],
                  'strength_structure': inputs['strength_structure']}
    data_hash = digest(model_data)
    history_hash = inputs['home_history']['input_sha256']
    retained, remove = set(), []
    for folder in entries(root, 'fits'):
        report = read_report(folder / 'report.json') if not folder.is_symlink() else {}
        ident = report.get('identity', {})
        if (folder.is_dir() and HASH.fullmatch(folder.name) and digest(ident) == folder.name
                and ident.get('refit_generation') == REFIT_GENERATION
                and ident.get('model_source') == source_hash('model.py')
                and ident.get('diagnostic_source') == source_hash('refit_2024.py')
                and ident.get('model_data_sha256') == data_hash
                and ident.get('home_prior', {}).get('history_input_sha256') == history_hash
                and report.get('diagnostics', {}).get('sampling_checks_passed') is True
                and (folder / 'posterior.npz').is_file()):
            retained.add(folder.name)
        else:
            remove.append(folder)
    for leaf, filename in (('scores', 'merit.npz'), ('exact', 'quantities.npz')):
        for folder in entries(root, leaf):
            report = read_report(folder / 'report.json') if not folder.is_symlink() else {}
            ident = report.get('identity', {})
            runner = 'runner_source' if leaf == 'exact' else 'exact_runner_source'
            sampling = 'sampling_source' if leaf == 'exact' else 'exact_sampling_source'
            compatible = (ident.get('reference_ranks') == list(REFERENCE_RANKS)
                          and report.get('diagnostics', {}).get('sampling_checks_passed') is True) if leaf == 'exact' else (
                              ident.get('reference_rank') in REFERENCE_RANKS and ident.get('exact_loo') is True)
            if not (folder.is_dir() and HASH.fullmatch(folder.name) and digest(ident) == folder.name
                    and ident.get('fit_key') in retained and compatible
                    and ident.get(runner) == source_hash('fit_saved_season.py')
                    and ident.get(sampling) == source_hash('sampling_retry.py')
                    and ident.get('scorer_source') == source_hash('loo_scoring.py')
                    and ident.get('reference_source') == source_hash('reference_config.py')
                    and (folder / filename).is_file()):
                remove.append(folder)
    # This is shared across all weeks of the selected season. Its identity is
    # the same one used by historical_home.load_or_estimate, without inference.
    home_identity = {'history_input_sha256': history_hash,
                     'fbs_ids': [inputs['teams'][i]['id'] for i in inputs['fbs_indices']],
                     'specification': asdict(HOME),
                     'source_sha256': digest(Path(__file__).with_name('historical_home.py').read_text())}
    for path in entries(root, 'home'):
        if path.is_symlink() or path.name != digest(home_identity) + '.json':
            remove.append(path)
    # Inspect every cache category before deleting anything; never traverse
    # linked directories or touch the environment, input data, or public site.
    for path in remove:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    result = {'event': 'pruned_task_cache', 'removed_entries': len(remove),
              'retained_fit_keys': sorted(retained), 'before': before, 'after': storage_report(root)}
    print(json.dumps(result), flush=True)
    return result


def main():
    plan = json.loads((ROOT / 'update-plan.json').read_text())
    cutoff = {'as_of': plan['as_of']} if plan.get('as_of') else {}
    inputs = load_fit_inputs(plan['season'], through_week=plan.get('through_week'), **cutoff)
    prune(ROOT, inputs)


if __name__ == '__main__':
    main()
