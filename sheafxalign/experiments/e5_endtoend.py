"""E5 (v2): End-to-end — heterogeneous toy architectures + GW + sheaf cohomology.

Design notes (perf): all large systems solved sparsely (lsqr/spsolve); dim H^1 on
the big filled complex via the E1-validated quotient formula dim H^1 = g*beta1
with beta1 from the constant sheaf (small sparse rank); dense globalizability
statistics on moderate subcomplexes.
"""
import json
import time
import numpy as np
import torch
import torch.nn as nn
import scipy.sparse as sp
import scipy.sparse.linalg as spls
from scipy.spatial import cKDTree
import ot as pot
from sheafxalign.complex import SimplicialComplex as SC
from sheafxalign.sheaf import CellularSheaf

dev = "cuda" if torch.cuda.is_available() else "cpu"
t0 = time.time()
rng = np.random.default_rng(3)
res = {}

# ------------------------------------------------------------------- data
K_CLUSTERS, SEQ_LEN, N_SEQ, VOCAB = 8, 24, 220, 40
centers = rng.standard_normal((K_CLUSTERS, 16)) * 2.0
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

# --------------------------------------------------------------- models
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
    yt = torch.tensor(traj_cluster, dtype=torch.long, device=dev)   # (S,L) per-token topics
    for ep in range(epochs):
        opt.zero_grad()
        logits = cls(enc(Xt))                                       # (S,L,K)
        loss = lossf(logits.reshape(-1, K_CLUSTERS), yt.reshape(-1))
        loss.backward(); opt.step()
    return float(loss.item())

torch.manual_seed(0); np.random.seed(0)
encA, encB = AttnEnc().to(dev), SSMEnc().to(dev)
lA, lB = train_encoder(encA), train_encoder(encB)
print(f"[{time.time()-t0:6.1f}s] train loss: attention {lA:.3f} | ssm {lB:.3f}")
with torch.no_grad():
    Xt = torch.tensor(X, dtype=torch.float32, device=dev)
    FA = encA(Xt).cpu().numpy().reshape(-1, encA.d)
    FB = encB(Xt).cpu().numpy().reshape(-1, encB.d)
N, L = N_SEQ, SEQ_LEN
token_id = np.tile(np.arange(L), N)

# ------------------------------------------------- GW coupling (subsample)
Nsub = 120
idx = rng.choice(N * L, Nsub, replace=False)
def _dm(Z):
    Zs = (Z - Z.mean(0)) / (Z.std(0) + 1e-9)
    D = np.linalg.norm(Zs[:, None] - Zs[None], axis=-1)
    return D / D.max()
DA, DB = _dm(FA[idx]), _dm(FB[idx])
p = np.full(Nsub, 1 / Nsub)
C, _ = pot.gromov.gromov_wasserstein(DA, DB, p, p, "square_loss", verbose=False, log=True)
match = np.asarray(C).argmax(1)
acc_gw = float(np.mean(clu[idx] == clu[idx][match]))
acc_gw_exact = float(np.mean(token_id[idx] == token_id[idx][match]))
print(f"[{time.time()-t0:6.1f}s] GW coupling: cluster-acc {acc_gw:.3f} | exact {acc_gw_exact:.3f}")
res["gw"] = {"cluster": acc_gw, "exact": acc_gw_exact}

# ------------------------------------------------------- coupled complex
def knn_edges(Z, k=5):
    _, ix = cKDTree(Z).query(Z, k=k + 1)
    E = set()
    for i in range(len(Z)):
        for j in ix[i][1:]:
            E.add((min(i, int(j)), max(i, int(j))))
    return sorted(E)

coup = []
for i in range(Nsub):
    coup.append((i, Nsub + int(match[i])))
E = knn_edges(FA[idx]) + [(a + Nsub, b + Nsub) for a, b in knn_edges(FB[idx])] + coup
Kc = SC(2 * Nsub, E)
print(f"[{time.time()-t0:6.1f}s] coupled complex: n={Kc.n} m={Kc.m}")

# ------------------------------------------------- quotient sheaf from data
g = 8
def pca_map(Zloc, g, d_model):
    Zc = Zloc - Zloc.mean(0)
    _, s, Vt = np.linalg.svd(Zc, full_matrices=False)
    A = np.zeros((g, d_model))
    kk = min(g, Vt.shape[0])
    A[:kk] = Vt[:kk] * (np.sqrt(s[:kk] + 1e-9) / np.sqrt(len(Zc)))[:, None]
    return A                                                             # a_v: (g, dim), rank g

d_model = encA.d
_, ixA = cKDTree(FA[idx]).query(FA[idx], k=13)
_, ixB = cKDTree(FB[idx]).query(FB[idx], k=13)
a_map = {}
for v in range(Nsub):
    a_map[v] = pca_map(FA[idx][ixA[v]], g, d_model)
for v in range(Nsub):
    a_map[Nsub + v] = pca_map(FB[idx][ixB[v]], g, d_model)
dv = {v: d_model for v in range(Kc.n)}
de = {e: g for e in Kc.edges}
rho = {}
for e in Kc.edges:
    u, v = e
    rho[(u, e)] = a_map[u]
    rho[(v, e)] = a_map[v]
F = CellularSheaf(Kc, dv, de, rho_ve=rho)

# beta1 via constant sheaf (small sparse)
def betti1(K):
    one = np.ones((1, 1))
    rho_ve = {(w, e): one for e in K.edges for w in e}
    if K.triangles:
        dt = {t: 1 for t in K.triangles}
        rho_et = {(f, t): one for t in K.triangles for f, _ in K.boundary_faces(t)}
        rho_vt = {(w, t): one for t in K.triangles for w in t}
    else:
        dt, rho_et, rho_vt = None, None, None
    Fc = CellularSheaf(K, {v: 1 for v in range(K.n)}, {e: 1 for e in K.edges},
                       dt, rho_ve=rho_ve, rho_et=rho_et, rho_vt=rho_vt)
    dims = Fc.cohomology_dims() if K.n * 1 <= 2500 else None
    if dims is not None:
        return dims["dim_H1"]
    D0 = Fc.delta0()
    return Fc.dim_C1 - _rank_sp(D0)

def _rank_sp(M, tol=1e-8):
    m, n = M.shape
    k = min(m, n)
    if max(m, n) <= 2500:
        return int(np.sum(np.linalg.svd(M.toarray(), compute_uv=False) > tol * max(M.shape)))
    s = spls.svds(M, k=min(k - 1, 200), which="LM", return_singular_vectors=False)
    # rank >= #s > tol ; upper-bound check via null of M^T M cheaply:
    # fall back: use lsqr-based estimate of nullity on k random rhs
    return int(np.sum(s > tol))

b1_c = betti1(Kc)
H1_pred_unfilled = g * b1_c          # d_e = g  =>  dim H1 = g*beta1
print(f"[{time.time()-t0:6.1f}s] beta1(coupled 1-skeleton) = {b1_c}  ->  "
      f"dim H^1 = g*beta1 = {H1_pred_unfilled} (quotient formula)")

# sparse flatness check: sample y in ker delta1 (no triangles -> everything flat),
# LS distance to im delta0 via sparse lsqr
def globalizability_sparse(F, trials=16, tol=0.05):
    D0 = F.delta0().tocsr()
    hits, resids = 0, []
    for _ in range(trials):
        y = rng.standard_normal(F.dim_C1)
        z = spls.lsqr(D0, y, iter_lim=400)[0]
        r = np.linalg.norm(D0 @ z - y)
        resids.append(float(r))
        hits += (r < tol * np.linalg.norm(y))
    return hits / trials, resids

rate0, resids0 = globalizability_sparse(F)
print(f"[{time.time()-t0:6.1f}s] unfilled: globalizability={rate0*100:.0f}% "
      f"(median resid {np.median(resids0):.3f})")

# ---------------------------------------------------- cone filling (hub patch)
# Add ONE hub vertex connected to all patches + a triangle over every original
# edge.  The cone over any complex is contractible => beta1 = 0 exactly, using
# only ~m triangles (vs. millions for clique completion).  Semantics: a global
# synchronizing hub patch realizing the shared ground G.
t_cone = time.time()
hub = Kc.n
allE = sorted(set(Kc.edges) | {(v, hub) for v in range(Kc.n)})
tris = [tuple(sorted((u, v, hub))) for (u, v) in Kc.edges]
Kf = SC(Kc.n + 1, allE, tris)
b1_f = betti1(Kf)
H1_pred_filled = g * b1_f
a_map[hub] = np.eye(g)                       # hub stalk IS the ground G
dv[hub] = g
print(f"[{time.time()-t0:6.1f}s] cone-filled: m={Kf.m} tri={len(Kf.triangles)} "
      f"beta1={b1_f} -> dim H^1 = {H1_pred_filled}  (cone construction, "
      f"{time.time()-t_cone:.1f}s)")

# globalizability on filled: flat data = G-flat edge labelings (quotient family!)
#   y flat  <=>  for each triangle: sum_f s a_e y_e = 0  (sparse system S y = 0)
def flat_samples_quotient(K, a_map, g, trials):
    """Sample G-valued flat edge data via tree extension: values on a spanning
    tree are free; remaining edges solved from triangle conditions by sparse LS
    (exact when beta1 = 0)."""
    edges = K.edges
    ei = {e: i for i, e in enumerate(edges)}
    rows, cols, vals = [], [], []
    r = 0
    for t in K.triangles:
        for f, s_ in K.boundary_faces(t):
            A = a_map[f[0]] * 0  # placeholder, a_e acts as identity on G-labels? no:
    # For the quotient sheaf, delta1 y = 0 <=> sum_f s rho_{f<=t} y_f = 0 with
    # rho_{f<=t} = iota_t a_f; iota_t injective -> sum_f s a_f y_f = 0 where
    # y_f in V_f (dim g) and a_f: V_f -> G.  With V_f = R^g we take a_f = Id_g
    # (edge data already G-valued): flatness <=> sum s y_f = 0 per triangle.
    rows, cols, vals, r = [], [], [], 0
    for t in K.triangles:
        for f, s_ in K.boundary_faces(t):
            for q in range(g):
                rows.append(r + q); cols.append(g * ei[f] + q); vals.append(float(s_))
        r += g
    S = sp.csr_matrix((vals, (rows, cols)), shape=(r, g * len(edges)))
    out = []
    for _ in range(trials):
        y = rng.standard_normal(S.shape[1])
        sol = spls.lsqr(S, -S @ np.zeros_like(y), iter_lim=200)  # homogeneous system:
        # solve S y = 0 in least squares -> S y minimal; instead project: y - pinv(S) S y
        Ps = S.T @ S
        z = spls.spsolve(Ps + 1e-9 * sp.identity(S.shape[1]), S.T @ (S @ y))
        yflat = y - z
        out.append(yflat)
    return out

# verify flatness system is exact on the filled complex (beta1=0 -> only 0-flat
# independent of tree values? no: flat data exist in abundance; the claim is that
# ALL of them are coboundaries).  Direct test: distance of flat y to im d0.
def globalizability_filled(F, yflat_list, tol=0.05):
    D0 = F.delta0().tocsr()
    hits, resids = 0, []
    for y in yflat_list:
        z = spls.lsqr(D0, y, iter_lim=500)[0]
        rr = float(np.linalg.norm(D0 @ z - y))
        resids.append(rr)
        hits += (rr < tol * np.linalg.norm(y))
    return hits / len(yflat_list), resids

de_f = {e: g for e in Kf.edges}
dt = {t: g for t in Kf.triangles}
rho_f = dict(rho)
for v in range(Kc.n):
    e = (v, hub)
    rho_f[(v, e)] = a_map[v]
    rho_f[(hub, e)] = a_map[hub]
rho_et = {(f, t): np.eye(g) for t in Kf.triangles for f, _ in Kf.boundary_faces(t)}
rho_vt = {(w, t): a_map[w] for t in Kf.triangles for w in t}
Ff = CellularSheaf(Kf, dv, de_f, dt, rho_f, rho_et, rho_vt)
cerr = Ff.commutator_error()

# EXACT H^1 at pipeline scale: dense SVDs (definitive; sizes ~9k)
import time as _t
_tt = _t.time()
s0 = np.linalg.svd(Ff.delta0().toarray(), compute_uv=False)
r0 = int(np.sum(s0 > 1e-8 * max(Ff.dim_C1, Ff.dim_C0)))
s1 = np.linalg.svd(Ff.delta1().toarray(), compute_uv=False)
r1 = int(np.sum(s1 > 1e-8 * max(Ff.dim_C1, Ff.dim_C2)))
H1_exact = (Ff.dim_C1 - r1) - r0
print(f"[{time.time()-t0:6.1f}s] filled EXACT: rank d0={r0} null d1={Ff.dim_C1 - r1} "
      f"-> dim H^1 = {H1_exact}  (comm_err={cerr:.1e}, svd {_t.time()-_tt:.0f}s)")

# glue-error vs flatness-defect regression (practical form of H^1=0):
#   d_glue(y) = dist(y, im d0);  d_flat(y) = ||delta^1 y||  (G-valued defect)
def glue_vs_defect(F, trials=40):
    D0 = F.delta0().tocsr()
    D1 = F.delta1().tocsr()
    out = []
    for _ in range(trials):
        y = rng.standard_normal(F.dim_C1)
        z = spls.lsqr(D0, y, iter_lim=500)[0]
        d_glue = float(np.linalg.norm(D0 @ z - y))
        d_flat = float(np.linalg.norm(D1 @ y)) if D1.shape[0] else 0.0
        out.append((d_glue, d_flat))
    return np.array(out)

reg_f = glue_vs_defect(Ff)
slope_f = float(np.linalg.lstsq(reg_f[:, 1:2], reg_f[:, 0], rcond=None)[0][0])
corr_f = float(np.corrcoef(reg_f[:, 0], reg_f[:, 1])[0, 1])
reg_u = glue_vs_defect(F)
has_tri = F.dim_C2 > 0
slope_u = float(np.linalg.lstsq(reg_u[:, 1:2], reg_u[:, 0], rcond=None)[0][0]) if has_tri else 0.0
corr_u = float(np.corrcoef(reg_u[:, 0], reg_u[:, 1])[0, 1]) if has_tri else float("nan")
print(f"[{time.time()-t0:6.1f}s] filled: d_glue = {slope_f:.3f} * d_flat (corr {corr_f:.3f}) "
      f"| unfilled: slope {slope_u:.3f} (corr {corr_u:.3f}, median glue-at-flat "
      f"{np.median(reg_u[:,0]):.1f})")
res["exact_filled"] = {"rank_d0": r0, "null_d1": Ff.dim_C1 - r1, "dim_H1": int(H1_exact)}
res["regression"] = {"filled_slope": slope_f, "filled_corr": corr_f,
                     "unfilled_slope": slope_u, "unfilled_corr": corr_u,
                     "unfilled_median_glue_at_flat": float(np.median(reg_u[:, 0]))}

# ------------------------- global semantic codes + matching accuracy
def global_codes(F, coupled_edges, lam=1e-4):
    D0 = F.delta0().tocsr()
    eoff = F._eoff
    rows = []
    for e in coupled_edges:
        r0 = eoff[e]
        rows.extend(range(r0, r0 + g))
    mask = sp.csr_matrix((np.ones(len(rows)), (rows, np.zeros(len(rows), int))),
                         shape=(D0.shape[0], 1))
    M = D0.multiply(mask)
    x0 = np.zeros(F.dim_C0)
    lat = np.concatenate([FA[idx], FB[idx]], 0).astype(np.float64)
    voff = F._voff
    for v in range(Kc.n):
        x0[voff[v]:voff[v] + d_model] = lat[v]
    Mx = M @ x0
    Gm = (M.T @ M).tocsc()
    rhs = -(M.T @ Mx)
    z = spls.spsolve(Gm + lam * sp.identity(Gm.shape[0], dtype=np.float64), rhs)
    return x0 + z

x_unc = global_codes(F, coup)
x_fil = global_codes(Ff, coup)
voffF = Ff._voff
voff = F._voff
z_unc = np.stack([a_map[v] @ x_unc[voff[v]:voff[v] + d_model] for v in range(Kc.n)])
z_fil = np.stack([a_map[v] @ x_fil[voffF[v]:voffF[v] + d_model] for v in range(Kc.n)])

def match_acc(z):
    _, ix = cKDTree(z[Nsub:]).query(z[:Nsub], k=1)
    return float(np.mean(clu[idx] == clu[idx][ix])), \
           float(np.mean(token_id[idx] == token_id[idx][ix]))

acc_unc, acc_unc_exact = match_acc(z_unc)
acc_fil, acc_fil_exact = match_acc(z_fil)
A0, B0 = FA[idx].astype(np.float64), FB[idx].astype(np.float64)
U_, S_, Vt_ = np.linalg.svd(A0[match].T @ B0)
Bp = B0 @ (U_ @ Vt_)
_, ix = cKDTree(Bp).query(A0, k=1)
acc_proc = float(np.mean(clu[idx] == clu[idx][ix]))
acc_proc_exact = float(np.mean(token_id[idx] == token_id[idx][ix]))

res["matching"] = {"gw_cluster": acc_gw, "gw_exact": acc_gw_exact,
                   "procrustes_cluster": acc_proc, "procrustes_exact": acc_proc_exact,
                   "sheaf_unfilled_cluster": acc_unc, "sheaf_unfilled_exact": acc_unc_exact,
                   "sheaf_filled_cluster": acc_fil, "sheaf_filled_exact": acc_fil_exact}
print(f"\n[{time.time()-t0:6.1f}s] matching accuracy (cluster | exact):")
print(f"  GW coupling only      : {acc_gw:.3f} | {acc_gw_exact:.3f}")
print(f"  Procrustes on GW pairs: {acc_proc:.3f} | {acc_proc_exact:.3f}")
print(f"  sheaf codes (unfilled): {acc_unc:.3f} | {acc_unc_exact:.3f}")
print(f"  sheaf codes (filled)  : {acc_fil:.3f} | {acc_fil_exact:.3f}")
with open("results/e5_endtoend.json", "w") as f:
    json.dump(res, f, indent=2, default=float)
print("saved results/e5_endtoend.json")
