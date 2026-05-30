# PRD-02 — Excel export: NCHRP-era fields + 3-tab schema

**Status:** ready to build
**Owner:** backend (+ thin frontend S8 update)
**Order:** 2 of 6 (depends on PRD-01 only via the mode-lookup helper that excel_export.py also calls)
**Est:** ~1 day

## Why

`backend/excel_export.py:99` reads `lastRun['convergence']` — a field that **does not exist** in the NCHRP-era `lastRun` shape. The deliverable silently emits stale or empty values for the most important question a colleague will ask: *did this corridor converge?* Three roles at the kickoff flagged the export as the single biggest hand-off gap: a colleague reading the Excel cannot verify which intersections converged, what method was used, or whether the run is auditable. Today they'd have to open DemandIQ.

## What (scope in / out)

**In — 3 tabs:**

1. **Provenance** *(new)* — auditable run header + per-intersection convergence detail. Columns / rows:
   - Header block: project name, run timestamp, method (`larger` / `average`), AM window, PM window, tolerance (veh), max iterations, direction.
   - Per-intersection table: `Int # | Name | AM iter | AM converged Y/N | AM final residual | PM iter | PM converged Y/N | PM final residual`.
   - QC flags table: `check | period | message` (mirrors S6 QC section, including the new GEOMETRY-FALLBACK from PRD-05).
2. **Combined View** *(existing — preserve)* — current combined-table output, no regression. Same shape, same formulas, same column order.
3. **Raw Movements** *(new)* — audit-grade table: one row per `(int_num, movement)`, columns `Int # | Movement | AM raw | AM balanced | AM delta | AM override | PM raw | PM balanced | PM delta | PM override`. Drops (delta < 0) shaded amber.

**Out:**
- No per-intersection tabs (Q2 answer).
- No new chart embeds in the workbook (the line diagrams are separate deliverable files per PRD-03).
- No change to filename convention.

## How

- `backend/excel_export.py:98–137` — rewrite the data-pull. Read `lastRun.config` (method, windows, tolerance, maxIterations — added by the S6 redesign), `lastRun.intConverged`, `lastRun.iterations`, `lastRun.finalResidual`, `lastRun.qcFlags`.
- `backend/excel_export.py:529` — second `lastRun` read site; same pivot.
- Drop all references to the legacy `lastRun['convergence']` field. Remove dead code paths.
- Tab order: Provenance → Combined View → Raw Movements (Provenance is the first thing a colleague sees on open).
- Use the existing openpyxl style helpers; do not introduce new dependencies.

## Acceptance criteria

- [ ] Workbook opens in Excel and Google Sheets without warning.
- [ ] Tab order matches spec (Provenance first).
- [ ] Provenance header block populates from `lastRun.config` (no hardcoded values).
- [ ] Per-intersection convergence table has one row per intersection × period column-pair, with iter / Y-N / final residual all populated from `lastRun.iterations`, `intConverged`, `finalResidual`.
- [ ] Combined View tab byte-identical to current export on the Bodger fixture (regression check).
- [ ] Raw Movements tab has 12 movement rows per intersection (no U-turns), drops visually flagged.
- [ ] QC flags table renders even when empty (one "All clean" row).
- [ ] `backend/test_excel_overrides.py` still passes; one new test asserting the Provenance tab structure.
- [ ] No reference to `lastRun['convergence']` remains in `excel_export.py`.

## Risks / open

- If a legacy persisted project in localStorage still has `lastRun['convergence']` and no `lastRun.config`, the export must degrade gracefully (emit "—" for missing fields, not crash). Treat missing config as an "old run" indicator.
- The Raw Movements tab is the new audit surface — make sure column widths are wide enough that nothing truncates on print.
