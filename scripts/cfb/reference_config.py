"""Saved FBS reference-strength choices; these do not change the fitted model."""
DEFAULT_REFERENCE = 12
REFERENCE_RANKS = (2, 4, 12, 24)


def check_reference(rank):
    if type(rank) is not int or rank not in REFERENCE_RANKS:
        raise ValueError('Reference rank must be 2, 4, 12 or 24')
    return rank


def exact_quantities_for(bank, rank):
    check_reference(rank)
    names = ('home_cdf', 'away_cdf', 'home_sos', 'away_sos')
    if set(bank) != {f'r{r}_{name}' for r in REFERENCE_RANKS for name in names}:
        raise ValueError('Exact LOO cache is missing reference-team quantities')
    return {name: bank[f'r{rank}_{name}'] for name in names}
