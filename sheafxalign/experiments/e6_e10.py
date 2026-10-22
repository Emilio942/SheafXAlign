"""E6 + E10: Triangle-budget inequality and knife-edge conditioning.

E6 (2-complex generalization of the conservation law):
    dim H^1  >=  dim C^1 - dim C^2 - dim C^0 + dim H^0        (always)
    Derived: rank(d1) <= C^2, ker(d1) >= C^1 - C^2, rank(d0) = C^0 - H^0.
    Consequence: triangles 'buy' obstruction removal at rate C^2; vanishing
    requires C^2 >= C^1 - C^0 + H^0  (quantitative 'fill your cycles').
    Tightness: cone filling achieves equality (verified).
E10: at the critical budget dim C^1 = dim C^0 (the only regime with H^1 = H^0 = 0),
    the restricted problem is ill-conditioned: kappa(d0) measured vs budget offset.
"""
import json
import time
import numpy as np
from sheafxalign.complex import SimplicialComplex as SC
from sheafxalign.sheaf import CellularSheaf, ground_quotient_sheaf, random_graph_sheaf

rng = np.random.default_rng(41)
res = {"e6_inequality": [], "e6_cone_tightness": [], "e6_monotone": [], "e10_conditioning": []}

# ------------------------------------------------------------- E6 sweep
print("== E6: triangle-budget inequality sweep ==")
viol = 0
for trial in range(30):
    n = int(rng.integers(12, 40))
    p = 0.2
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    eset = set(edges)
    tau = rng.uniform(0.1, 0.9)
    tris = [(i, j, k) for i, j in edges for k in range(j + 1, n)
            if (i, k) in eset and (j, k) in eset and rng.random() < tau]
    K = SC(n, edges, tris)
    g = int(rng.integers(1, 4))
    dv = g + int(rng.integers(0, 3))
    de = g + int(rng.integers(0, 2))
    F = ground_quotient_sheaf(K, dv, de, g, seed=trial, d_t=g)
    d = F.cohomology_dims()
    lhs = d["dim_H1"]
    rhs = d["dim_C1"] - d["dim_C2"] - d["dim_C0"] + d["dim_H0"]
    ok = lhs >= rhs
    viol += (not ok)
    res["e6_inequality"].append({"n": n, "m": K.m, "ntri": len(K.triangles), "g": g,
                                 "dim_H1": lhs, "bound": rhs, "holds": bool(ok),
                                 "slack": lhs - rhs})
    if not ok:
        print(f"  VIOLATION trial {trial}: H1={lhs} < bound={rhs}")
print(f" inequality holds in {30 - viol}/30 random quotient sheaves")

# --------------------------------------------------- E6 cone tightness
print("\n== E6: cone filling achieves the bound with equality ==")
for trial in range(10):
    n = int(rng.integers(12, 36))
    pts = rng.random((n, 2))
    K0 = SC.from_knn(pts, k=5, add_triangles=False)
    hub = n
    allE = sorted(set(K0.edges) | {(v, hub) for v in range(n)})
    tris = [tuple(sorted((u, v, hub))) for (u, v) in K0.edges]
    Kf = SC(n + 1, allE, tris)
    g = int(rng.integers(1, 4))
    F = ground_quotient_sheaf(Kf, g, g, g, seed=trial, d_t=g)
    d = F.cohomology_dims()
    lhs = d["dim_H1"]
    rhs = d["dim_C1"] - d["dim_C2"] - d["dim_C0"] + d["dim_H0"]
    res["e6_cone_tightness"].append({"n": n, "m": Kf.m, "ntri": len(Kf.triangles),
                                     "dim_H1": lhs, "bound": rhs,
                                     "tight": lhs == rhs})
    print(f" n+1={n+1:3d} m={Kf.m:4d} tri={len(Kf.triangles):4d} | H1={lhs:2d} bound={rhs:2d} "
          f"{'TIGHT' if lhs == rhs else 'slack'}")

# ----------------------------------- E6 monotonicity: triangles reduce dim H1
print("\n== E6: monotonicity under triangle addition ==")
for trial in range(6):
    n = int(rng.integers(14, 30))
    p = 0.25
    edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
    eset = set(edges)
    cand = [(i, j, k) for i, j in edges for k in range(j + 1, n)
            if (i, k) in eset and (j, k) in eset]
    rng.shuffle(cand)
    K = SC(n, edges)
    g = 2
    hist = []
    batch = max(1, len(cand) // 5)
    for b in range(6):
        take = cand[b * batch:(b + 1) * batch]
        K = SC(n, edges, [t for t in (K.triangles + take)])
        F = ground_quotient_sheaf(K, g, g, g, seed=trial, d_t=g)
        d = F.cohomology_dims()
        hist.append({"ntri": len(K.triangles), "dim_H1": d["dim_H1"], "bound":
                     d["dim_C1"] - d["dim_C2"] - d["dim_C0"] + d["dim_H0"]})
    mono = all(hist[i]["dim_H1"] >= hist[i + 1]["dim_H1"] for i in range(len(hist) - 1))
    res["e6_monotone"].append({"hist": hist, "monotone_decreasing": bool(mono)})
    print(f" trial {trial}: H1 over ntri " +
          " -> ".join(f"({h['ntri']},{h['dim_H1']})" for h in hist) +
          f"  monotone={mono}")

# ------------------------------------------------------------- E10
print("\n== E10: conditioning at the knife-edge budget ==")
for off in (-0.20, -0.05, -0.01, 0.0, 0.01, 0.05, 0.20):
    kappas, h1s, h0s = [], [], []
    for t in range(10):
        n = 24
        K = SC.cycle_graph(n)
        # choose d_e to hit (C1 - C0)/C0 = off :  C0 = n*dv; C1 = m*de
        dv = 4
        de_target = (1 + off) * n * dv / K.m
        de = max(1, int(round(de_target)))
        F = random_graph_sheaf(K, dv, de, seed=t)
        D0 = F.delta0().toarray()
        s = np.linalg.svd(D0, compute_uv=False)
        smax, smin = s.max(), s.min()
        kappa = smax / smin if smin > 1e-12 else np.inf
        d = F.cohomology_dims()
        kappas.append(kappa); h1s.append(d["dim_H1"]); h0s.append(d["dim_H0"])
    res["e10_conditioning"].append({
        "budget_offset": off, "d_e": de, "median_kappa": float(np.median(kappas)),
        "median_H1": int(np.median(h1s)), "median_H0": int(np.median(h0s))})
    print(f" budget offset {off:+.2f} (d_e={de}): median kappa(d0)={np.median(kappas):9.1f} "
          f"H1={int(np.median(h1s)):3d} H0={int(np.median(h0s)):3d}")

res["summary"] = {"e6_violations": viol,
                  "e6_cone_tight_frac": float(np.mean([c["tight"] for c in res["e6_cone_tightness"]])),
                  "e6_monotone_frac": float(np.mean([m["monotone_decreasing"] for m in res["e6_monotone"]])),
                  "e10_knife_edge_kappa": res["e10_conditioning"][3]["median_kappa"]}
print("\nSUMMARY:", res["summary"])
with open("results/e6_e10_bounds_conditioning.json", "w") as f:
    json.dump(res, f, indent=2)
