# v1 Corridor Audit — Alpine Tavern Rd

**Date:** 2026-05-29
**Fixture:** 10 intersections, Tavern Rd NB/SB (Alpine, CA), constructed per kickoff Q4.
**Planted issues** (so we can tell whether the system catches what it should):
1. Int 4 ↔ Int 5 share `lat/lng = (32.8410, -116.7619)` — should fire **GEOMETRY-FALLBACK** (PRD-05).
2. Int 6 SBT raw = `12` (typo, intended `1200`) — should surface as a flagged drop or implausibly low value.
3. Int 7 is a T-intersection (no EB approach) — should pass through without manual intervention.
4. Int 9 NB outbound = 690 vs Int 8 NB inbound = 390 — internal inconsistency, should surface as a link-conservation gap or be reconciled away.

Artifacts (sibling files): `v1_corridor_s6.png`, `v1_corridor_s7.png`, `v1_corridor_s8.png`, `v1_corridor_am.png`, `v1_corridor_pm.png`, `v1_corridor.xlsx`, `v1_corridor_findings.json`. Script: `/tmp/alpine_corridor_run.mjs`.

---

## What worked

- **Excel deliverable is 3-tab (Provenance / Combined View / Raw Movements)** — PRD-02 live; the Provenance tab carries method, windows, tolerance, max iter, per-intersection convergence with iter / Y-N / residual, plus the qc_flags. The deliverable is self-describing.
- **Corridor line diagrams (AM + PM, separate)** — PRD-03 live; both PNGs land in S8 download bundle (`alpine-tavern-rd-corridor-v1-smoke_line_diagram_am.png`, `_pm.png`), each ~275 KB, print-clean at 8.5×11.
- **GEOMETRY-FALLBACK fired correctly** — `Directional fallback used at Int 4↔5 — verify leg orientation.` (PRD-05 live.)
- **NCHRP-LINK-DELTA messages are rich** — for each off-balance link: `Link 3→4 NB (Full): delta -10.0 veh post-reconciliation — upstream 685, downstream 675. Likely a raw-floor clipping issue on one of the leg's L/T/R cells.` Engineer-readable; tells them where to look.
- **T-intersection handled cleanly** — Int 7 has no EB approach. The algorithm rebalanced its NB/SB/WB flows; conservation deltas on 6↔7, 7↔8 are all 0.0.
- **Per-intersection IPF converges in 1–N iterations** with `final_residual` reported per intersection (just stored on `lastRun.config`).
- **PRD-04 bulk-paste tolerance + PRD-01 mode unification** both invisible in this run (no paste used; no S5 mode edits) but the underlying paths are tested by the e2e.
- **Drops surface in the banner** — "AM: 41 movements dropped below raw, largest -95 veh (Int 6 EBT)." Direct CTA to S7.

## What surfaced that needs attention (v2 findings, ordered by severity)

### F1 — Silent false-positive when the backend can't classify a link (CRITICAL)

**Discovered as a side effect.** My fixture initially had `direction: 'NB'` (cardinal) on each link. The store accepted it. The S6 frontend serialised and POSTed it. The backend (`balancer.py:360`) checks `axis == 'EB/WB' or 'NB/SB'` and silently skipped every link. The response came back with `resolved_links: []`, `link_conservation: []`, `qc_flags: []`. **S6's hero strip displayed `"0/0 links conserve ✓ · AM 10/10 · PM 10/10 converged"` in GREEN** — a confident "all clean" verdict on a 9-link corridor where the algorithm never engaged corridor balancing.

A user wouldn't ordinarily produce this — S2's `suggestDirection` always assigns the axis form. But programmatic import / a stale localStorage / a future S2 change / a copy-paste from a JSON export could. The system should fail loud.

**Fix candidates:**
- **Backend (cheap, ½ day):** reject unrecognised direction values in `/balance-nchrp` with HTTP 400 — `{detail: "link {fromNum}→{toNum} has unknown direction 'NB' — expected 'EB/WB' or 'NB/SB'"}`. Or emit a `LINK-DROPPED` qc_flag.
- **Frontend hero gate (cheap, ¼ day):** if `links.length > 0 && resolvedLinks.length === 0`, the hero must NOT paint green — show amber `"Link resolution skipped — verify corridor direction"`. Same dimension as the "config changed since this run" warning.
- **Both** is the right answer; the backend rejection is the durable fix, the hero gate is the defense-in-depth.

### F2 — One geometry collision cascades into 8 NCHRP-LINK-DELTA flags

The planted Int 4↔5 coordinate collision was the *root* of 8 of the 9 qc_flags. The engineer reads a list of 9 issues, but 8 are downstream symptoms of one root cause. The flags read independently — no causal link surfaced.

**Fix:** when GEOMETRY-FALLBACK fires at Int N↔M, the NCHRP-LINK-DELTA flags on links touching N or M should reference it: `Link 3→4 NB (Full): delta -10.0 veh — likely caused by GEOMETRY-FALLBACK at Int 4↔5 (resolve coords first).` Small string-concat in `balancer.py` where qc_flags are appended.

### F3 — Implausible source values produce no flag (Int 6 SBT = 12)

The SBT typo got swallowed by Furness — the value rose during balancing to fit the link totals, but no warning ever told the engineer the raw was 100× too small. The Raw Movements tab in the Excel shows the absurd raw → balanced delta, but only if the engineer specifically scans it.

**Fix:** source-data sanity QC. For each leg total, check if it's > 3σ outside the corridor mean for that leg/direction. Emit `SOURCE-OUTLIER` qc_flag: `"Int 6 SB approach total = 58 veh; corridor median = 415 veh — verify count."` Adds a new check class to `balancer.py`. Half day.

### F4 — Hero conflates "intersection converged" with "links balanced"

Hero strip reads `"1/9 links conserve · 8 off · AM 10/10 · PM 10/10 converged"`. The "AM 10/10 converged" pulls the eye to "passed" while the "1/9 links" is the real story. Per-intersection IPF convergence is a matrix-stability statement about each intersection independently; corridor-link conservation is the real correctness signal (Backend made this point at the kickoff).

**Fix:** demote the "X/Y converged" line; promote conservation. Hero v2 layout:
```
8/9 link inconsistencies · largest 25 veh
Method: Larger · Tolerance: 0.50 veh · Run 5m ago
(quiet underline) AM 10/10 PM 10/10 intersections IPF-stable
```
The headline becomes the thing an engineer's eye must land on. Quarter day.

### F5 — Drops banner shows count but no severity bucketing

"AM: 41 movements dropped below raw, largest -95 veh (Int 6 EBT)" — but 41 drops include lots of small ones. The 5 largest (-95, -90, -60, -45, -40) are real concerns; the others are typically <5 veh and routine NCHRP-Larger behavior.

**Fix:** banner v2: `"AM: 5 drops > 40 veh (Int 4–6), 36 smaller. Largest -95 (Int 6 EBT)."` Two-bucket summary makes severity unmissable.

### F6 — Line diagram drops 3 of 9 segment labels at row wraps

The 3-wide grid renders segments only between same-row adjacent intersections. For 10 intersections, the row boundaries (3↔4, 6↔7, 9↔10) lose their labels. The colleague reading the AM figure sees 5 segments labelled and 4 spans without numbers. The corridor flow story is partial.

**Fix candidates** (per the PRD-03 agent's own open question):
- (a) Single horizontal strip layout (figure width grows with N) — readable but no longer fits 8.5×11 for >5 ints
- (b) Keep the grid but emit a separate "corridor spine" mini-figure showing all 9 segments — second page per period
- (c) Render unlabeled-but-visible arrows at row wraps + a footnote pointing to the conservation table

I'd lean (b) — small additional asset, full information.

### F7 — Reconciled inconsistencies silently disappear (Int 8↔9)

I planted a 300 veh inconsistency between Int 8 NB outbound and Int 9 NB inbound. The link conservation table shows `8→9 NB: out=630 in=630 delta=0.0 mode=Full`. The algorithm reconciled both ends to the same value (probably the Larger of the two). The engineer never sees that the raw counts disagreed by 300 veh — only the smoothed result.

**Fix:** add a "raw → balanced reconciliation" column to Resolved Link Targets. For each link: `Int 8 raw NB out = 480, Int 9 raw NB in = 780, resolved = 780, Δ = +300 (Larger picked Int 9 side)`. Currently invisible. The deliverable hides the smoothing. Half day on the backend (response shape) + ½ day on S6 + the Excel Provenance tab.

### F8 — S8 "Convergence" stat in the Ready to Export panel labels veh as "%"

S8 export landing shows `Convergence: AM 10/10 · PM 10/10 (50% threshold)`. The threshold is `0.5 veh`, not `50%`. S8 is multiplying `convergenceThreshold` by 100 and appending `%`. A pre-existing display bug (predates PRDs 01–06). Quarter day, single-line fix in `S8_Export.jsx`.

---

## v1 verdict

**The deliverable ships honestly when the input is well-formed.** A colleague opening `v1_corridor.xlsx` + the two line diagrams can:
- Verify which intersections converged (Provenance tab)
- See which links have conservation issues, by how much, and the algorithm's hint (qc_flags)
- Audit every (int × movement) raw → balanced delta (Raw Movements tab)
- Read the run's method, windows, tolerance, max iter, timestamp

That was the kickoff bar. PRDs 01–06 hit it.

**The honest-output assumption is fragile.** F1 in particular — silent failure when the backend can't classify input — would have shipped the wrong story to a stakeholder. It surfaced only because I fed a fixture the user-facing UI couldn't have produced. The v2 list above is the queue, F1 → F8 by impact on hand-off correctness.

## Next step

Run another corridor — ideally a *real* WSP corridor with real data quality — and see what F1–F8 don't catch. The kickoff's premise stands: real data tells us what v2 actually needs, not theory.
