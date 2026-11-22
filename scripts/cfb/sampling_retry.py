"""Bounded exact-LOO recovery; the statistical model and diagnostic gates stay fixed."""
import json
import math

# Four sequential chains in model.fit, with the same seed/model for both attempts.
# A longer run is attempted once, never repeated until a lucky run passes.
EXACT_ATTEMPTS = ((1000, 1000), (2000, 2000))


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def log_event(event):
    print(json.dumps(json_safe(event), allow_nan=False), flush=True)


class ExactLOOSamplingError(ValueError):
    def __init__(self, game_id, attempts):
        self.details = json_safe({'game_id': game_id, 'attempts': attempts})
        last = self.details['attempts'][-1]['diagnostics']
        super().__init__(f'Exact LOO game {game_id} failed sampling diagnostics after '
                         f'{len(attempts)} attempts: {json.dumps(last, allow_nan=False)}')


def checked_exact_refit(game_id, seed, fit_attempt, describe, emit=log_event):
    attempts = []
    for number, (warmup, draws) in enumerate(EXACT_ATTEMPTS, 1):
        settings = {'seed': seed, 'warmup': warmup, 'draws': draws}
        emit({'exact_loo_game': game_id, 'attempt': number, 'phase': 'sampling', **settings})
        samples, diagnostics, _ = describe(fit_attempt(**settings))
        attempts.append({'settings': settings, 'diagnostics': json_safe(diagnostics)})
        emit({'exact_loo_game': game_id, 'attempt': number, 'phase': 'diagnostics',
              'diagnostics': diagnostics})
        if diagnostics['sampling_checks_passed']:
            return samples, diagnostics, attempts
        # Do not retain the failed posterior while allocating the longer run.
        del samples
    raise ExactLOOSamplingError(game_id, attempts)
