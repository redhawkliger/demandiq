# Lessons (append-only)

Written by the Mechanic (Phase 2) as failures get diagnosed and fixed.
Format per entry: symptom → root cause → fix → proof seeds (the seeds that
reproduced it, re-run green after the fix).

## Orientation-variant ±5 swap in leg reconciliation (`adef03a02cb7`)

- **Symptom.** probe-orientation-sweep: the same corridor run N–S vs E–W
  flips a single ±5 rounding quantum between two movements sharing an
  **exit leg** (seed 4: AM int 1 NBR/SBL swap 120/125). Accuracy metrics
  healthy; only the sweep probe red. 1,060 recorded hits, one signature.
- **Root cause.** `_adjust_leg_to_target` (balancer.py, Stage 4c.3
  post-round reconciliation) decrement branch sorted candidate cells by
  `(value, movement-code string)` and broke value ties by the string.
  Compass-labeled codes relabel under 90° corridor rotation, so the same
  physical tie selects different physical cells per orientation: EW frame
  ties SBL/NBR at 125 → `'S' > 'N'` picks SBL; NS frame labels the same
  cells EBL/WBR → `'W' > 'E'` picks WBR — the other physical cell. Ties
  can only diverge on outflow legs (three different compass prefixes per
  tier: e.g. EBT/SBL/NBR), which is why the symptom is always two
  movements sharing an exit leg; approach-leg tiers share one prefix, so
  their string order happens to survive rotation.
  The initial hypothesis — float accumulation order in IPF/normalization —
  was **falsified**: Level-1 leg targets and pre-round IPF matrices are
  bit-identical across orientations. Alphabetical sorting of compass-
  labeled movement keys is the anti-pattern here, not the cure: canonical
  order must be frame-relative (leg-local L/T/R spec-list position), never
  the compass code string.
- **Fix.** `fdcd29e` — break decrement value-ties by tier position (the
  leg-relative L/T/R spec order, which maps 1:1 under rotation), mirroring
  the increment branch's `max()` semantics. No NCHRP methodology change.
- **Proof seeds.** 4, 5, 9 (FAIL → PASS, worst GEH unchanged); 100-seed
  batch with zero `adef03a02cb7` hits; controls 1, 2, 3, 10, 11, 12
  verdict-identical; 50 identical POSTs byte-identical; backend suite
  green (seed 94's MARGINAL accuracy-drift `f1bf8e87b69d` pre-dates the
  fix and is unrelated).
