# PRD-04 — S4 bulk-paste tolerance + 1024 column fit

**Status:** ready to build
**Owner:** frontend
**Order:** 4 of 6 (independent; can run in parallel with PRD-02 / PRD-03)
**Est:** ~1 day

## Why

At N=10 intersections × 2 periods, S4 is a 5/5 friction screen. Two compounding problems:

1. **Strict parser** (`lib/bulkPaste` + `S4_VolumeEntry.jsx:432–565`): demands tab-separated rows with exact "Int#" / "Period" / movement-key headers. Real-world Excel paste from engineers comes with K-suffixes (`1.2K`), header variants (`Movement / Left / Through / Right`), mixed column orders, sometimes no header row at all. The parser rejects the entire batch on any mismatch; engineers fall back to modal-by-modal manual entry — 2–3 hours at N=10.
2. **1024 column clip** (`volumes.css:272`): sticky-left metadata = 220px + period column = 36px → 256px gone from a 1024-wide viewport. On a typical engineer laptop, the rightmost movement columns (SBR + PHF + HV%) clip off-screen with no horizontal-scroll affordance.

This blocks the deliverable upstream: every fix downstream is moot if engineers can't get the data in.

## What (scope in / out)

**In — parser tolerance:**
- Accept K-suffixes: `1.2K` → `1200`, `1.5k` → `1500`.
- Accept header variants: `Movement` / `Direction`, `Left` / `LT` / `L`, `Through` / `TH` / `T`, `Right` / `RT` / `R`; case-insensitive.
- Accept no-header paste (first row is data): detect when first row parses as numbers, treat it as data.
- Tolerate mixed column orders: if a header row IS present, map by header rather than position.
- On parse failure, show error with **the unparseable row index** and a one-line hint ("Header row not recognized — try pasting with column headers Movement / AM / PM").

**In — 1024 fit:**
- `volumes.css:272`: sticky-left `220px` → `180px`; period column `36px` → `30px`.
- Net: 256 → 210, +46px of column space at 1024px → all 12 movement columns visible without horizontal clip.

**Out:**
- No new bulk-paste UI affordance (file upload, drag-drop). Modal stays.
- No backend change.
- No new tests for the K-suffix parser beyond what's needed for `bulkPaste.test.mjs`.
- No general CSS token migration (PRD-defer item).

## How

- `frontend/src/lib/bulkPaste/` (or wherever it lives) — add normalization layer: strip header row if recognized, parse K-suffix, build a header→column map.
- `frontend/src/sessions/S4_VolumeEntry.jsx:432–565` — preserve the error-banner UX, improve the error string to include `row N: <reason>`.
- `frontend/src/styles/volumes.css:272` — width changes only.
- `frontend/src/components/VolumeGrid.jsx` — no logic change; just inherits new sticky widths.

## Acceptance criteria

- [ ] Paste `EBL\t1.2K\nEBT\t800` parses to `{ EBL: 1200, EBT: 800 }`.
- [ ] Paste with header `Movement\tAM\tPM\nEBL\t100\t150` parses correctly.
- [ ] Paste with header `Mvt\tLT\tTH\tRT` recognizes the column variants.
- [ ] Paste with no header (first row `EBL\t100`) parses by position.
- [ ] Paste with malformed row 7 of 12 shows error: "row 7: unparseable value 'x'" — and does NOT discard the other 11.
- [ ] At 1024px viewport, all 12 movement columns + PHF + HV% are visible without horizontal scroll on a 4-leg intersection.
- [ ] `frontend/src/lib/bulkPaste.test.mjs` adds cases for K-suffix, header variants, no-header, and partial-failure scenarios. All pass.
- [ ] Existing test cases still pass (no regression).
- [ ] Lint clean.

## Risks / open

- Column-width reduction may push the leftmost metadata column too tight on long intersection names. Spot-check Bodger intersection names ("Tavern @ Willow Glen" = 18 chars); truncate with ellipsis if needed (already an existing pattern in S6 conv list).
- "Through" vs "Thru" vs "T" — pick the canonical set; document inline.
- Partial-failure UX: surface the count "Imported 11 of 12 rows, 1 skipped" rather than nothing.
