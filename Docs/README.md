# Docs

## `demandiq_tour/`

Working artifacts from the F1–F8 v1 → v2 refinement cycle. Moved in-repo from
`/tmp/demandiq_tour/` so they survive a tmp wipe.

- **`kickoff_s1_s8.md`** — cross-functional product roundtable that produced
  the six-PRD v1 sequence.
- **`prd_0{1..6}_*.md`** — the six PRDs that defined PRD-01 through PRD-06 (in
  build order: mode-lookup unification → Excel 3-tab schema → line-diagram
  link volumes → S4 paste tolerance → coordinate QC flag → S1→S8 e2e test).
- **`design_review.md`** + **`captions.txt`** + **`S{1..8}_*.png`** —
  screen-by-screen QA tour at 1024 / 1440 / 1920 widths.
- **`v1_corridor_audit.md`** — what the Alpine Tavern Rd corridor exposed
  when piped through the F1–F8 fixes (F1 silent false-positive, F2
  geometry-cascade, F3 source outliers, F4 hero hierarchy, F5 drops severity,
  F6 line-diagram footnote, F7 raw-vs-resolved smoothing, F8 S8 veh label).
- **`v1_corridor.xlsx`** + **`v1_corridor_findings.json`** +
  **`v1_corridor_{s6,s7,s8,am,pm}.png`** — the deliverable + screenshots that
  back up the audit.

These are reference material, not source-of-truth. The implementation lives in
`backend/` and `frontend/src/`. Tests in `backend/test_*.py` and
`frontend/src/lib/*.test.mjs` + `frontend/tests/e2e/`.
