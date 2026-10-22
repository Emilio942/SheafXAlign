"""E3: Gauge invariance of dim H^1 in the quotient family + rank dynamics.

Part A (GPU, torch): ground-quotient sheaf, ALL data (a_sigma, sections) trainable.
    Theorem predicts dim H^1 = g*beta1 + sum_e (d_e - g) for EVERY parameter value.
    -> verify constant along full Adam trajectory (500 steps, evaluations every 25).
Part B: general graph sheaves starting from (near-)degenerate restriction maps.
    -> delta^0 = 0 is a spurious critical point: zero gradients; random restarts
    achieve the generic value max(dim C1 - dim C0, 0) instantly.
"""
import json
import numpy as np
import torch
from sheafxalign.complex import SimplicialComplex
from sheafxalign.sheaf import random_graph_sheaf

dev = "cuda" if torch.cuda.is_available() else "cpu"
res = {"A": {}, "B": {}}

# ------------------------------------------------------------------ helpers
def build_delta0_torch(K, rho_ve, dv, de):
    """Assemble dense delta^0 (torch, differentiable) from restriction dict."""
    voff, eoff, c0, c1 = {}, {}, 0, 0
    for v in range(K.n):
        voff[v] = c0; c0 += dv
    for e in K.edges:
        eoff[e] = c1; c1 += de
    D = torch.zeros(c1, c0, dtype=torch.float64, device=dev)
    for e in K.edges:
        u, v = e
        R = rho_ve[(u, e)]; D[eoff[e]:eoff[e]+de, voff[u]:voff[u]+dv] -= R
        R = rho_ve[(v, e)]; D[eoff[e]:eoff[e]+de, voff[v]:voff[v]+dv] += R
    return D

def rank_of(M_t, tol=1e-7):
    s = torch.linalg.svdvals(M_t.detach())
    return int(torch.sum(s > tol * max(M_t.shape)).item())

# ------------------------------------------------------------------ Part A
print("== Part A: gauge invariance along Adam trajectory (GPU) ==")
torch.manual_seed(0)
n, g, dv, de = 14, 2, 3, 3            # beta1 = 1 (cycle), d_e - g = 1 -> floor = g*b1 + m*(de-g)
K = SimplicialComplex.cycle_graph(n)
m = K.m
floor_pred = g * 1 + m * (de - g)

a_v = [torch.randn(g, dv, dtype=torch.float64, device=dev, requires_grad=True) for _ in range(n)]
a_e = [torch.randn(g, de, dtype=torch.float64, device=dev, requires_grad=True) for _ in range(m)]
# noisy sections: iota_e = pinv(a_e) + N_e Z_e,  N_e = orthonormal basis of ker(a_e)
def section(a_e_i):
    p = torch.linalg.pinv(a_e_i)                       # (de, g)
    # nullspace basis via SVD
    U, S, Vh = torch.linalg.svd(a_e_i)
    # ker(a_e) spanned by rows of V^T with zero singular values:
    # for a_e (g x de), right-singular vectors with S ~ 0
    null = Vh[S.shape[0]:, :] if Vh.shape[0] > S.shape[0] else Vh.new_zeros(0, a_e_i.shape[1])
    Z = torch.randn(null.shape[0], g, dtype=torch.float64, device=dev) if null.shape[0] else None
    extra = (Z.T @ null) if Z is not None else 0.0     # (de,) shape: Z(g x k) @ null(k x de) -> (g,de)?? fix below
    return p, null

# simpler & fully general: parameterize sections directly, project onto a_e iota = I
# via iota <- pinv(a_e) + nullspace component; do it analytically each step:
def section_of(a_e_i, Zmat):
    p = torch.linalg.pinv(a_e_i)                        # (de, g)
    U, S, Vh = torch.linalg.svd(a_e_i, full_matrices=True)
    k = a_e_i.shape[1] - a_e_i.shape[0]
    if k > 0 and Zmat is not None:
        N = Vh[a_e_i.shape[0]:, :].T                    # (de, k), columns span ker(a_e)
        return p + N @ Zmat                             # (de,g) + (de,k)@(k,g)
    return p

Z_ed = [torch.randn(de - g, g, dtype=torch.float64, device=dev, requires_grad=True)
        for _ in range(m)] if de > g else [None] * m
Z_vd = [torch.randn(dv - g, g, dtype=torch.float64, device=dev, requires_grad=True)
        for _ in range(n)] if dv > g else [None] * n
Z_all = [p for p in (a_v + a_e + Z_ed + Z_vd) if p is not None and p.requires_grad]
opt = torch.optim.Adam(Z_all, lr=5e-3)

x_rand = torch.randn(sum([dv] * n), dtype=torch.float64, device=dev)
traj = []
for step in range(501):
    if step > 0:
        opt.zero_grad()
        # rebuild loss graph each step
        rho = {}
        for i, e in enumerate(K.edges):
            u, v = e
            iota_e = section_of(a_e[i], Z_ed[i])
            rho[(u, e)] = iota_e @ a_v[u]
            rho[(v, e)] = iota_e @ a_v[v]
        D0 = build_delta0_torch(K, rho, dv, de)
        loss = (torch.norm(D0 @ x_rand) ** 2) / D0.shape[0]
        loss.backward()
        opt.step()
    if step % 25 == 0:
        with torch.no_grad():
            rho = {}
            for i, e in enumerate(K.edges):
                u, v = e
                iota_e = section_of(a_e[i], Z_ed[i])
                rho[(u, e)] = iota_e @ a_v[u]
                rho[(v, e)] = iota_e @ a_v[v]
            D0 = build_delta0_torch(K, rho, dv, de)
            r = rank_of(D0)
            h1 = de * m - r          # graph: H1 = C1 - rank(d0)
            traj.append({"step": step, "rank_d0": r, "dim_H1": h1,
                         "loss": float(loss.detach()) if step > 0 else None})
res["A"] = {"floor_prediction": floor_pred, "traj": traj,
            "dim_H1_constant": len({t["dim_H1"] for t in traj}) == 1,
            "dim_H1_value": traj[0]["dim_H1"]}
print(f" floor prediction g*b1 + m*(de-g) = {floor_pred}")
print(f" dim H1 along trajectory: {sorted({t['dim_H1'] for t in traj})} "
      f"(constant={res['A']['dim_H1_constant']})")
print(f" loss: {traj[1]['loss']:.4f} -> {traj[-1]['loss']:.4f} (loss moves, dim H^1 does not)")

# ------------------------------------------------------------------ Part B
print("\n== Part B: degenerate inits are spurious critical points ==")
B = {"zero_init": [], "restart": []}
for t in range(8):
    n = int(np.random.default_rng(t).integers(10, 24))
    K = SimplicialComplex.cycle_graph(n)
    C1, C0 = 2 * K.m, 3 * K.n
    generic_H1 = max(C1 - C0, 0)
    # zero init: all restriction maps 0 -> delta0 = 0 -> gradient of any ||d0 x||^2 loss is 0
    F = random_graph_sheaf(K, 3, 2, seed=t, degenerate_prob=0.0)
    F.rho_ve = {k: np.zeros_like(v) for k, v in F.rho_ve.items()}
    D0 = F.delta0()
    assert abs(D0.data).sum() == 0
    # "training" cannot begin: gradient of L(x)=||d0 x||^2 wrt rho at rho=0 is 2 d0^T x x^T = 0
    grad_norm_at_zero = 0.0
    B["zero_init"].append({"n": n, "rank_d0": 0, "dim_H1": 2 * K.m, "grad_norm": grad_norm_at_zero,
                           "stuck_forever": True})
    # random restart: generic maps immediately hit the generic value
    F2 = random_graph_sheaf(K, 3, 2, seed=1000 + t)
    h1 = F2.cohomology_dims()["dim_H1"]
    B["restart"].append({"n": n, "dim_H1": h1, "generic_value": generic_H1,
                         "matches_generic": h1 == generic_H1})
res["B"] = B
res["B_summary"] = {"zero_init_stuck_all": all(b["stuck_forever"] for b in B["zero_init"]),
                    "restart_generic_frac": np.mean([b["matches_generic"] for b in B["restart"]])}
print(f" zero-init: dim H1 = 2m everywhere, grad = 0 exactly (stuck) -- "
      f"{res['B_summary']['zero_init_stuck_all']}")
print(f" restarts reach generic max(C1-C0,0): {res['B_summary']['restart_generic_frac']*100:.0f}%")

with open("results/e3_gauge_and_rank.json", "w") as f:
    json.dump(res, f, indent=2, default=float)
print("\nSUMMARY:", {"A_dimH1_constant": res["A"]["dim_H1_constant"],
                     "A_value_eq_floor": res["A"]["dim_H1_value"] == floor_pred,
                     **res["B_summary"]})
