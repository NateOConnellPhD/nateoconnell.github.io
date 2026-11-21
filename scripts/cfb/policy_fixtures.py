"""Small offline fixtures shared by current-policy checks."""

def teams(n):
    return [{'id': i + 1, 'name': chr(65 + i), 'conference': 'American Athletic'} for i in range(n)]


def games(pairs):
    return [{'id': k + 1, 'season': 2024, 'season_type': 'regular', 'eligible': True, 'completed': True,
             'home_id': w, 'away_id': l, 'home_points': 24, 'away_points': 21}
            for k, (w, l) in enumerate(pairs)]


def probability(n, pairs=None):
    p = [[0. if i == j else .5 for j in range(n)] for i in range(n)]
    for (i, j), value in (pairs or {}).items():
        p[i - 1][j - 1], p[j - 1][i - 1] = value, 1 - value
    return p
