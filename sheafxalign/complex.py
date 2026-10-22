"""Simplicial complexes of dimension <= 2 with explicit orientations.

Vertices: 0..n-1. Edges: tuples (u,v), u<v. Triangles: tuples (a,b,c), a<b<c.
Orientation convention (standard): d(a,b,c) = (b,c) - (a,c) + (a,b).
"""
from __future__ import annotations
import numpy as np
from typing import List, Sequence


class SimplicialComplex:
    def __init__(self, vertices: int, edges: Sequence[tuple], triangles: Sequence[tuple] = ()):
        self.n = vertices
        self.edges = [(int(u), int(v)) for u, v in edges if u != v]
        # dedupe, keep u<v
        seen, es = set(), []
        for u, v in self.edges:
            u, v = min(u, v), max(u, v)
            if (u, v) not in seen:
                seen.add((u, v))
                es.append((u, v))
        self.edges = es
        self.triangles = []
        seen_t = set()
        for a, b, c in triangles:
            a, b, c = sorted((int(a), int(b), int(c)))
            if a != b != c != a and (a, b, c) not in seen_t and (a, b) in seen and (b, c) in seen and (a, c) in seen:
                seen_t.add((a, b, c))
                self.triangles.append((a, b, c))
        self.edge_index = {e: i for i, e in enumerate(self.edges)}
        self.tri_index = {t: i for i, t in enumerate(self.triangles)}

    # ------------------------------------------------------------------ faces
    @property
    def m(self) -> int:
        return len(self.edges)

    def boundary_faces(self, tri: tuple):
        a, b, c = tri
        return [((b, c), +1.0), ((a, c), -1.0), ((a, b), +1.0)]

    def cofaces(self, edge: tuple):
        """Triangles containing `edge`, with incidence sign of `edge` in the triangle."""
        u, v = edge
        out = []
        for t in self.triangles:
            a, b, c = t
            for e, s in self.boundary_faces(t):
                if e == (u, v):
                    out.append((t, s))
        return out

    # ---------------------------------------------------------- constructors
    @classmethod
    def from_knn(cls, X: np.ndarray, k: int, add_triangles: bool = True, max_tri_per_edge: int = 3):
        """k-NN graph on rows of X -> complex; triangles = cliques of the kNN graph."""
        from scipy.spatial import cKDTree
        n = X.shape[0]
        k = min(k, n - 1)
        tree = cKDTree(X)
        _, idx = tree.query(X, k=k + 1)
        edges = set()
        for i in range(n):
            for j in idx[i][1:]:
                edges.add((min(i, int(j)), max(i, int(j))))
        tri_count = {e: 0 for e in edges}
        triangles = []
        if add_triangles:
            for i in range(n):
                nb = [int(j) for j in idx[i][1:]]
                for a in range(len(nb)):
                    for b in range(a + 1, len(nb)):
                        u, v = min(nb[a], nb[b]), max(nb[a], nb[b])
                        if (u, v) in edges:
                            t = tuple(sorted((i, nb[a], nb[b])))
                            key = t
                            if key not in triangles and tri_count[(u, v)] < max_tri_per_edge \
                               and tri_count[(min(i, nb[a]), max(i, nb[a]))] < max_tri_per_edge \
                               and tri_count[(min(i, nb[b]), max(i, nb[b]))] < max_tri_per_edge:
                                triangles.append(key)
                                tri_count[(u, v)] += 1
                                tri_count[(min(i, nb[a]), max(i, nb[a]))] += 1
                                tri_count[(min(i, nb[b]), max(i, nb[b]))] += 1
        return cls(n, sorted(edges), triangles)

    @classmethod
    def cycle_graph(cls, n: int):
        return cls(n, [(i, (i + 1) % n) for i in range(n)])

    @classmethod
    def random_geometric(cls, n: int, radius: float, seed: int = 0, dim: int = 2):
        rng = np.random.default_rng(seed)
        X = rng.random((n, dim))
        return cls.from_knn(X, k=6), X
