# Diagnosis: corridor-through inflation — one mechanism across all open accuracy-drift signatures

**Date:** 2026-07-14 · **Scope:** diagnosis only, no code changes.
**Method:** read-only extraction from case-file / run artifacts (`puzzle.json`,
`answer_key.json`, `tool_output.json`, `grade.json`). Every number below comes
from those artifacts; nothing was re-run or modified. Reference worked
example: `failures/20260713-120511-seed34093/` (signature `43e3470d5cfe`).

## The mechanism (as diagnosed in 43e3470d5cfe)

At every chain intersection, the corridor through movement (EBT/WBT on EW,
NBT/SBT on NS) is **the only cell shared by both adjacent corridor-link
constraints** — it sits in the upstream link's approach set *and* the
downstream link's outflow set. The corner movements each belong to only one
constraint and normally absorb reconciliation deltas (Stage 4c.3 prefers
non-shared cells). A T-intersection removes one corner from **each**
constraint (the movements referencing the absent leg), halving the absorption
capacity on both sides. When adjacent raw counts disagree, `larger`
resolution sets each link target to the bigger side; the accumulated
disagreement that the lone surviving corners cannot absorb lands on the
shared through — which, being low-volume (key 50–255 in every observed
case), takes a catastrophic relative hit while post-round link conservation
still closes **exactly** (delta 0.0), so no QC surface ever fires.

## Per-signature findings (all open accuracy-drift signatures)

All four cases: **(a)** worst movement is a corridor-axis through ✓ ·
**(b)** the failing intersection is itself a T (and has T neighbors) ✓ ·
**(c)** the through is the sole cell shared by both adjacent link
constraints, and each constraint has exactly **one** surviving corner ✓ ·
**(d)** inflation is upward under `larger` ✓ · **(e)** zero
balancing/reconciliation QC flags fired ✓ (details below).

| Signature | Case | Tier / corridor | Worst movement | key → raw → tool | GEH | Failing int legs | Surviving corners (appr / outf) | Adjacent links (resolved vol · reconciliation_delta) |
|---|---|---|---|---|---|---|---|---|
| `43e3470d5cfe` | seed 34093, `20260713-120511` | D · EW, n=20 | PM int 7 **WBT** | 60 → 50 → **210** | 12.91 | E,N,W (T, no S) | WBR / SBR | 8→7 WB: 971 · Δ241; 7→6 WB: 781 · Δ173 |
| `0ef7c180de21` | seed 13594, `20260712-165044` | D · EW, n=10 | PM int 8 **EBT** | 70 → 80 → **195** | 10.86 | E,S,W (T, no N) | EBR / NBR | 7→8 EB: 951 · Δ188; 8→9 EB: 720 · Δ142 |
| `e791ef99a454` | seed 15327, `20260712-181756` | D · NS, n=14 | PM int 9 **NBT** | 95 → 105 → **235** | 10.90 | N,S,W (T, no E) | NBL / EBL | 8→9 NB: 902 · Δ194; 9→10 NB: 895 · Δ121 |
| `146f86e36b93` | seed 15711, `20260712-183821` | D · NS, n=13 | AM int 11 **SBT** | 75 → 85 → **215** | 11.63 | E,N,S (T, no W) | SBL / WBL | 12→11 SB: 1004 · Δ151; 11→10 SB: 961 · Δ208 |

Secondary GEH>5 rows in the same cases are the **same shape**: the opposite
through at the same T (34093: PM int 7 EBT 50→130; 13594: PM int 8 WBT
255→350) or another corridor through at another T on the same chain (15711:
PM int 8 NBT 215→310, int 8 is a T missing E; AM int 11 NBT 180→265).

**(e) in full:** no `NCHRP-LINK-DELTA`, `NCHRP-LINK-INFEASIBLE`,
`NCHRP-LINK-NOLEG`, `NCHRP-CONV`, or phantom flag fired in any of the four
runs. The only flags anywhere are `SOURCE-OUTLIER` raw-input notices at
unrelated intersections (34093: ints 12/16/18; 15327: int 11; 15711: ints
6/9/10). One incidental exception: 13594 has a `SOURCE-OUTLIER` on int 8's
**WB approach** raw total — it names the failing intersection but is a
raw-count statistical notice, unrelated to and not gating the EBT inflation.
Post-round link conservation on every failing link is exactly **0.0** in all
four cases (verified from `link_conservation`) — the inflation is invisible
to the conservation check *by construction*, because reconciliation is what
produces it.

**Why four signatures for one bug:** `compute_signature` hashes the set of
movement codes with GEH>10. The same mechanism hits EBT at one seed, NBT at
another, {SBT, plus nothing else} at a third → distinct hashes. This is the
signature scheme working as designed (movement-set shape), but for this bug
class it splinters one mechanism into per-through-code ledger rows.

## MARGINAL sample tally

Seeded sample (`random.Random(20260714)`) of MARGINAL accuracy-drift runs
with surviving artifacts. Eligible pool: 4,421 (tiers B/C/D) + 253 (tier A).

**Tiers B/C/D, n=20:** **18/20 fit the full fingerprint**
(through + T-context + upward). Component counts: worst movement is a
corridor-axis through **20/20**; inflated upward **20/20**; at or adjacent to
a T **18/20**. Fits span tiers C and D, both periods, both orientations;
through keys 50–255, inflation +50…+150 — the FAIL cases' shape at lower
magnitude.

The **2 misfits** are the same mechanism minus the T amplifier:

| Run | Tier | Worst movement | key → raw → tool | T-context | Corners alive |
|---|---|---|---|---|---|
| `20260712-051931-seed2756` | D | PM int 10 WBT | 230 → 240 → 315 | none (int 10 + neighbors 4-leg) | 2 / 2 |
| `20260712-121456-seed7713` | B | PM int 15 NBT | 135 → 124 → 210 | none possible (Tier B is all 4-leg) | 2 / 2 |

Both are still corridor throughs inflated upward, deep in long chains
(int 10 of 20, int 15 of ~20) where link disagreement accumulates — but with
both corners alive in each constraint, the through takes a smaller share and
the drift stays MARGINAL (GEH ~5–6) instead of FAIL. Tier B existing means
the core concentration effect does not require a T; the T removes half the
absorption capacity and pushes the same effect over the FAIL threshold.

**Tier A control, n=8: 0/8 fit.** Only 2/8 even land on a through; 2/8 drift
*downward*; none have any T-context (Tier A has no T-intersections). Tier A
MARGINAL drift scatters across corner movements (WBL, NBR, SBR, EBL…) — the
concentration onto low-volume throughs is specific to the long-chain/T tiers,
exactly as the mechanism predicts.

## Verdict

**One mechanism.** All three remaining open accuracy-drift signatures
(`0ef7c180de21`, `e791ef99a454`, `146f86e36b93`) are the identical
T-through inflation diagnosed in `43e3470d5cfe`, differing only in which
through code crossed GEH 10 (and hence the signature hash). 18/20 of the
sampled B/C/D MARGINALs are the same fingerprint at sub-FAIL magnitude; the
2 exceptions are the same through-concentration without a T (both corners
alive → more absorption → MARGINAL only), including one on Tier B where T's
cannot exist. The Tier A control (0/8) confirms the effect is driven by
accumulated link disagreement concentrating on the sole shared cell, with
T-intersections as the amplifier that turns MARGINAL into FAIL.

Severity scaling observed: `GEH ∝` accumulated adjacent-link
`reconciliation_delta` landing on a low-volume through; every FAIL case had
Δ ≥ 121 veh on both adjacent links and a through key ≤ 255.

**For a future Mechanic (observations, not fixes):** the defect lives in
where Stage 4c.3 reconciliation *sends* accumulated link disagreement, not in
IPF and not in the resolution method itself; no current QC flag can see it
because post-round conservation closes exactly. Any fix proposal must
preserve the [[corridor-order-invariant]] and re-verify orientation
invariance (see `lessons.md`, `adef03a02cb7`).
