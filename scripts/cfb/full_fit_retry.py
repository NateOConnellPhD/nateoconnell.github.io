"""Checked full-fit recovery with separate cache identities for actual draw counts."""
import hashlib
import json

from sampling_retry import json_safe, log_event
from sync_data import digest

FULL_ATTEMPTS = ((1000, 1000), (2000, 2000))


class FullFitSamplingError(ValueError):
    def __init__(self, context, attempts):
        self.details = json_safe({'phase': 'full_fit', **context, 'attempts': attempts})
        last = self.details['attempts'][-1]['diagnostics']
        super().__init__(f"Full fit for season {context['season']}, week {context.get('week')} failed sampling "
                         f"diagnostics after {len(attempts)} attempts: {json.dumps(last, allow_nan=False)}")


def array_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_full_fit(base_identity, cache, context, fit_attempt, describe, predictive, emit=log_event):
    """Reuse a passing initial or longer fit before doing any more sampling.

    The seed, model and diagnostics remain fixed. Failed draws are never saved
    or pooled with a later attempt. Unrelated exceptions propagate immediately.
    """
    import numpy as np

    identities = [{**base_identity, 'warmup': warmup, 'draws': draws} for warmup, draws in FULL_ATTEMPTS]
    prior_failures = {}
    for number, identity in enumerate(identities, 1):
        key = digest(identity)
        folder = cache / key
        if not folder.exists():
            continue
        report = json.loads((folder / 'report.json').read_text())
        if report['identity'] != identity or report['array_sha256'] != array_hash(folder / 'posterior.npz'):
            raise ValueError('Cached full fit identity or array integrity failed')
        if report['diagnostics']['sampling_checks_passed']:
            with np.load(folder / 'posterior.npz', allow_pickle=False) as saved:
                samples = dict(saved)
            emit({'full_fit': context, 'phase': 'cached', 'fit_key': key,
                  'warmup': identity['warmup'], 'draws': identity['draws'], 'diagnostics': report['diagnostics']})
            return samples, report, key, True
        # Older runners wrote failed arrays. They are evidence of this failed
        # attempt, never usable draws or a reason to repeat the identical run.
        prior_failures[number] = json_safe(report['diagnostics'])

    attempts = []
    for number, identity in enumerate(identities, 1):
        settings = {k: identity[k] for k in ('seed', 'warmup', 'draws')}
        if number in prior_failures:
            diagnostics = prior_failures[number]
            attempts.append({'settings': settings, 'diagnostics': diagnostics, 'restored_failure': True})
            emit({'full_fit': context, 'attempt': number, 'phase': 'restored_failure', 'diagnostics': diagnostics})
            continue
        emit({'full_fit': context, 'attempt': number, 'phase': 'sampling', **settings})
        samples, diagnostics, parameters = describe(fit_attempt(**settings))
        attempts.append({'settings': settings, 'diagnostics': json_safe(diagnostics)})
        emit({'full_fit': context, 'attempt': number, 'phase': 'diagnostics', 'diagnostics': diagnostics})
        if not diagnostics['sampling_checks_passed']:
            del samples, parameters
            continue
        report = {'identity': identity, 'diagnostics': diagnostics, 'parameters': parameters,
                  'attempts': attempts, 'posterior_predictive': predictive(samples)}
        key = digest(identity)
        folder = cache / key
        folder.mkdir(parents=True)
        np.savez_compressed(folder / 'posterior.npz', **samples)
        report['array_sha256'] = array_hash(folder / 'posterior.npz')
        (folder / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        return samples, report, key, False
    raise FullFitSamplingError(context, attempts)
