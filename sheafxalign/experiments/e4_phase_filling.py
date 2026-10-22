"""E4: Phase diagram + constructive vanishing via cycle filling.

E4a  Genericity: random graph sheaves realize dim H^1 = max(C1 - C0, 0) with
     probability ~1  ->  H^1=0 on graphs is a *dimension budget* condition, not
     an optimization target.
E4b  Quotient family floor: dim H^1 = g*beta1 + sum_e (d_e - g) across a grid;
     floor g*beta1 > 0 uncrossable for d_e >= g.
E4c  Constructive vanishing: chordal completion of the 1-skeleton + full clique
     complex => beta1 = 0 => quotient sheaves with d_e = g have H^1 = 0 exactly,
     for every seed.  Gluing residual for flat edge data collapses to 0.
"""
import json
import numpy as np
import scipy.sparse as sp
from sheafxalign.complex import SimplicialComplex
from sheafxalign.sheaf import CellularSheaf, random_graph_sheaf, ground_quotient_sheaf

rng = np.random.default_rng(23)
res = {"a_genericity": [], "b_floor": [], "c_filling": []}

def const_sheaf_betti1(K):
    dv = {v: 1 for v in range(K.n)}
    de = {e: 1 for e in K.edges}
    dt = {t: 1 for t in K.triangles}
    F = CellularSheaf(K, dv, de, dt,
                      {(w, e): np.ones((1, 1)) for e in K.edges for w in e},
                      {(f, t): np.ones((1, 1)) for t in K.triangles for f, _ in K.boundary_faces(t)},
                      {(w, t): np.ones((1, 1)) for t in K.triangles for w in t})
    return F.cohomology_dims()["dim_H1"]

# ------------------------------------------------------------------- E4a
print("== E4a: genericity phase diagram (graph sheaves) ==")
for d_v in (1, 2, 3, 4):
    for d_e in (1, 2, 3):
        hits, trials = 0, 12
        for t in range(trials):
            n = int(rng.integers(12, 30))
            edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.15]
            if not edges:
                continue
            K = SimplicialComplex(n, edges)
            F = random_graph_sheaf(K, d_v, d_e, seed=t)
            h1 = F.cohomology_dims()["dim_H1"]
            hits += (h1 == max(d_e * K.m - d_v * K.n, 0))
        res["a_genericity"].append({"d_v": d_v, "d_e": d_e, "generic_frac": hits / trials})
        print(f" d_v={d_v} d_e={d_e}: generic-value rate {hits}/{trials}")

# ------------------------------------------------------------------- E4b
print("\n== E4b: quotient family floor on cycle graph (beta1=1) ==")
n = 15
K = SimplicialComplex.cycle_graph(n)
for g in (1, 2, 3):
    for d_e in (g, g + 1, g + 2):
        vals = set()
        for t in range(8):
            F = ground_quotient_sheaf(K, g, d_e, g, seed=t, d_t=g)
            vals.add(F.cohomology_dims()["dim_H1"])
        pred = g * 1 + K.m * (d_e - g)
        res["b_floor"].append({"g": g, "d_e": d_e, "pred": pred, "observed": sorted(vals)})
        print(f" g={g} d_e={d_e}: pred={pred:3d} observed={sorted(vals)} {'OK' if vals == {pred} else 'FAIL'}")

# ------------------------------------------------------------------- E4c
print("\n== E4c: chordal filling => beta1=0 => H^1=0 (quotient, d_e=g) ==")

def chordal_fill(edges, n):
    """Greedy elimination ordering fill-in; returns extra edges."""
    adj = {i: set() for i in range(n)}
    for u, v in edges:
        adj[u].add(v); adj[v].add(u)
    fill = set()
    seen = set()
    G = {i: set(adj[i]) for i in adj}
    while len(seen) < n:
        # min-degree vertex
        v = min((i for i in G if i not in seen), key=lambda i: len(G[i] - {j for j in seen}))
        nb = G[v] - seen
        for a in nb:
            for b in nb:
                if a < b and b not in G[a]:
                    G[a].add(b); G[b].add(a)
                    fill.add((min(a, b), max(a, b)))
        seen.add(v)
    return sorted(fill)

for trial in range(8):
    n = int(rng.integers(16, 42))
    pts = rng.random((n, 2))
    from sheafxalign.complex import SimplicialComplex as SC
    K0 = SC.from_knn(pts, k=5, add_triangles=True, max_tri_per_edge=2)
    b1_before = const_sheaf_betti1(K0)
    fill = chordal_fill(K0.edges, n)
    K1 = SC.from_knn(pts, k=5, add_triangles=False)
    all_edges = sorted(set(K0.edges) | set(fill))
    # full clique triangles of the chordalized graph
    eset = set(all_edges)
    nb = {i: set() for i in range(n)}
    for u, v in all_edges:
        nb[u].add(v); nb[v].add(u)
    tris = []
    for u, v in all_edges:
        common = nb[u] & nb[v]
        for w in common:
            t = tuple(sorted((u, v, w)))
            if t not in tris:
                tris.append(t)
    K1 = SC(n, all_edges, tris)
    b1_after = const_sheaf_betti1(K1)
    g = 2
    h1_before, h1_after = [], []
    glue_before, glue_after = [], []
    for s in range(4):
        F0 = ground_quotient_sheaf(K0, g, g, g, seed=trial * 10 + s, d_t=g)
        F1 = ground_quotient_sheaf(K1, g, g, g, seed=trial * 10 + s, d_t=g)
        h1_before.append(F0.cohomology_dims()["dim_H1"])
        h1_after.append(F1.cohomology_dims()["dim_H1"])
        # gluing test: random flat edge data y (delta1 y = 0) -> distance to im d0
        for F, store in ((F0, glue_before), (F1, glue_after)):
            D0, D1 = F.delta0(), F.delta1()
            # sample cocycles: random y, project out non-flat part by LS onto ker? use SVD of D1
            y = rng.standard_normal(F.dim_C1)
            if F.dim_C2:
                U, s, Vt = np.linalg.svd(D1.toarray(), full_matrices=False)
                rank1 = int(np.sum(s > 1e-9 * (s.max() if len(s) else 1.0)))
                Vc = Vt[rank1:]
                y = Vc.T @ (Vc @ y) if Vc.size else y
            # distance to im d0 via LS
            sol, *_ = np.linalg.lstsq(D0.toarray(), y, rcond=None)
            resid = np.linalg.norm(D0 @ sol - y)
            store.append(float(resid))
    res["c_filling"].append({
        "n": n, "m_before": K0.m, "tri_before": len(K0.triangles), "b1_before": b1_before,
        "m_after": K1.m, "tri_after": len(K1.triangles), "b1_after": b1_after,
        "H1_before": h1_before, "H1_after": h1_after,
        "pred_H1_before": g * b1_before, "glue_resid_before": glue_before,
        "glue_resid_after": glue_after})
    print(f" n={n:3d}: beta1 {b1_before:3d} -> {b1_after:3d} | "
          f"H1 before {h1_before[0]:3d} (pred {g*b1_before:3d}) -> after {sorted(set(h1_after))} | "
          f"glue resid {np.mean(glue_before):.2e} -> {np.mean(glue_after):.2e}")

ok_c = all(r["b1_after"] == 0 and set(r["H1_after"]) == {0} for r in res["c_filling"])
res["summary"] = {"genericity": "see a_genericity",
                  "floor_ok": all(r["observed"] == [r["pred"]] for r in res["b_floor"]),
                  "filling_gives_exact_vanishing": bool(ok_c)}
print("\nSUMMARY:", res["summary"])
with open("results/e4_phase_filling.json", "w") as f:
    json.dump(res, f, indent=2)
