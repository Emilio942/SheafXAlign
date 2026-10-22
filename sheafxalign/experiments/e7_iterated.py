"""E7: Iterated GW <-> sheaf codes. Does the cohomologically consistent embedding
feed back into the coupling and improve correspondence accuracy?

Protocol
  z^0 = raw latents            GW on dist(z^0)          -> acc_0
  z^{t+1} = cone-sheaf codes   GW on dist(z^{t+1})      -> acc_{t+1}
  (3 rounds; codes from harmonic extension of coupled-edge consistency)
Controls
  C1: iterate GW on raw distances with re-randomized entropic init (GW non-convexity)
  C2: iterate GW on Procrustes-aligned latents
Evaluation: cluster accuracy + exact cell accuracy vs ground truth.
"""
import json
import time
import numpy as np
import torch
import torch.nn as nn
from scipy.spatial import cKDTree
import ot as pot
from sheafxalign.complex import SimplicialComplex as SC
from sheafxalign.sheaf import CellularSheaf
import scipy.sparse as sp
import scipy.sparse.linalg as spls

dev = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
import sys
BASE_SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 3
rng = np.random.default_rng(BASE_SEED)

# ---------------------------------------- data + encoders (same task as E5)
K_CLUSTERS, SEQ_LEN, N_SEQ, VOCAB = 8, 24, 220, 40
trans = np.full((K_CLUSTERS, K_CLUSTERS), 0.05)
for i in range(K_CLUSTERS):
    trans[i, (i + 1) % K_CLUSTERS] = 0.6
    trans[i, (i + 2) % K_CLUSTERS] = 0.2
trans /= trans.sum(1, keepdims=True)
vocab_emb = rng.standard_normal((VOCAB, 16))
cluster_of_vocab = rng.integers(0, K_CLUSTERS, VOCAB)
seqs, traj_cluster = [], []
for _ in range(N_SEQ):
    c = rng.integers(0, K_CLUSTERS)
    toks, cs = [], []
    for _ in range(SEQ_LEN):
        toks.append(int(rng.choice(VOCAB) if rng.random() < 0.15
                     else rng.choice(np.where(cluster_of_vocab == c)[0])))
        cs.append(c)
        c = rng.choice(K_CLUSTERS, p=trans[c])
    seqs.append(toks); traj_cluster.append(cs)
seqs = np.array(seqs); traj_cluster = np.array(traj_cluster)
clu = traj_cluster.reshape(-1)
X = vocab_emb[seqs]

class AttnEnc(nn.Module):
    def __init__(self, d_in=16, d=32):
        super().__init__()
        self.inp = nn.Linear(d_in, d)
        self.q = nn.Linear(d, d); self.k = nn.Linear(d, d); self.v = nn.Linear(d, d)
        self.d = d
    def forward(self, x):
        h = torch.tanh(self.inp(x))
        att = torch.softmax(self.q(h) @ self.k(h).transpose(-2, -1) / self.d ** 0.5, dim=-1)
        return att @ self.v(h)

class SSMEnc(nn.Module):
    def __init__(self, d_in=16, d=32):
        super().__init__()
        self.B = nn.Linear(d_in, d); self.d = d
        self.A = nn.Parameter(torch.eye(d) * 0.9 + 0.05 * torch.randn(d, d))
    def forward(self, x):
        b, L, _ = x.shape
        h = torch.zeros(b, self.d, device=x.device)
        outs = []
        for t in range(L):
            h = torch.tanh(h @ self.A + self.B(x[:, t]))
            outs.append(h)
        return torch.stack(outs, dim=1)

def train_encoder(enc, epochs=400):
    cls = nn.Linear(enc.d, K_CLUSTERS).to(dev)
    opt = torch.optim.Adam(list(enc.parameters()) + list(cls.parameters()), lr=3e-3)
    lossf = nn.CrossEntropyLoss()
    Xt = torch.tensor(X, dtype=torch.float32, device=dev)
    yt = torch.tensor(traj_cluster, dtype=torch.long, device=dev)
    for ep in range(epochs):
        opt.zero_grad()
        loss = lossf(cls(enc(Xt)).reshape(-1, K_CLUSTERS), yt.reshape(-1))
        loss.backward(); opt.step()
    return float(loss.item())

torch.manual_seed(0); np.random.seed(0)
encA, encB = AttnEnc().to(dev), SSMEnc().to(dev)
train_encoder(encA); train_encoder(encB)
with torch.no_grad():
    Xt = torch.tensor(X, dtype=torch.float32, device=dev)
    FA = encA(Xt).cpu().numpy().reshape(-1, encA.d)
    FB = encB(Xt).cpu().numpy().reshape(-1, encB.d)
N, L = N_SEQ, SEQ_LEN
token_id = np.tile(np.arange(L), N)
print(f"[{time.time()-t0:5.1f}s] encoders trained")

Nsub = 120
idx = rng.choice(N * L, Nsub, replace=False)
clu_s, tok_s = clu[idx], token_id[idx]

def dist_mat(Z):
    Zs = (Z - Z.mean(0)) / (Z.std(0) + 1e-9)
    D = np.linalg.norm(Zs[:, None] - Zs[None], axis=-1)
    return D / D.max()

def gw_match(ZA, ZB, seed=0):
    DA, DB = dist_mat(ZA), dist_mat(ZB)
    p = np.full(len(ZA), 1 / len(ZA))
    C, _ = pot.gromov.gromov_wasserstein(DA, DB, p, p, "square_loss", verbose=False, log=True)
    return np.asarray(C).argmax(1)

def accs(match):
    return (float(np.mean(clu_s == clu_s[match])), float(np.mean(tok_s == tok_s[match])))

# ------------------------------------------------ cone-sheaf code machinery
g = 8
def knn_ix(Z, k=13):
    _, ix = cKDTree(Z).query(Z, k=k)
    return ix

def pca_map(Zloc, g, d_model):
    Zc = Zloc - Zloc.mean(0)
    _, s, Vt = np.linalg.svd(Zc, full_matrices=False)
    A = np.zeros((g, d_model))
    kk = min(g, Vt.shape[0])
    A[:kk] = Vt[:kk] * (np.sqrt(s[:kk] + 1e-9) / np.sqrt(len(Zc)))[:, None]
    return A

d_model = encA.d
def build_codes(ZA, ZB, match):
    n = len(ZA)
    Kc = SC(2 * n, [(i, i) for i in range(0)] , [])  # placeholder
    E = set()
    for v in range(n):
        for u in knn_ix(ZA, 8)[v][1:]:
            E.add((min(v, int(u)), max(v, int(u))))
    for v in range(n):
        for u in knn_ix(ZB, 8)[v][1:]:
            E.add((n + min(v, int(u)), n + max(v, int(u))))
    for i in range(n):
        E.add((i, n + int(match[i])))
    edges = sorted(E)
    Kc = SC(2 * n, edges)
    hub = 2 * n
    allE = sorted(set(Kc.edges) | {(v, hub) for v in range(2 * n)})
    tris = [tuple(sorted((u, v, hub))) for (u, v) in Kc.edges]
    Kf = SC(2 * n + 1, allE, tris)
    a_map = {}
    ixA, ixB = knn_ix(ZA), knn_ix(ZB)
    for v in range(n):
        a_map[v] = pca_map(ZA[ixA[v]], g, d_model)
        a_map[n + v] = pca_map(ZB[ixB[v]], g, d_model)
    a_map[hub] = np.eye(g)
    dv = {v: d_model for v in range(2 * n)}; dv[hub] = g
    de = {e: g for e in Kf.edges}
    rho = {}
    for e in Kf.edges:
        u, v = e
        rho[(u, e)] = a_map[u]
        rho[(v, e)] = a_map[v]
    dt = {t: g for t in Kf.triangles}
    rho_et = {(f, t): np.eye(g) for t in Kf.triangles for f, _ in Kf.boundary_faces(t)}
    rho_vt = {(w, t): a_map[w] for t in Kf.triangles for w in t}
    Ff = CellularSheaf(Kf, dv, de, dt, rho, rho_et, rho_vt)
    # harmonic extension of coupled-edge consistency
    D0 = Ff.delta0().tocsr()
    eoff = Ff._eoff
    rows = []
    for i in range(n):
        r0 = eoff[(i, n + int(match[i]))]
        rows.extend(range(r0, r0 + g))
    mask = sp.csr_matrix((np.ones(len(rows)), (rows, np.zeros(len(rows), int))),
                         shape=(D0.shape[0], 1))
    M = D0.multiply(mask)
    x0 = np.zeros(Ff.dim_C0)
    lat = np.concatenate([ZA, ZB], 0).astype(np.float64)
    voff = Ff._voff
    for v in range(2 * n):
        x0[voff[v]:voff[v] + d_model] = lat[v]
    Mx = M @ x0
    Gm = (M.T @ M).tocsc()
    rhs = -(M.T @ Mx)
    z = spls.spsolve(Gm + 1e-4 * sp.identity(Gm.shape[0], dtype=np.float64), rhs)
    x = x0 + z
    codes = np.stack([a_map[v] @ x[voff[v]:voff[v] + d_model] for v in range(2 * n)])
    return codes[:n], codes[n:]

# ------------------------------------------------------- iteration
log = {"rounds": [], "controls": [], "base_seed": BASE_SEED}
ZA, ZB = FA[idx].astype(np.float64), FB[idx].astype(np.float64)
m = gw_match(ZA, ZB)
a, e = accs(m)
print(f"[{time.time()-t0:5.1f}s] round 0 (raw):     cluster {a:.3f} | exact {e:.3f}")
log["rounds"].append({"round": 0, "cluster": a, "exact": e})
for it in range(1, 4):
    cA, cB = build_codes(ZA, ZB, m)
    m = gw_match(cA, cB)
    a, e = accs(m)
    print(f"[{time.time()-t0:5.1f}s] round {it} (sheaf codes): cluster {a:.3f} | exact {e:.3f}")
    log["rounds"].append({"round": it, "cluster": a, "exact": e})

# control C1: GW restarts on raw distances (non-convexity spread)
accs_c1 = []
for s in range(5):
    DA, DB = dist_mat(ZA), dist_mat(ZB)
    p = np.full(Nsub, 1 / Nsub)
    rng2 = np.random.default_rng(s)
    q0 = rng2.random(Nsub); q0 /= q0.sum()
    q1 = rng2.random(Nsub); q1 /= q1.sum()
    C = pot.gromov.entropic_gromov_wasserstein(DA, DB, q0, q1, "square_loss",
                                               epsilon=0.05, verbose=False)
    a, e = accs(np.asarray(C).argmax(1))
    accs_c1.append(a)
print(f"[{time.time()-t0:5.1f}s] control C1 (entropic restarts on raw): "
      f"cluster {min(accs_c1):.3f}-{max(accs_c1):.3f} (mean {np.mean(accs_c1):.3f})")
log["controls"].append({"name": "entropic_restarts", "accs": accs_c1})

# control C2: iterate GW on Procrustes-aligned latents
U_, S_, Vt_ = np.linalg.svd(ZA[m].T @ ZB)
Bp = ZB @ (U_ @ Vt_)
m2 = gw_match(ZA, Bp)
a, e = accs(m2)
print(f"[{time.time()-t0:5.1f}s] control C2 (Procrustes-iterated): cluster {a:.3f} | exact {e:.3f}")
log["controls"].append({"name": "procrustes_iterated", "cluster": a, "exact": e})

best_sheaf = max(r["cluster"] for r in log["rounds"])
log["summary"] = {"raw_gw_cluster": log["rounds"][0]["cluster"],
                  "best_iterated_sheaf_cluster": best_sheaf,
                  "improvement": best_sheaf - log["rounds"][0]["cluster"],
                  "entropic_restart_mean": float(np.mean(accs_c1))}
print("\nSUMMARY:", log["summary"])
with open("results/e7_iterated.json", "w") as f:
    json.dump(log, f, indent=2, default=float)
