"""E1 v2: Correctness + Hodge verification + conservation law + quotient formula.

Checks
  (0) constant sheaf on K reproduces classical Betti numbers
  (a) ground-quotient sheaves: ||delta1 delta0||_F ~ 0   (functoriality exact)
  (b) Hodge:       dim ker(Delta^1) == dim H^1
  (c) conservation on graphs:  dim H^1 - dim H^0 == dim C^1 - dim C^0
  (d) ground-quotient sheaves, connected, any dim <= 2:
        dim H^0 = sum_v d_v - (n-1) g
        dim H^1 = g * beta1(K) + sum_e (d_e - g)
"""
import json
import numpy as np
from sheafxalign.complex import SimplicialComplex
from sheafxalign.sheaf import CellularSheaf, random_graph_sheaf, ground_quotient_sheaf


def kernel_dim_L1(F: CellularSheaf, tol=1e-7) -> int:
    _, _, _, L1 = F.laplacians()
    n = L1.shape[0]
    if n == 0:
        return 0
    if n <= 2500:
        ev = np.linalg.eigvalsh(L1.toarray())
        return int(np.sum(ev < tol))
    ev = F.smallest_eigs_L1(k=200)
    return int(np.sum(ev < tol)) if len(ev) < 200 else -1  # -1 = capped


def betti1(K: SimplicialComplex) -> int:
    """dim H^1(K; R) via the constant sheaf (sanity check vs classical topology)."""
    dv = {v: 1 for v in range(K.n)}
    de = {e: 1 for e in K.edges}
    dt = {t: 1 for t in K.triangles}
    rho_ve = {(w, e): np.ones((1, 1)) for e in K.edges for w in e}
    rho_et = {(f, t): np.ones((1, 1)) for t in K.triangles for f, _ in K.boundary_faces(t)}
    rho_vt = {(w, t): np.ones((1, 1)) for t in K.triangles for w in t}
    Fc = CellularSheaf(K, dv, de, dt, rho_ve, rho_et, rho_vt)
    return Fc.cohomology_dims()["dim_H1"]


rng = np.random.default_rng(7)
results = {"graph_checks": [], "quotient_checks": [], "betti_checks": []}

# ------------------------------------------------------- (0) classical sanity
print("== constant sheaf reproduces Betti numbers ==")
for trial in range(4):
    n = int(rng.integers(10, 30))
    p = 0.3
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    eset = set(edges)
    tris = [(i, j, k) for i, j in edges for k in range(j + 1, n)
            if (i, k) in eset and (j, k) in eset and rng.random() < 0.7]
    K = SimplicialComplex(n, edges, tris)
    b1 = betti1(K)
    # classical reference: beta1 = m - n + c - rank(d2) ; compute via null spaces
    import scipy.sparse as sp
    d2 = sp.lil_matrix((K.m, len(K.triangles)))
    for ti, t in enumerate(K.triangles):
        for f, s in K.boundary_faces(t):
            d2[K.edge_index[f], ti] = s
    rk = np.linalg.matrix_rank(d2.toarray()) if len(K.triangles) else 0
    ref = K.m - K.n + 1 - rk
    results["betti_checks"].append({"n": K.n, "m": K.m, "ntri": len(K.triangles),
                                    "betti1_sheaf": b1, "betti1_ref": int(ref)})
    print(f" n={K.n:3d} m={K.m:3d} tri={len(K.triangles):3d} | beta1(sheaf)={b1:3d} ref={ref:3d} "
          f"{'OK' if b1 == ref else 'MISMATCH'}")

# ---------------------------------------------------------------- (a)-(c) graphs
print("\n== graph sheaves: Hodge + conservation law ==")
for trial in range(10):
    n = int(rng.integers(8, 60))
    p = 0.15
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    if not edges:
        continue
    K = SimplicialComplex(n, edges)
    dv, de = int(rng.integers(1, 6)), int(rng.integers(1, 4))
    F = random_graph_sheaf(K, dv, de, seed=trial)
    dims = F.cohomology_dims()
    kdim = kernel_dim_L1(F)
    ok_hodge = (kdim == dims["dim_H1"])
    ok_cons = (dims["dim_H1"] - dims["dim_H0"] == dims["dim_C1"] - dims["dim_C0"])
    results["graph_checks"].append({
        "n": n, "m": K.m, "d_v": dv, "d_e": de,
        "dim_H0": dims["dim_H0"], "dim_H1": dims["dim_H1"], "ker_Delta1": kdim,
        "hodge_ok": bool(ok_hodge), "conservation_ok": bool(ok_cons)})
    print(f" n={n:3d} m={K.m:3d} dv={dv} de={de} | H0={dims['dim_H0']:3d} H1={dims['dim_H1']:3d} "
          f"kerD1={kdim:3d} | hodge={ok_hodge} cons={ok_cons}")

# ------------------------------------------------- (a),(b),(d) quotient sheaves
print("\n== ground-quotient sheaves (2-complexes) ==")
for trial in range(10):
    n = int(rng.integers(10, 40))
    p = 0.25
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    eset = set(edges)
    tris = [(i, j, k) for i, j in edges for k in range(j + 1, n)
            if (i, k) in eset and (j, k) in eset and rng.random() < 0.5]
    K = SimplicialComplex(n, edges, tris)
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    A = sp.lil_matrix((K.n, K.n))
    for u, v in K.edges:
        A[u, v] = A[v, u] = 1
    ncomp = connected_components(A.tocsr(), directed=False)[0]
    g = int(rng.integers(1, 4))
    dv = g + int(rng.integers(0, 3))
    de = g + int(rng.integers(0, 3))
    F = ground_quotient_sheaf(K, dv, de, g, seed=100 + trial, d_t=g)
    cerr = F.commutator_error()
    dims = F.cohomology_dims()
    kdim = kernel_dim_L1(F)
    b1 = betti1(K)
    pred_H0 = dims["dim_C0"] - (K.n - ncomp) * g
    pred_H1 = g * b1 + sum(F.de[e] - g for e in K.edges)
    ok = (dims["dim_H0"] == pred_H0) and (dims["dim_H1"] == pred_H1) and (kdim == dims["dim_H1"])
    results["quotient_checks"].append({
        "n": K.n, "m": K.m, "n_tri": len(K.triangles), "g": g, "beta1": b1,
        "d_v": dv, "d_e": de, "comm_err": cerr,
        "dim_H0": dims["dim_H0"], "pred_H0": pred_H0,
        "dim_H1": dims["dim_H1"], "pred_H1": pred_H1,
        "ker_Delta1": kdim, "formula_ok": bool(ok)})
    results.setdefault("commutator_errors", []).append(cerr)
    print(f" n={K.n:3d} m={K.m:3d} tri={len(K.triangles):3d} g={g} b1={b1:3d} | "
          f"|d1d0|={cerr:.1e} | H0={dims['dim_H0']:3d}/{pred_H0:3d} "
          f"H1={dims['dim_H1']:3d}/{pred_H1:3d} kerD1={kdim:3d} | ok={ok}")

all_hodge = all(c["hodge_ok"] for c in results["graph_checks"])
all_cons = all(c["conservation_ok"] for c in results["graph_checks"])
all_form = all(c["formula_ok"] for c in results["quotient_checks"])
all_betti = all(c["betti1_sheaf"] == c["betti1_ref"] for c in results["betti_checks"])
max_comm = max(results["commutator_errors"])
results["summary"] = {"hodge_all_ok": bool(all_hodge), "conservation_all_ok": bool(all_cons),
                      "quotient_formula_all_ok": bool(all_form), "betti_all_ok": bool(all_betti),
                      "max_commutator_err": float(max_comm)}
print(f"\nSUMMARY: betti={all_betti} hodge={all_hodge} conservation={all_cons} "
      f"quotient_formula={all_form} max|d1d0|={max_comm:.2e}")
with open("results/e1_hodge_conservations.json", "w") as f:
    json.dump(results, f, indent=2)
