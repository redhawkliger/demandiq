# PRD-05 — Coordinate-degeneracy QC flag

**Status:** ready to build
**Owner:** backend
**Order:** 5 of 6 (independent; can run in parallel with PRD-02 / PRD-03 / PRD-04)
**Est:** ~½ day

## Why

`backend/balancer.py:315–369` (`resolve_link_volumes`) determines leg orientation from each intersection's lat/lng. When two adjacent intersections share the *same* lat/lng (overlapping micro-locations, common in tight urban grids), the geometry calculation can't disambiguate the corridor direction — and the code silently falls back to `a < b` intersection-number ordering. Lines 345–347 and 359–361 take that path with no log, no warning, no qc_flag.

**Consequence:** the EB-labeled link in the UI may be interpreted as WB internally. The user sees phantom `NCHRP-LINK-DELTA` residuals (lines 1245–1256) that look like data-quality issues but are actually geometry bugs. The engineer cannot debug it because nothing in the run output says "we fell back."

Half a day buys honesty: surface the fallback as a named QC flag and S6 already renders it (`S6_RunAnalysis.jsx` QcFlagsSection).

## What (scope in / out)

**In:**
- In `resolve_link_volumes`, detect when the lat/lng disambiguation can't resolve a link's orientation and the int-number fallback fires.
- Append a qc_flag: `{ check: 'GEOMETRY-FALLBACK', period: null, message: 'Directional fallback used at Int <N>↔<M> — verify leg orientation.' }`.
- Flag is per-link-pair; do not duplicate if both AM and PM hit the same link.
- Flow through `app.py /balance-nchrp` into the existing `qc_flags[]` array.

**Out:**
- No UI change — S6 QcFlagsSection already renders qc_flags by `check`.
- No styling distinction for GEOMETRY-FALLBACK (uses the default amber chip; FRACTIONAL-VOLUME has its own variant — GEOMETRY-FALLBACK doesn't earn one yet).
- No auto-resolution (we don't try to fix the geometry; we report it).

## How

- `backend/balancer.py:315–369` — add a return-channel for fallback detection. Either:
  - (a) `resolve_link_volumes` returns an additional list of fallback events, OR
  - (b) accumulate fallback events into a passed-in `qc_flags` list (preferred — matches the existing pattern in lines 1245–1256).
- `backend/app.py` around the `/balance-nchrp` response builder — no change needed if (b); the flag just appears in `qc_all` via the existing path.

## Acceptance criteria

- [ ] Bodger fixture: zero GEOMETRY-FALLBACK flags emitted (Bodger coords are distinct).
- [ ] Constructed fixture with two intersections at identical lat/lng + a link between them: exactly one GEOMETRY-FALLBACK flag emitted, message names both intersection numbers.
- [ ] Three intersections, two share coords: flag emitted once per affected link, not per intersection.
- [ ] Same coord-sharing fixture with both AM and PM data: flag still appears exactly once (deduped across periods).
- [ ] New test in `backend/test_balancer_nchrp.py` covering both the no-fallback and fallback paths.
- [ ] S6 renders the flag via existing QcFlagsSection on the constructed-fixture run (manual visual check is fine).
- [ ] No regression on existing test_balancer_nchrp.py + test_e2e_bodger.py.

## Risks / open

- Coordinate equality threshold: exact `==` is brittle; use a small epsilon (e.g. `1e-6` degrees ≈ 11 cm) so that floating-point drift in stored coords doesn't suppress the flag. Make the epsilon a named constant.
- If the same link triggers fallback AND a downstream LINK-DELTA residual, the engineer should see both flags — don't suppress LINK-DELTA when GEOMETRY-FALLBACK fires (it's informational, not a substitute).
