"""Side-effect-free reproduction of the archived final-season ordering policy.

This preserves the archive's SCC release rule for the prior comparison. The
production policy still needs a separately versioned minimal-cycle-release
implementation and season-specific conference membership.
"""
from collections import defaultdict
import heapq
import itertools

import numpy as np
from scipy.special import stdtr


def components(nodes, edges):
    adjacency = {n: [] for n in nodes}
    for a, b in sorted(edges):
        adjacency[a].append(b)
    index, low, stack, active, result = {}, {}, [], set(), []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        active.add(v)
        for w in adjacency[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in active:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            group = set()
            while True:
                w = stack.pop()
                active.remove(w)
                group.add(w)
                if w == v:
                    break
            result.append(group)

    for node in nodes:
        if node not in index:
            visit(node)
    return result


class ReferencePolicy:
    def __init__(self, teams, data, protected=()):
        self.teams = teams
        self.n = len(teams)
        self.vs = {i: defaultdict(list) for i in range(self.n)}
        self.wins = np.zeros(self.n, int)
        self.losses = np.zeros(self.n, int)
        for h, a, margin in zip(data['home'], data['away'], data['margin']):
            if margin == 0:
                raise ValueError('Tied final scores require a separate policy')
            win = int(margin > 0)
            self.vs[h][a].append(win)
            self.vs[a][h].append(1 - win)
            self.wins[h] += win
            self.wins[a] += 1 - win
            self.losses[h] += 1 - win
            self.losses[a] += win
        self.groups = defaultdict(list)
        for i in range(self.n):
            self.groups[(self.wins[i], self.losses[i])].append(i)
        self.protected = set(protected)
        if any(self.wins[i] < 8 or self.losses[i] for i in self.protected):
            raise ValueError('Protected teams must have at least eight FBS wins and zero losses')
        h2h, common = set(), set()
        for group in self.groups.values():
            for a, b in itertools.combinations(group, 2):
                aw, bw = sum(self.vs[a].get(b, [])), sum(self.vs[b].get(a, []))
                shared = (set(self.vs[a]) & set(self.vs[b])) - {a, b}
                delta = [np.mean(self.vs[a][o]) - np.mean(self.vs[b][o]) for o in shared]
                if aw != bw:
                    h2h.add((a, b) if aw > bw else (b, a))
                elif delta and min(delta) >= 0 and max(delta) > 0:
                    common.add((a, b))
                elif delta and max(delta) <= 0 and min(delta) < 0:
                    common.add((b, a))
        cycles = [c for c in components(range(self.n), h2h) if len(c) > 1]
        edges = {e for e in h2h | common if not any(set(e) <= c for c in cycles)}
        while True:
            cyclic = [c for c in components(range(self.n), edges) if len(c) > 1]
            if not cyclic:
                break
            remove = {e for e in edges & common if any(set(e) <= c for c in cyclic)}
            if not remove:
                raise ValueError('Unresolved reference-policy cycle')
            edges -= remove
        self.edges = edges
        self.audit = [{'winner': teams[a], 'loser': teams[b],
                       'rule': 'head_to_head' if (a, b) in h2h else 'common_opponent',
                       'applied': (a, b) in edges,
                       'release_reason': None if (a, b) in edges else 'archived_SCC_rule'}
                      for a, b in sorted(h2h | common)]
        self.constraints = []
        for group in self.groups.values():
            if len(group) > 1:
                successors = {i: sorted(b for a, b in edges if a == i) for i in group}
                indegree = {i: sum(b == i for a, b in edges) for i in group}
                self.constraints.append((set(group), successors, indegree))

    def completed(self, samples):
        theta = samples['theta']
        score = np.zeros_like(theta)
        for i, j in itertools.combinations(range(self.n), 2):
            p = (np.mean(self.vs[i][j]) if j in self.vs[i] else
                 stdtr(samples['nu'], (theta[:, i] - theta[:, j]) / samples['sigma']))
            score[:, i] += p
            score[:, j] += 1 - p
        return score

    def order(self, merit, completed):
        order = list(np.argsort(-np.asarray(merit), kind='stable'))
        for group, successors, indegree in self.constraints:
            slots = [k for k, i in enumerate(order) if i in group]
            degree = dict(indegree)
            heap = [(-completed[i], -merit[i], i) for i in sorted(group) if not degree[i]]
            heapq.heapify(heap)
            result = []
            while heap:
                _, _, i = heapq.heappop(heap)
                result.append(i)
                for j in successors[i]:
                    degree[j] -= 1
                    if not degree[j]:
                        heapq.heappush(heap, (-completed[j], -merit[j], j))
            if len(result) != len(group):
                raise ValueError('Ordering contains a constraint cycle')
            for slot, i in zip(slots, result):
                order[slot] = i
        for i in sorted(self.protected, key=order.index):
            position = next((k for k, j in enumerate(order) if self.losses[j] >= 2), self.n)
            if order.index(i) > position:
                order.remove(i)
                order.insert(position, i)
        return np.asarray(order, int)

    def ranks(self, merit, completed):
        ranks = np.empty(merit.shape, dtype=np.int16)
        for i in range(len(merit)):
            ranks[i, self.order(merit[i], completed[i])] = np.arange(1, self.n + 1)
        point = np.empty(self.n, int)
        point[self.order(merit.mean(axis=0), completed.mean(axis=0))] = np.arange(1, self.n + 1)
        if not np.all(np.sort(ranks, axis=1) == np.arange(1, self.n + 1)):
            raise ValueError('Rank draws must be permutations')
        return point, ranks
