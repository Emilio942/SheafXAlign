# SheafXAlign

**Cellular sheaf cohomology over discrete latent patch complexes for cross-architecture
optimal transport alignment — a negative result with a constructive resolution.**

> **TL;DR.** The research program asks whether one can enforce
> $\mathrm{H}^1(K;\mathcal{F}) \equiv 0$ — the vanishing of the first sheaf cohomology
> group — over a shared patch complex $K$, so that locally consistent cross-architecture
> alignments glue into a globally consistent pullback metric. **Answer: not by
> optimization.** $\dim \mathrm{H}^1$ is an integer-valued, locally constant,
> gauge-invariant quantity with a provable topological floor $g\,\beta_1(K)$.
> Gradient-based training of restriction maps cannot cross it (verified: 0/9 runs).
> **But it is achievable by design**: one hub patch (a cone) fills all cycles
> ($\beta_1 = 0$), and budgeting edge stalks at the shared semantic dimension
> ($d_e = g$) yields $\mathrm{H}^1 = 0$ *exactly* for every parameter draw —
> flat local data then glues globally, in linear time, at scale.

---

## What is here

A complete empirical study (7 theorems/verdicts, 9 experiment suites, all reproducible)
that answers the question

> *"How can cellular sheaf cohomology be formulated over discrete latent patch complexes
> to construct a globally consistent pullback metric, such that the 1st sheaf cohomology
> group H¹ vanishes identically, thereby eliminating local semantic obstructions during
> cross-architecture optimal transport alignment?"*

with a **sharp negative** for the optimization route and a **constructive recipe** for
the design route.

### Results at a glance

| # | Result | Status | Evidence |
|---|--------|--------|----------|
| 1 | **Conservation law** (graphs): $\dim H^1 - \dim H^0 = \dim C^1 - \dim C^0$ — obstructions are transferred, never destroyed | theorem, 10/10 exact | E1 |
| 2 | **Quotient formula** ($\dim \le 2$): $\dim H^0 = \sum_v d_v - (n{-}c)g$, $\dim H^1 = g\beta_1 + \sum_e (d_e - g)$ | theorem, 10/10 + 9/9 | E1, E4b |
| 3 | **Irreducible floor** $\dim H^1 \ge g\beta_1$; gauge-invariant under *all* restriction/section updates | theorem, GPU trajectory constant | E3 |
| 4 | **H¹-blindness** of the framework objective $\|\delta^0 x\|^2$: measures $H^0$, not $H^1$ | 4-regime proof + 40/40 invariance | E2 |
| 5 | **Triangle-budget inequality** $\dim H^1 \ge C^1 - C^2 - C^0 + H^0$, tight on cones; exact $-g$ per filled cycle | theorem, 30/30 + 10/10 + 6/6 | E6 |
| 6 | **Knife-edge fragility**: the unique-gluing budget $C^1 = C^0$ pays $\sim 34\times$ conditioning | $\kappa \approx 580$ vs $18$ | E10 |
| 7 | **Spectral penalties are H¹-blind regularizers**: loss improves, integer floors never crossed (0/9) | settles prior valid/invalid conflicts | E8 |
| 8 | **Sheaf-code → GW feedback is an immediate fixed point**: zero accuracy effect in 4/4 instances | GW variance dominates | E7 |
| 9 | **Scaling**: obstruction grows linearly in $n$; the cone solution is linear-time and exactly vanishing | $3212 \to 62\,148$ obstruction units, 0.034 s fill | E9 |

### The constructive recipe

$$\mathrm{H}^1(K;\mathcal{F}) \equiv 0 \quad\Longleftrightarrow\quad \big[\,\beta_1(K) = 0 \;\wedge\; d_e = g\,\big]$$

1. **Fill the cycles of the base complex** by attaching a single hub patch: star edges to
   all vertices plus one triangle per original edge. The cone is contractible
   ($\beta_1 = 0$), costs $O(m)$, and is interpretable as a global synchronizing hub.
2. **Budget edge stalks at the semantic dimension** ($d_e = g$, the ground/quotient
   dimension of the sheaf).
3. Then every *flat* (admissible) local alignment pattern glues **exactly**
   (SVD-verified at full pipeline scale: $\operatorname{rank}\delta^0 = \operatorname{nullity}\delta^1$),
   the residual glue error is linearly controlled by the flatness defect
   ($d_{\text{glue}} \approx 0.58\, d_{\text{flat}}$), and "admissible" collapses onto
   "globally consistent".

Without filling, flat data generically fails to glue outright (0% globalizability,
$\dim H^1 = g\beta_1$, e.g. $62\,148$ obstruction dimensions at $n = 2000$ patches).

### Honest scope

The sheaf layer delivers **consistency certification** (glueability of flat local data),
not correspondence *accuracy*: coupling quality is inherited from the Gromov–Wasserstein
solver and was unchanged by the sheaf constraint in our pipelines (E5, E7). Attacking
accuracy requires non-isometric/learned codes jointly optimized with the transport
objective — a separate question.

---

## Installation & reproduction

```bash
python -m venv .venv
.venv/bin/pip install numpy scipy networkx matplotlib pot
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu121  # or plain torch

# experiment suites (each writes JSON evidence into results/)
.venv/bin/python -m sheafxalign.experiments.e1_hodge              # Hodge + conservation + quotient formula
.venv/bin/python -m sheafxalign.experiments.e2_naive_objective    # H¹-blindness of ‖δ⁰x‖²
.venv/bin/python -m sheafxalign.experiments.e3_gauge_and_rank     # gauge invariance (GPU/Adam), rank dynamics
.venv/bin/python -m sheafxalign.experiments.e4_phase_filling      # genericity, floor grid, cycle filling
.venv/bin/python -m sheafxalign.experiments.e5_endtoend           # attention vs SSM, GW, cone filling (≈3 min on GPU)
.venv/bin/python -m sheafxalign.experiments.e6_e10                # triangle-budget inequality, knife-edge conditioning
.venv/bin/python -m sheafxalign.experiments.e7_iterated [seed]    # iterated GW ↔ sheaf codes
.venv/bin/python -m sheafxalign.experiments.e8_spectral           # spectral penalty learnability (autograd eigh)
.venv/bin/python -m sheafxalign.experiments.e9_scaling            # scaling sweep n = 100 … 2000
```

All suites are deterministic (fixed seeds); totals run in a few minutes on a laptop GPU
and in ~10 minutes CPU-only.

## Repository layout

```
sheafxalign/
  complex.py            simplicial complexes (dim ≤ 2), kNN / cycle generators
  sheaf.py              cellular sheaves, sparse coboundaries δ⁰, δ¹, sheaf Laplacians,
                        cohomology dimensions, ground-quotient generator (exact functoriality)
  experiments/          E1–E10 as above
results/                JSON evidence for every claim in this README
SheafXAlign.md          full research log: 105 cycles of formal verification
                        (hypothesis → proof → verdict), including the failures
```

## Why publish a negative result

The vanishing requirement $\mathrm{H}^1 \equiv 0$ appears repeatedly in sheaf-based
learning proposals. This repository pins down *why* gradient-based enforcement cannot
work (integer invariants, gauge floors, conservation of obstruction) and *what to do
instead* (base-complex design). The full research log documents every failed mechanism
along the way — model categories, spectral sequences, Morse theory, persistent cohomology,
random sheaves — with formal proofs of each verdict.

## License

Apache-2.0 (see `LICENSE`).
