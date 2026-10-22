"""E2: The framework objective L_sheaf(x) = ||delta^0 x||^2 is cohomologically blind.

Claims tested numerically
  (C1) min_x L(x) = 0 identically (x=0), for ALL sheaves, in particular those with
       dim H^1 > 0  ->  the unconstrained objective carries no H^1 information.
  (C2) The constrained minimum min_{||x||=1} L(x) = lambda_min(Delta^0) detects
       dim H^0 (it is 0 iff H^0 != 0), NOT dim H^1:  construct sheaves with
         (H^1>0, L*>0), (H^1>0, L*=0), (H^1=0, L*>0), (H^1=0, L*=0)  -- all four.
  (C3) Parameter-independence: H^1 depends only on restriction maps rho, while x is
       the only variable coupled to L in  min_{pi,x} dGW + lambda L(x).
       Optimizing x to convergence over many random rho leaves dim H^1 unchanged.
"""
import json
import numpy as np
from sheafxalign.complex import SimplicialComplex
from sheafxalign.sheaf import random_graph_sheaf, ground_quotient_sheaf

rng = np.random.default_rng(11)
res = {"C1": [], "C2_regimes": [], "C3": []}

def constrained_min_L0(F, trials=64):
    """min_{||x||=1} ||D0 x||^2 = smallest eigenvalue of Delta^0."""
    D0, _, L0, _ = F.laplacians()
    n = L0.shape[0]
    ev = np.linalg.eigvalsh(L0.toarray()) if n <= 2500 else None
    return float(ev[0]) if ev is not None else None

# ---------------------------------------------------------------- C1
print("== C1: unconstrained min ||d0 x||^2 ==")
for t in range(6):
    K = SimplicialComplex.cycle_graph(int(rng.integers(6, 30)))
    F = random_graph_sheaf(K, 3, 2, seed=t)
    dims = F.cohomology_dims()
    x0 = rng.standard_normal(F.dim_C0)
    L_uncon = float(np.linalg.norm(F.delta0() @ x0) ** 2)
    x_star = np.zeros(F.dim_C0)
    L_min = float(np.linalg.norm(F.delta0() @ x_star) ** 2)
    res["C1"].append({"dim_H1": dims["dim_H1"], "L_at_random_x": L_uncon,
                      "L_at_x0": L_min, "min_is_zero": L_min == 0.0})
    print(f" dim H1={dims['dim_H1']:3d} | L(random x)={L_uncon:9.3f}  L(x=0)={L_min:.1f}"
          f"  -> objective minimized by x=0 regardless of H^1")

# ---------------------------------------------------------------- C2 regimes
print("\n== C2: four regimes (H^1, lambda_min(Delta^0)) ==")
regimes = {}
# (a) H1>0, L*>0 : generic random graph sheaf, dim C1 > dim C0
K = SimplicialComplex.cycle_graph(12)
F = random_graph_sheaf(K, 4, 2, seed=1)   # C1=24, C0=48 -> wait C1<C0 here
F = random_graph_sheaf(K, 2, 4, seed=1)   # C1=48, C0=24 -> H0=0, H1=24
dims = F.cohomology_dims(); lm = constrained_min_L0(F)
regimes["a_H1pos_Lpos"] = (dims["dim_H1"], dims["dim_H0"], lm)
# (b) H1>0, L*=0 : quotient sheaf on cycle, d_v = g (constant section kernel)
K = SimplicialComplex.cycle_graph(12)
F = ground_quotient_sheaf(K, d_v=2, d_e=2, g=1, seed=2)  # H0 = 24 - 11 = 13 > 0, H1 = 1*b1 + 12*1
dims = F.cohomology_dims(); lm = constrained_min_L0(F)
regimes["b_H1pos_Lzero"] = (dims["dim_H1"], dims["dim_H0"], lm)
# (c) H1=0, L*>0 : generic sheaf with dim C1 < dim C0 and full row rank d0
K = SimplicialComplex.cycle_graph(12)
F = random_graph_sheaf(K, 4, 2, seed=3)   # C1=24 < C0=48, rank d0=24 -> H1=0, H0=24... wait H0 = C0-rank = 24 >0 -> L*=0
# need H0=0 AND H1=0 -> rank d0 = C0 = C1 -> dim C1 = dim C0 exactly, knife edge:
F = random_graph_sheaf(K, 3, 3, seed=3)   # C1=C0=36, generic full rank both ways
dims = F.cohomology_dims(); lm = constrained_min_L0(F)
regimes["c_H1zero_Lpos"] = (dims["dim_H1"], dims["dim_H0"], lm)
# (d) H1=0, L*=0 : same knife-edge but rank-deficient d0 (degenerate maps)
F = random_graph_sheaf(K, 3, 3, seed=4, degenerate_prob=1.0)  # d0 = 0 -> H0=36, H1=0
dims = F.cohomology_dims(); lm = constrained_min_L0(F)
regimes["d_H1zero_Lzero"] = (dims["dim_H1"], dims["dim_H0"], lm)
for k, (h1, h0, lm) in regimes.items():
    res["C2_regimes"].append({"regime": k, "dim_H1": h1, "dim_H0": h0, "lambda_min_D0": lm})
    print(f" {k:18s} dim H1={h1:3d} dim H0={h0:3d}  lambda_min(D0)={lm:9.3e}")
# lambda_min ~ 0 iff dim H0 > 0 :  (a) h1>0,h0=0 -> L>0 ; (b) h1>0,h0>0 -> L~0
lam_a = regimes["a_H1pos_Lpos"][2]; lam_b = regimes["b_H1pos_Lzero"][2]
blind = (lam_a > 1e-3) and (lam_b < 1e-6) and regimes["a_H1pos_Lpos"][0] > 0 and regimes["b_H1pos_Lzero"][0] > 0
res["C2_conclusion_blind_to_H1"] = bool(blind)
print(f" -> H^1-blindness confirmed: {blind}  (objective sees H^0, not H^1)")

# ---------------------------------------------------------------- C3
print("\n== C3: optimizing x never changes dim H^1 ==")
changed = 0
for t in range(40):
    n = int(rng.integers(8, 25))
    K = SimplicialComplex.cycle_graph(n)
    F = random_graph_sheaf(K, 3, 2, seed=100 + t)
    dims_before = F.cohomology_dims()["dim_H1"]
    D0 = F.delta0()
    # gradient descent on x: L(x)=||D0 x||^2 ; many steps
    x = rng.standard_normal(F.dim_C0)
    G = (D0.T @ D0).toarray()
    for _ in range(300):
        x -= 0.01 * (G @ x)
    dims_after = F.cohomology_dims()["dim_H1"]
    if dims_before != dims_after:
        changed += 1
    res["C3"].append({"dim_H1_before": dims_before, "dim_H1_after": dims_after})
res["C3_summary"] = {"runs": 40, "dim_H1_changed": changed}
print(f" runs=40, dim H1 changed in {changed} runs (x-optimization cannot touch H^1(rho))")

res["summary"] = {"C1_all_min_zero": all(r["min_is_zero"] for r in res["C1"]),
                  "C2_blind": bool(blind), "C3_unchanged": changed == 0}
print("\nSUMMARY:", res["summary"])
with open("results/e2_naive_objective.json", "w") as f:
    json.dump(res, f, indent=2)
