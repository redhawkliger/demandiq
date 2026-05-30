# PRD-03 — Line diagram: link volumes + separate AM/PM figures

**Status:** ready to build
**Owner:** backend (+ thin S8 frontend consumption)
**Order:** 3 of 6 (no hard dependency; can run in parallel with PRD-02)
**Est:** ~½ day

## Why

`backend/line_diagram.py` renders per-intersection turning movements only. A colleague handed the Excel + diagram cannot tell whether `Int 1 → Int 2` conserved or by how many vehicles — the corridor flow story is missing entirely. Data-Viz flagged this as a hand-off gap, not a legibility one: the diagram is print-clean, it's just incomplete.

Per Q3 answer: emit two separate figures (one AM, one PM). Doubles page count, keeps each figure readable; the alternative (AM (PM) labels on one figure) crowds the segment text past legibility at 8.5×11.

## What (scope in / out)

**In:**
- Add link-volume labels on the corridor segments *between* intersections. Source: `lastRun.resolvedLinks` (the NCHRP-resolved target volumes that the balance solved toward).
- Each segment labeled `<from>→<to>: <volume> veh` in the corridor's primary direction (per `balancing.corridorDir`). One label per segment.
- Emit **two** figures per run: `line_diagram_am.png` and `line_diagram_pm.png`. Identical layout; AM and PM differ only in the per-segment + per-cell numbers.
- `/line-diagram` endpoint in `backend/app.py` returns both image bytes (or both paths if it currently returns a path).

**Out:**
- No new chartjunk (no arrows other than what the diagram already has, no color encoding of conservation status — that's deferred to v2 if it earns its slot).
- No interactive SVG / hover. PNG output for the deliverable, same as today.
- No change to figure size / DPI (`FIG_INCHES=4`, `DPI=150` stays — already print-clean at 8.5×11).
- No layout regression on the per-intersection turning-movement cells.

## How

- `backend/line_diagram.py` — accept `resolved_links` as input alongside the existing per-intersection movements. Render segment labels via matplotlib `ax.text()` at the midpoint of each corridor segment, sized to match existing cell labels.
- Add a `period: 'AM' | 'PM'` arg to the figure builder; existing call site loops over both periods and writes two files.
- `backend/app.py /line-diagram` endpoint — return `{ am: <bytes/path>, pm: <bytes/path> }` (was a single image).
- `frontend/src/sessions/S8_Export.jsx` — consume both; show both in the export preview; bundle both into the Excel/zip output.

## Acceptance criteria

- [ ] On the Bodger fixture, AM figure shows the resolved AM link volume between each adjacent intersection pair.
- [ ] PM figure shows the PM values — and they differ from AM where the data does.
- [ ] Labels are legible at 8.5×11 print (no overlap with cell numbers or each other).
- [ ] Existing per-intersection turning-movement rendering is byte-identical to before (no regression).
- [ ] `/line-diagram` endpoint returns both AM and PM in one response (one round-trip).
- [ ] S8 export deliverable includes both figures (filename convention: `<project>_line_diagram_am.png` / `_pm.png`).
- [ ] Backend test in `test_e2e_bodger.py` (or a new file) asserts the segment label count = `len(resolved_links)` per period.
- [ ] No new dependencies beyond what `line_diagram.py` already uses.

## Risks / open

- When `resolved_links` is empty (no corridor links configured), figures must render cleanly with no segment labels — not crash.
- Segment label position needs a sensible default when intersections are very close together on the figure; fall back to offsetting the label perpendicular to the corridor axis.
- S8 may need a small layout tweak to show two figures side-by-side or stacked in the preview (small, but call it out).
