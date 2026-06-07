# Math-Soundness Fuzz Bot — Design

**Date:** 2026-06-05
**Status:** Approved (pending spec review)
**Scope:** Property-based fuzz testing of the DemandIQ forecasting/balancing numeric pipeline.

## 1. Goal & Philosophy

Build a property-based tester that generates **valid random corridors** and asserts the
forecasting math obeys its invariants for *any* input — not just the handful of hand-picked
examples the current example-based suite covers.

This tests **soundness on valid inputs** (conservation, non-negativity, convergence,
ordering), not malformed-input/validation fuzzing. The generators always produce
structurally valid corridors; the assertions check that the math the engine produces is
sound.

**Motivating evidence.** The corridor-order invariant — links must follow the *given*
intersection order, never re-sorted by intersection number — has broken three separate
times (legacy `3_demand_analysis.py` QC, live `balancer.py run_qc`, frontend S7
ResultsMap). A property test that generates corridors in randomly permuted intersection
order and asserts links are never re-sorted would have caught all three mechanically. This
is the kind of regression the bot exists to prevent.

When the bot finds a violation, Hypothesis shrinks the input to the minimal failing
corridor and persists it, giving a reproducible counterexample that auto-replays on every
later run.

## 2. Architecture — Hybrid Generator

Two complementary layers, both operating on the **pure-numeric pipeline only** (verified:
`pass1`, `pass2`, `refinement`, `vmt`, `balancer` import with zero geo modules pulled, so
no geopandas/shapefiles are required and the tests run in lean CI).

### Spine: one end-to-end corridor generator
Builds a *coherent* synthetic corridor and drives the real pipeline end to end:
- N intersections (2–8) laid out west→east with monotonically increasing lat/lng.
- Corridor links following the given intersection order, with `mode ∈ {Full, Land Use, None}`.
- A synthetic base `NetworkLayer` and a horizon `NetworkLayer` (horizon = base with
  per-functional-class growth applied), both valid per the contract (unique `link_id`, etc.).
- Base TMCs (`{int_num: {movement: float}}`) over the 12 standard movements + 4 U-turns.

The generator runs the real `refinement → pass1 → pass2 → vmt` chain and asserts stage
invariants throughout. This catches cross-stage interaction bugs and exercises the
corridor-order invariant under permutation.

### Focused unit properties
For the pure numeric core where tight, fast properties live:
- `furness_intersection` — directly-generated 4×4 matrices + row/col targets; asserts IPF
  convergence and matrix stability.
- `balance_nchrp` — small generated corridors; asserts conservation, round-to-5,
  non-negativity.

These are fast and trivially shrinkable.

### File layout
```
backend/tests/forecasting/fuzz/
  generators.py          # Hypothesis @composite strategies: corridors, layers, TMCs, 4x4 matrices
  test_fuzz_balancer.py  # focused: furness_intersection + balance_nchrp properties
  test_fuzz_pipeline.py  # spine: end-to-end corridor, stage-by-stage invariants
  conftest.py            # Hypothesis profiles: "ci" (deterministic) vs "nightly" (deep)
  .hypothesis/           # per-developer example cache — GITIGNORED (see §4)
```

## 3. Invariants Asserted

Each invariant is tied to the code location that establishes it, so the assertion checks the
engine's own contract.

| # | Property | Code reference | Assertion |
|---|----------|---------------|-----------|
| 1 | Link conservation | `balancer.py:644` / `:1206` | every Full directed link: `upstream_outflow == downstream_inflow` (delta 0 post-round, within `tol`) |
| 2 | Non-negativity | `balancer.py:1093`, `refinement.py:109` | all movement volumes, VMT, refined futures ≥ 0 |
| 3 | Round-to-5 | `balance_nchrp(round_to_5=True)` | every balanced movement ≡ 0 (mod 5) |
| 4 | IPF convergence | `balancer.py:541` | on consistent margins, returns `converged=True` with `final_residual` finite & ≥ 0, and every cell finite & non-negative. (NOTE: convergence is *matrix stability*, NOT target satisfaction — `converged=True` does not imply `residual < tol`; see `test_pass1.test_in_out_imbalance_residual`. A residual<tol assertion would over-claim.) |
| 5 | U-turn passthrough | `pass1.py:116` | U-turn volumes identical seed → output |
| 6 | Corridor-order invariant | `balancer.py:103` + memory | links follow given intersection order under random permutation — never sorted by int number |
| 7 | Identity-growth conservation | `test_pass2.py:86` | horizon == base ⇒ refined futures ≈ base counts (within `tol`) |
| 8 | VMT scenario linearity | `vmt.py:208` | `scenario_vmt ≈ baseline_vmt × (1 − scenario_factor)` within `0.1` (two independent round-to-1-decimal steps → 0.05 + 0.05; bound holds for the single-segment VMT generator) |
| 9 | total_flow identity | commit `ab9b821` | `total_flow == Σ directional/period flows` |
| 10 | Daily-VMT all-or-none | `vmt.py:191` | daily VMT fields never partially populated across a corridor (all segments have a ratio, or none reported) |

**Deliberately excluded:** growth monotonicity (`future ≥ base`) is *not* asserted —
growth factors < 1 are valid model inputs, so it is not a sound invariant.

## 4. Shrinking, Reproducibility, Determinism

- **Hypothesis profiles** (`conftest.py`):
  - `ci` — `derandomize=True`, ~150 examples, `deadline` set. Fully deterministic, zero
    flakes in the PR gate.
  - `nightly` — ~5000 examples, randomized, `deadline=None`. Deep exploration.
- **Example-DB policy.** Hypothesis writes a per-developer `.hypothesis/` example cache;
  this is **gitignored**, not committed (a per-developer cache blob does not belong in git).
  When the nightly bot surfaces a counterexample, the regression is pinned explicitly with a
  committed `@example(...)` on the relevant property — an auditable, reviewable pin rather
  than an opaque cache artifact.
- **Float comparisons** use the engine's native `tol=0.5`, not exact equality, so assertions
  hold to the precision the engine itself targets.

## 5. CI Wiring

### Pre-existing gap being fixed
The forecasting pytest suite (`test_pass1`, `test_pass2`, `test_vmt`, `test_refinement`,
etc.) is **not run in CI today**. `backend/run_tests.sh` hardcodes a list
(`test_balancer_nchrp`, `test_excel_overrides`, `test_line_diagram_annotation`,
`test_line_diagram`, `test_e2e_bodger`) and invokes them as plain scripts, never via
pytest. As part of this work we fix that gap so the forecasting suite **and** the new fuzz
tests run in CI.

### Changes
1. Add `hypothesis` and `pytest` to `requirements.txt` (both pure Python, lean — verified
   no geo dependency pulled).
2. Update CI (`.github/workflows/ci.yml` → backend test job) to run the forecasting pytest
   suite, including `pytest backend/tests/forecasting/ -p ci`, as a **blocking gate**. The
   numeric pipeline imports without geopandas (verified), so no geo venv is needed in CI.
3. New `.github/workflows/fuzz-nightly.yml`: scheduled `cron` nightly, runs the `nightly`
   Hypothesis profile with a large example budget. **On failure the job fails loudly**
   (visible in the Actions tab) — **no auto-filed GitHub issues**.

## 6. Scope Boundaries (YAGNI)

**In scope:** the 10 invariants above, on the pure-numeric pipeline
(`balancer`, `pass1`, `pass2`, `refinement`, `vmt`); CI gate + nightly deep run; fixing the
forecasting-suite CI gap.

**Out of scope:**
- Geo ingest/matcher fuzzing (needs real shapefiles — deferred; tracked separately, and
  blocked on the known `Data/Sandag/<year>/` vs `data/sandag/` path mismatch).
- Malformed-input / validation fuzzing (different goal — this bot tests sound math on valid
  inputs).
- Performance / load fuzzing.
- Auto-filing GitHub issues from the nightly bot.

## 7. Open Risks

- **Generator validity bar.** If generators produce corridors the engine legitimately
  rejects (e.g. a degenerate single-leg intersection), tests could fail for the wrong
  reason. Mitigation: generators model the contract's structural constraints; use
  Hypothesis `assume()` to discard the rare invalid combination rather than asserting on it.
- **Nightly runtime.** 5000 examples through the full pipeline may be slow. Mitigation:
  tune the example budget to keep the nightly job under a reasonable wall-clock; the focused
  unit properties carry the bulk of the example count cheaply.
