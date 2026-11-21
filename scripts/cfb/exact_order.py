"""Exact lexicographic linear ordering, with no scalar penalty weights.

Complete forward raw-order preferences let us split at boundaries crossed by
no backward requirement. Across such a boundary every objective agrees, so
interleaving the two blocks cannot improve any count and worsens raw retention.
Small blocks use subset dynamic programming; larger blocks use four successive
integer programs, fixing each optimum before solving the next priority.
"""
from functools import lru_cache
from itertools import combinations
import time


class UnsolvedOrder(ValueError):
    pass


def blocks(n, requirements):
    end = list(range(n))
    for row in requirements:
        a, b = row['before'], row['after']
        if not (0 <= a < n and 0 <= b < n) or a == b:
            raise ValueError('Invalid ordering requirement')
        if a > b:
            end[b] = max(end[b], a)
    output, start = [], 0
    while start < n:
        last, i = end[start], start
        while i <= last:
            last = max(last, end[i]); i += 1
        output.append(list(range(start, last + 1)))
        start = last + 1
    return output


def objective(order, requirements):
    rank = {v: k for k, v in enumerate(order)}
    counts = [0, 0, 0, 0]
    for row in requirements:
        respected = rank[row['before']] < rank[row['after']]
        if row['priority'] == 0:
            if not respected:
                raise UnsolvedOrder('Inconsistent hard ranking requirements')
        elif respected:
            counts[row['priority'] - 1] += 1
    counts[3] = sum(a < b for k, a in enumerate(order) for b in order[k + 1:])
    return tuple(counts)


def subset_order(ids, requirements):
    n = len(ids)
    predecessors = [0] * n
    masks = [[0] * 4 for _ in ids]
    for row in requirements:
        a, b, priority = row['before'], row['after'], row['priority']
        if priority == 0:
            predecessors[b] |= 1 << a
        else:
            masks[a][priority - 1] |= 1 << b
    for a in range(n):
        masks[a][3] = sum(1 << b for b in range(a + 1, n))
    candidates = sorted(range(n), key=lambda i: ids[i])
    choices = {}

    @lru_cache(None)
    def solve(remaining):
        if not remaining:
            return (0, 0, 0, 0)
        best = None
        for a in candidates:
            if not remaining & (1 << a) or predecessors[a] & remaining:
                continue
            rest = remaining ^ (1 << a)
            tail = solve(rest)
            if tail is None:
                continue
            value = tuple(tail[k] + bin(masks[a][k] & rest).count('1') for k in range(4))
            # Ascending IDs plus strict improvement select the lexicographically
            # smallest ID sequence among exact objective ties.
            if best is None or value > best:
                best, choices[remaining] = value, a
        return best

    remaining = (1 << n) - 1
    optimum = solve(remaining)
    if optimum is None:
        raise UnsolvedOrder('Inconsistent hard ranking requirements')
    order = []
    while remaining:
        a = choices[remaining]; order.append(a); remaining ^= 1 << a
    return order


def integer_order(ids, requirements, deadline):
    """HiGHS through SciPy. Accept only certified integer optima, never incumbents."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    n = len(ids)
    pairs = list(combinations(range(n), 2))
    columns = {pair: k for k, pair in enumerate(pairs)}
    m = len(pairs)
    lower, upper = np.zeros(m), np.ones(m)
    rows, lbs, ubs = [], [], []

    def direction(a, b):
        return columns[min(a, b), max(a, b)], 1 if a < b else -1

    targets = [np.zeros(m) for _ in range(4)]
    targets[3][:] = 1
    for row in requirements:
        col, sign = direction(row['before'], row['after'])
        if row['priority'] == 0:
            value = int(sign == 1)
            if lower[col] == upper[col] and lower[col] != value:
                raise UnsolvedOrder('Inconsistent hard ranking requirements')
            lower[col] = upper[col] = value
        else:
            targets[row['priority'] - 1][col] += sign
    for a, b, c in combinations(range(n), 3):
        rows.append({columns[a, b]: 1, columns[b, c]: 1, columns[a, c]: -1})
        lbs.append(0); ubs.append(1)

    def optimize(target, extra_rows=(), extra_lbs=(), extra_ubs=()):
        width = len(target)
        all_rows = rows + list(extra_rows)
        rr, cc, vv = [], [], []
        for i, row in enumerate(all_rows):
            for j, value in row.items():
                rr.append(i); cc.append(j); vv.append(value)
        matrix = coo_matrix((vv, (rr, cc)), shape=(len(all_rows), width)).tocsc()
        left = deadline - time.monotonic()
        if left <= 0:
            raise UnsolvedOrder('Exact ranking optimization exceeded its time budget; no approximate ranking was published')
        result = milp(-np.asarray(target), integrality=np.ones(width),
            bounds=Bounds(np.r_[lower, np.zeros(width-m)], np.r_[upper, np.ones(width-m)]),
            constraints=LinearConstraint(matrix, lbs + list(extra_lbs), ubs + list(extra_ubs)),
            options={'mip_rel_gap': 0., 'time_limit': left, 'presolve': True})
        if result.status == 2:
            raise UnsolvedOrder('Inconsistent hard ranking requirements')
        if result.status != 0 or result.x is None:
            raise UnsolvedOrder('Exact ranking optimization did not prove an optimum; no approximate ranking was published')
        rounded = np.rint(result.x)
        if np.max(np.abs(result.x-rounded)) > 1e-6:
            raise UnsolvedOrder('Optimizer returned a noninteger order')
        values = matrix @ rounded
        if (np.any(values < np.asarray(lbs+list(extra_lbs))-1e-6) or
                np.any(values > np.asarray(ubs+list(extra_ubs))+1e-6)):
            raise UnsolvedOrder('Optimizer result violates ranking constraints')
        return rounded

    for target in targets:
        if not np.any(target):
            continue
        solution = optimize(target)
        value = int(round(float(target @ solution)))
        rows.append({i: float(c) for i, c in enumerate(target) if c})
        lbs.append(value); ubs.append(value)
    # Exact deterministic ID tie-break: choose the smallest possible next ID,
    # with every earlier objective fixed. z[a] means a precedes all remaining.
    order, remaining = [], set(range(n))
    stable = {a: k for k, a in enumerate(sorted(remaining, key=lambda i: ids[i]))}
    while len(remaining) > 1:
        candidates = sorted(remaining)
        z = {a: m+k for k, a in enumerate(candidates)}
        extra = [{col: 1 for col in z.values()}]; lo, hi = [1], [1]
        for a in candidates:
            for b in candidates:
                if a == b: continue
                col, sign = direction(a, b)
                extra.append({z[a]: 1, col: -sign})
                lo.append(-np.inf); hi.append(0 if sign == 1 else 1)
        target = np.zeros(m+len(candidates))
        for a in candidates: target[z[a]] = -stable[a]
        solution = optimize(target, extra, lo, hi)
        first = [a for a in candidates if solution[z[a]] == 1]
        if len(first) != 1: raise UnsolvedOrder('Invalid deterministic optimizer tie-break')
        a = first[0]; order.append(a); remaining.remove(a)
        for b in remaining:
            col, sign = direction(a, b); lower[col] = upper[col] = int(sign == 1)
    return order + sorted(remaining)


def exact_order(ids, requirements, *, subset_limit=18, timeout_seconds=120):
    if len(set(ids)) != len(ids):
        raise ValueError('Stable IDs must be unique')
    if any(r['priority'] not in (0, 1, 2, 3) for r in requirements):
        raise ValueError('Unknown evidence priority')
    if len({(r['before'], r['after'], r['priority']) for r in requirements}) != len(requirements):
        raise ValueError('Duplicate requirement would double-count evidence')
    order, methods = [], []
    deadline = time.monotonic() + timeout_seconds
    for group in blocks(len(ids), requirements):
        local = {value: i for i, value in enumerate(group)}
        rows = [{**r, 'before': local[r['before']], 'after': local[r['after']]}
                for r in requirements if r['before'] in local and r['after'] in local]
        keys = [ids[i] for i in group]
        if len(group) <= subset_limit:
            solved = subset_order(keys, rows); method = 'subset_dynamic_programming'
        else:
            solved = integer_order(keys, rows, deadline); method = 'lexicographic_integer_optimization'
        order.extend(group[i] for i in solved)
        methods.append({'size': len(group), 'method': method})
    counts = objective(order, requirements)
    return order, {'optimal': True, 'head_to_head': counts[0], 'common_opponents': counts[1],
                   'merit_protection': counts[2], 'raw_inversions': len(ids)*(len(ids)-1)//2-counts[3],
                   'tie_break': 'Lexicographically smallest stable-ID sequence', 'blocks': methods}
