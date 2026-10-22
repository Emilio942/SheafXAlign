"""Cellular sheaves on simplicial complexes (dim <= 2) with sparse coboundaries.

Conventions
-----------
* 0-cochains:  x in C^0 =  +_v V_v
* 1-cochains:  y in C^1 =  +_e V_e
* 2-cochains:  z in C^2 =  +_t V_t
* (delta^0 x)(e=(u,v)) = rho_{v<=e} x_v - rho_{u<=e} x_u
* (delta^1 y)(t)       = sum_{(f,s) in boundary(t)} s * rho_{f<=t} y_f
* Cohomology: dim H^0 = dim C^0 - rank(d0);  dim H^1 = nullity(d1) - rank(d0)
* Hodge: dim H^1 = dim ker(Delta^1),  Delta^1 = d0 d0^T + d1^T d1

Functoriality
-------------
On graphs (height-1 poset) functoriality is vacuous -> arbitrary random maps OK.
For 2-complexes we use the **ground-quotient construction** (exact functoriality):

    Ground space G = R^g.  Every cell sigma carries
        a_sigma : V_sigma -> G      (random epimorphism,  d_sigma >= g),
    and a chosen section iota_sigma : G -> V_sigma (canonical: pinv(a_sigma)).
    Restrictions:
        rho_{v<=e} = iota_e a_v,   rho_{e<=t} = iota_t a_e,   rho_{v<=t} = iota_t a_v
    Then rho_{e<=t} rho_{v<=e} = iota_t (a_e iota_e) a_v = iota_t a_v = rho_{v<=t}.  [exact]

    Interpretation: G is the shared semantic quotient; H^1 measures the residual
    obstruction to synchronizing local quotient data across the complex.
"""
from __future__ import annotations
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from .complex import SimplicialComplex


class CellularSheaf:
    """Stalk dims per cell + restriction matrices; sparse coboundaries/Laplacians."""

    def __init__(self, K: SimplicialComplex, dv: dict, de: dict, dt: dict | None = None,
                 rho_ve: dict | None = None, rho_et: dict | None = None,
                 rho_vt: dict | None = None):
        self.K = K
        self.dv = dict(dv)
        self.de = dict(de)
        self.dt = dict(dt or {t: 0 for t in K.triangles})
        self.rho_ve = rho_ve or {}
        self.rho_et = rho_et or {}
        self.rho_vt = rho_vt or {}
        self._voff = self._offset(self.dv, range(K.n))
        self._eoff = self._offset(self.de, K.edges)
        self._toff = self._offset(self.dt, K.triangles)
        self.dim_C0 = sum(self.dv.values())
        self.dim_C1 = sum(self.de.values())
        self.dim_C2 = sum(self.dt.values())

    @staticmethod
    def _offset(dims, cells):
        off, acc = {}, 0
        for c in cells:
            off[c] = acc
            acc += dims[c]
        return off

    # ------------------------------------------------------------- coboundary
    def delta0(self) -> sp.csr_matrix:
        rows, cols, vals = [], [], []
        for e in self.K.edges:
            u, v = e
            r0 = self._eoff[e]
            for w, sign in ((u, -1.0), (v, +1.0)):
                R = self.rho_ve.get((w, e))
                if R is None:
                    continue
                R = np.asarray(R, dtype=np.float64)
                rr, cc = np.nonzero(R)
                rows.extend(r0 + rr)
                cols.extend(self._voff[w] + cc)
                vals.extend((sign * R)[rr, cc])
        return sp.csr_matrix((vals, (rows, cols)), shape=(self.dim_C1, self.dim_C0))

    def delta1(self) -> sp.csr_matrix:
        if self.dim_C2 == 0:
            return sp.csr_matrix((0, self.dim_C1))
        rows, cols, vals = [], [], []
        for t in self.K.triangles:
            r0 = self._toff[t]
            for f, s in self.K.boundary_faces(t):
                R = self.rho_et.get((f, t))
                if R is None:
                    continue
                R = np.asarray(R, dtype=np.float64)
                rr, cc = np.nonzero(R)
                rows.extend(r0 + rr)
                cols.extend(self._eoff[f] + cc)
                vals.extend((s * R)[rr, cc])
        return sp.csr_matrix((vals, (rows, cols)), shape=(self.dim_C2, self.dim_C1))

    def commutator_error(self) -> float:
        """||delta^1 delta^0||_F -- must be ~0 for genuine cohomology."""
        if self.dim_C2 == 0:
            return 0.0
        M = (self.delta1() @ self.delta0())
        return float(sp.linalg.norm(M)) if M.nnz else 0.0

    # -------------------------------------------------------------- laplacians
    def laplacians(self):
        D0, D1 = self.delta0(), self.delta1()
        L0 = (D0.T @ D0).tocsr()
        L1 = (D0 @ D0.T).tocsr()
        if D1.shape[0]:
            L1 = (L1 + D1.T @ D1).tocsr()
        return D0, D1, L0, L1

    # -------------------------------------------------------------- cohomology
    def cohomology_dims(self, tol=1e-8):
        D0, D1 = self.delta0(), self.delta1()
        r0 = _rank(D0, tol)
        n1 = self.dim_C1 - _rank(D1, tol) if self.dim_C2 else self.dim_C1
        return {
            "dim_C0": self.dim_C0, "dim_C1": self.dim_C1, "dim_C2": self.dim_C2,
            "rank_d0": r0, "null_d1": n1,
            "dim_H0": self.dim_C0 - r0,
            "dim_H1": n1 - r0,
        }

    def smallest_eigs_L1(self, k: int = 24, tol=1e-7):
        """Smallest eigenvalues of Delta^1 via shift-invert around sigma=-1
        (robust against large kernel multiplicity; L1 + I is SPD)."""
        _, _, _, L1 = self.laplacians()
        n = L1.shape[0]
        if n == 0:
            return np.array([])
        if n <= 800:
            return np.sort(np.linalg.eigvalsh(L1.toarray()))[:k]
        k = min(k, max(1, n - 2))
        vals = spla.eigsh(L1, k=k, sigma=-1.0, which="LM",
                          return_eigenvectors=False)
        return np.sort(vals)


def _rank(M: sp.csr_matrix, tol=1e-8) -> int:
    m, n = M.shape
    if m == 0 or n == 0:
        return 0
    k = min(m, n)
    if max(m, n) <= 3000:
        s = np.linalg.svd(M.toarray(), compute_uv=False)
    else:
        s = spla.svds(M, k=k - 1, which="LM", return_singular_vectors=False)
        s = np.concatenate([s, [0.0]])  # the k-th smallest is 0 if rank < k
    return int(np.sum(s > tol * max(M.shape)))


# ----------------------------------------------------------------- generators
def random_graph_sheaf(K: SimplicialComplex, d_v: int, d_e: int, seed: int = 0,
                       scale: float = 1.0, degenerate_prob: float = 0.0):
    """Arbitrary Gaussian restriction maps (functoriality vacuous on graphs)."""
    rng = np.random.default_rng(seed)
    dv = {v: d_v for v in range(K.n)}
    de = {e: d_e for e in K.edges}
    rho = {}
    for e in K.edges:
        for w in e:
            if rng.random() < degenerate_prob:
                rho[(w, e)] = np.zeros((d_e, d_v))
            else:
                rho[(w, e)] = scale * rng.standard_normal((d_e, d_v)) / np.sqrt(d_v)
    return CellularSheaf(K, dv, de, rho_ve=rho)


def ground_quotient_sheaf(K: SimplicialComplex, d_v: int, d_e: int, g: int,
                          seed: int = 0, d_t: int | None = None,
                          defective: bool = False):
    """Functorial sheaf on a 2-complex via the ground-quotient construction.

    d_e >= g required (else a_e cannot be epi; `defective=True` skips the check
    to produce non-functoriality stress data).
    """
    rng = np.random.default_rng(seed)
    if not defective:
        assert d_e >= g and (d_t is None or d_t >= g), "need d_e,d_t >= g for epimorphisms"
    def rmap(d_out, d_in):
        return rng.standard_normal((d_out, d_in)) / np.sqrt(d_in)

    dv = {v: d_v for v in range(K.n)}
    de = {e: d_e for e in K.edges}
    dt = {t: (d_t if d_t is not None else g) for t in K.triangles}

    a_v = {v: rmap(g, d_v) for v in range(K.n)}
    a_e = {e: rmap(g, d_e) for e in K.edges}
    a_t = {t: rmap(g, dt[t]) for t in K.triangles} if K.triangles else {}
    iota_e = {e: np.linalg.pinv(a_e[e]) for e in K.edges}
    iota_t = {t: np.linalg.pinv(a_t[t]) for t in K.triangles}

    rho_ve, rho_et, rho_vt = {}, {}, {}
    for e in K.edges:
        for w in e:
            rho_ve[(w, e)] = iota_e[e] @ a_v[w]
    for t in K.triangles:
        for f, _ in K.boundary_faces(t):
            rho_et[(f, t)] = iota_t[t] @ a_e[f]
        for w in t:
            rho_vt[(w, t)] = iota_t[t] @ a_v[w]
    return CellularSheaf(K, dv, de, dt, rho_ve, rho_et, rho_vt)
