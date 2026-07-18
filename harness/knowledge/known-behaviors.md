# Known correct-but-surprising NCHRP behaviors

Seeded at Examiner build time from the repo's ADRs, docstrings, and specs, so
no future agent (Mechanic included) "fixes" behavior that is correct by
design. Each entry cites its source in the codebase.

## Balanced values can drop below raw counts

Under both `larger` and `average` link resolution, IPF column-scaling can
shrink cells that row-scaling raised — individual balanced movements below
their raw counts are **the mathematical truth, not a bug**
(`balancer.py` `balance_nchrp` docstring: "this is the mathematical truth").
The S6 UI says the same ("Under Average, individual movements can drop below
raw counts (expected NCHRP behavior)"), and S7 Review Drops exists precisely
to surface them for engineer review. A drop is only gradeable via GEH vs the
answer key, never as a hard invariant.

## The Stage-4 "floor" step was removed on purpose

Step C (clamp balanced ≥ raw) was removed in Stage 4b because it defeats
Furness convergence and creates phantom link-conservation violations
(`balance_nchrp` history notes). Do not reintroduce it.

## Round-up-to-5 with raw-0 passthrough

Every balanced movement is rounded UP to the next multiple of 5
(`_round_up_5_nchrp`); a movement whose raw count is 0 stays 0. So a balanced
value of 1–4 veh is impossible in correct output — that's the Grader's
floor-violation check — and balanced totals are always multiples of 5.

## The inner IPF tolerance is hardcoded to 0.01 veh

`balance_nchrp` calls `furness_intersection(..., tol=0.01,
max_iter=max(max_iter, 2000))` regardless of the payload's `tolerance`
(`balancer.py:1159-1162`, "Use 0.01 veh tolerance — far tighter than the
default"). The S5 setting and payload `tolerance` do not control Level-2 IPF
convergence. Reported `converged` refers to matrix stability at 0.01 veh.

## `final_residual` is pre-rounding and target-relative

`final_residual` = max |leg sum − Level-1 target| on the **pre-round IPF
matrix** (ADR 0001; `furness_intersection` docstring). The Level-1 targets
are not part of the API response, so the residual cannot be recomputed from
returned volumes alone — the telemetry-truthfulness probe instead recomputes
`link_conservation` and `movements_review`, which are exact functions of the
response. Per ADR 0001, in=out totals at one intersection are a tautology
(always equal); never grade that.

## `converged` is matrix stability, not in=out balance

`intConverged` means max inter-iteration cell delta < tol (ADR 0001,
`balancer.py:557-565`) — an intersection can converge while a residual to its
targets remains (structural infeasibility on thin matrices leaves a few veh).

## Post-round link reconciliation targets round5(avg) exactly

For Full links, both endpoints' leg L+T+R sums are forced to the canonical
link volume = round-up-5 of the average of the two pre-round leg sums
(Stage 4c.3). Post-round conservation should hold exactly; the tool itself
flags residual deltas > 0.5 veh as `NCHRP-LINK-DELTA` and uses a 10-veh
post-round tolerance constant for the rare raw-floor clipping case.

## U-turns pass through unchanged

U-turns are not in the 4×4 matrix; they pass through IPF unchanged and are
excluded from `movements_review` and from `intConverged`/`finalResidual`
(ADR 0001). They ARE counted inside a leg's outflow total for conservation
(`DIRECTION_SPEC[dir]['outflow_u']`).

## Movements with raw = 0 are skipped in movements_review

`compute_movements_review` drops rows where raw ≤ 0 ("no engineering meaning
at a missing-leg cell"). An absent row there is not missing telemetry.

## Orientation sweep: one-quantum (±5 veh) swaps are an OPEN finding, not blessed

First soak (2026-07-10, seeds 2–11) showed ~30% of seeds FAIL the
orientation sweep with a single ±5 veh swap between two movements sharing an
exit leg (e.g. EW `EBR=120/WBL=125` vs the NS rotation's mapped
`125/120`). Link conservation and GEH still pass in both orientations.
Likely mechanism: IPF row/col scaling order differs between orientations
(corridor legs occupy different matrix indices), leaving float differences
~tol that flip a cell across a round-up-to-5 boundary; reconciliation then
compensates in the paired cell. This is a real orientation-sensitivity of the
tool, tracked as an open ledger signature — it is NOT known-correct behavior,
but a future Mechanic should expect the root cause at the rounding boundary,
not in the movement mapping.

## Forger corpus firewall — synthetic sheets must NEVER train the extractor

Every Forger-generated PDF (`harness/forger/`) carries
`forger-synthetic=true` in its PDF metadata (Subject and Keywords). The
rule: **Forger sheets must never enter any extraction fine-tuning or
reference-example corpus** (`backend/training_data.jsonl`, the labeling
pipeline in `backend/tools/populate_labels.py`, or any future corpus) — a
model must not be trained on its own exam, or every Forger verdict
afterwards measures memorization instead of extraction. Anyone bulk-adding
PDFs to a corpus must check the metadata marker first. The Forger's runs/
and failures/ artifact dirs are gitignored, which also keeps synthetic
sheets from being casually harvested.

## Empty-period payloads crash the endpoint (pre-existing defect, not harness scope)

`/balance-nchrp` 500s (KeyError in `balance_leg_totals`) when a period has
links but an empty `unbalanced_volumes` dict for the linked intersections —
reachable from the UI with an AM-only project. The Examiner sidesteps it by
always generating both periods; documented in the Examiner PR as an observed
defect. If a future puzzle class goes single-period, expect `pipeline-crash`
verdicts that are the tool's bug, not the harness's.
