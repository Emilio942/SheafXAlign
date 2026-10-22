"""E8: Learnability of the spectral (Hodge) penalty through autograd-eigh (GPU).

Family: vertex-transfer sheaves on cycles (functorial by construction:
rho_{v<=e} = W_v in R^{d x d}, rho_{e<=t} = I, rho_{v<=t} = W_v;
W_v = I recovers the constant sheaf, dim H^1 = d * beta_1).

Regimes
  R1 unfilled cycle, d_v = d_e  : knife-edge; H^1 = d (at W=I); zero possible
      only in the ill-conditioned square case.  Question: does the spectral
      penalty find it, and what happens to kappa(d0)?
  R2 filled cycle (cone)        : H^1 = 0 by design; penalty starts ~0;
      question: stability under optimization.
  R3 quotient-family control    : floor g*beta1 + sum(d_e - g) invariant;
      question: plateau (no gradient signal can cross it).

Penalty  L(rho) = sum_{i<=k} softplus((tau - lambda_i(Delta^1))/tau)^2,
lambdas = ascending eigenvalues of Delta^1, autograd through torch.linalg.eigh.
"""
import json
import numpy as np
import torch
from sheafxalign.complex import SimplicialComplex as SC

dev = "cuda" if torch.cuda.is_available() else "cpu"
torch.manual_seed(7)
res = {"R1": [], "R2": [], "R3": []}


def build_sheaf_torch(K, W, d):
    """Vertex-transfer sheaf: delta0 and delta1 as torch matrices (functorial)."""
    n = K.n
    voff = {v: v * d for v in range(n)}
    eoff, acc_e = {}, 0
    for e in K.edges:
        eoff[e] = acc_e; acc_e += d
    toff, acc_t = {}, 0
    for t in K.triangles:
        toff[t] = acc_t; acc_t += d
    D0 = torch.zeros(acc_e, n * d, dtype=torch.float64, device=dev)
    for e in K.edges:
        u, v = e
        D0[eoff[e]:eoff[e] + d, voff[u]:voff[u] + d] -= W[u]
        D0[eoff[e]:eoff[e] + d, voff[v]:voff[v] + d] += W[v]
    D1 = torch.zeros(acc_t, acc_e, dtype=torch.float64, device=dev)
    for t in K.triangles:
        for f, s in K.boundary_faces(t):
            D1[toff[t]:toff[t] + d, eoff[f]:eoff[f] + d] += s * torch.eye(d, dtype=torch.float64, device=dev)
    return D0, D1


def dims_np(D0, D1, tol=1e-8):
    a = D0.detach().cpu().numpy()
    b = D1.detach().cpu().numpy()
    r0 = np.linalg.matrix_rank(a, tol=tol * max(a.shape)) if a.size else 0
    n1 = b.shape[1] - (np.linalg.matrix_rank(b, tol=tol * max(b.shape)) if b.size else 0)
    return r0, n1 - r0


def kappa_np(D0):
    s = torch.linalg.svdvals(D0.detach())
    s = s[s > 1e-12]
    return float(s.max() / s.min()) if len(s) else float("inf")


def run_regime(name, K, d, init, steps=2500, k=8, tau=0.25, lr=8e-3, seeds=3):
    out = []
    for seed in range(seeds):
        torch.manual_seed(100 * seed + seed)
        n = K.n
        if init == "identity":
            W = [torch.eye(d, dtype=torch.float64, device=dev, requires_grad=True) for _ in range(n)]
        else:  # small random perturbation of identity (breaks symmetry, keeps invertible)
            W = [(torch.eye(d) + 0.15 * torch.randn(d, d)).to(torch.float64).to(dev).requires_grad_(True)
                 for _ in range(n)]
        opt = torch.optim.Adam(W, lr=lr)
        traj = []
        for step in range(steps + 1):
            if step > 0:
                opt.zero_grad()
                D0, D1 = build_sheaf_torch(K, W, d)
                lam = torch.linalg.eigvalsh(D0 @ D0.T + D1.T @ D1)
                loss = (torch.nn.functional.softplus((tau - lam[:k]) / tau) ** 2).sum()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(W, 10.0)
                opt.step()
            if step % 250 == 0:
                with torch.no_grad():
                    D0, D1 = build_sheaf_torch(K, W, d)
                    r0, h1 = dims_np(D0, D1)
                    lam = torch.linalg.eigvalsh(D0 @ D0.T + D1.T @ D1)
                    traj.append({"step": step, "dim_H1": int(h1), "rank_d0": int(r0),
                                 "loss": float((torch.nn.functional.softplus((tau - lam[:k]) / tau) ** 2).sum()),
                                 "kappa_d0": kappa_np(D0)})
        out.append({"seed": seed, "traj": traj,
                    "H1_start": traj[0]["dim_H1"], "H1_end": traj[-1]["dim_H1"],
                    "loss_start": traj[0]["loss"], "loss_end": traj[-1]["loss"],
                    "kappa_end": traj[-1]["kappa_d0"]})
        print(f" {name} seed {seed}: H1 {traj[0]['dim_H1']} -> {traj[-1]['dim_H1']}  "
              f"loss {traj[0]['loss']:.3e} -> {traj[-1]['loss']:.3e}  kappa(d0)={traj[-1]['kappa_d0']:.1f}")
    return out


d = 4
print("== R1: unfilled cycle (knife-edge square case) ==")
K1 = SC.cycle_graph(12)
res["R1"] = run_regime("R1", K1, d, init="perturbed")
print("\n== R2: cone-filled cycle (H1=0 by design, stability) ==")
n = 12
hub = n
K2 = SC(n + 1, sorted(set(K1.edges) | {(v, hub) for v in range(n)}),
        [tuple(sorted((u, v, hub))) for (u, v) in K1.edges])
res["R2"] = run_regime("R2", K2, d, init="identity")
print("\n== R3: quotient-family floor control (plateau expected) ==")
from sheafxalign.sheaf import ground_quotient_sheaf
K3 = SC.cycle_graph(12)
F3 = ground_quotient_sheaf(K3, 2, 2, 1, seed=0, d_t=1)   # d_e = g+1 -> floor = 1*1 + 12*1 = 13
floor = 1 * 1 + 12 * (2 - 1)
# emulate: vertex-transfer with W_v = pinv(a_e)a_v style is not in torch builder;
# instead run R1-family but with W constrained to rank-1 projectors via low-rank
# parametrization W_v = B_v A_v, A_v(1xd), B_v(dx1): quotient-like gauge family.
class QuotientParam(torch.nn.Module):
    def __init__(self, n, d, g=1):
        super().__init__()
        self.A = torch.nn.Parameter(torch.randn(n, g, d, dtype=torch.float64) * 0.5)
        self.B = torch.nn.Parameter(torch.randn(n, d, g, dtype=torch.float64) * 0.5)
    def Ws(self, dev):
        return [ (self.B[i] @ self.A[i]).to(dev) for i in range(self.A.shape[0]) ]

def run_quotient(K, d, g=1, steps=2500, k=8, tau=0.25, lr=8e-3, seeds=3):
    out = []
    for seed in range(seeds):
        torch.manual_seed(500 + seed)
        P = QuotientParam(K.n, d, g).to(dev)
        opt = torch.optim.Adam([P.A, P.B], lr=lr)
        traj = []
        for step in range(steps + 1):
            if step > 0:
                opt.zero_grad()
                D0, D1 = build_sheaf_torch(K, P.Ws(dev), d)
                lam = torch.linalg.eigvalsh(D0 @ D0.T + D1.T @ D1)
                loss = (torch.nn.functional.softplus((tau - lam[:k]) / tau) ** 2).sum()
                loss.backward(); opt.step()
            if step % 250 == 0:
                with torch.no_grad():
                    D0, D1 = build_sheaf_torch(K, P.Ws(dev), d)
                    r0, h1 = dims_np(D0, D1)
                    traj.append({"step": step, "dim_H1": int(h1)})
        out.append({"seed": seed, "traj": traj, "H1_start": traj[0]["dim_H1"],
                    "H1_end": traj[-1]["dim_H1"], "floor_pred": 1 * 1 + K.m * (d - g)})
        print(f" R3 seed {seed}: H1 {traj[0]['dim_H1']} -> {traj[-1]['dim_H1']} "
              f"(floor pred {out[-1]['floor_pred']})")
    return out

res["R3"] = run_quotient(K3, d)

for R, key in ((res["R1"], "R1"), (res["R2"], "R2"), (res["R3"], "R3")):
    res.setdefault("summary", {})[f"{key}_H1_moved_frac"] = float(np.mean([r["H1_start"] != r["H1_end"] for r in R]))
res["summary"]["R1_kappa_end_median"] = float(np.median([r["kappa_end"] for r in res["R1"]]))
print("\nSUMMARY:", res["summary"])
with open("results/e8_spectral_learnability.json", "w") as f:
    json.dump(res, f, indent=2, default=float)
