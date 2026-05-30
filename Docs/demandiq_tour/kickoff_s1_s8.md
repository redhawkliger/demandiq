# Kickoff — DemandIQ S1–S8 v1 refine, before real-corridor validation

**Date:** 2026-05-29
**Question on the table:** "What's the v1 refine across S1–S8 that gets DemandIQ to the line where Akshaey can run a real WSP corridor (10+ intersections, 50+ drops, mixed data quality) end-to-end and hand the output to a colleague? What's explicitly NOT worth touching first?"

---

## Transcript

### PM
- **Headline:** Unlock end-to-end on a 10+ intersection corridor by fixing the *deliverable* and one entry-side gate. Don't touch polish until a real corridor has run.
- **Riskiest assumption:** "The output is sufficient for a colleague to read without DemandIQ open." Today it isn't. Cheapest test: ship the export with full provenance + run a real corridor through it.
- **Fix before real-corridor:**
  1. **S6↔S8 convergence reporting mismatch** (design_review.md:156–158). S6 reports per-intersection, S8 reports per-period. Two contradictory answers on the same run is unshippable in a deliverable.
  2. **S4 1024 column clip** (design_review.md:104–105). Engineers paste corridor volumes on laptops; if rightmost columns hide, entry fails at N=10+.
  3. **S8 export must restate method + windows** (design_review.md:210). A colleague reading the Excel has no way to see "Larger vs Average" or AM/PM windows.
- **Defer:** S1 period control rework; S2 basemap; S7 period toggle; 1440/1920 spacing polish. None block the hand-off.

### Product Designer
- **Per-session friction (1=effortless, 5=user gives up):** S1:1 · S2:2 · S3:3 · **S4:5** · S5:2 · S6:2 · **S7:4** · S8:1
- **Two worst friction points that BLOCK a real corridor:**
  1. **S4_VolumeEntry.jsx:432–565 + lib/bulkPaste** — bulk paste modal demands tab-separated rows with exact "Int#"/"Period" headers. Engineers copy from Excel with K-suffixes ("1.2K"), header variants ("Movement Left/Straight/Right"), mixed column orders. Strict parser rejects whole batches; modal-by-modal fallback turns N=10 × 2 periods into 2–3 hours. **JTBD failure: "one Excel file in, plumbed in 10 minutes, not 10 times."**
  2. **S7_ReviewDrops.jsx:87–111 + :476–495 + :614 (OverrideInput)** — 10 ints × 12 movements ≈ 120 rows flat with no grouping/pagination/lazy load. Worse: `OverrideInput` triggers `setDraft` on every keystroke, re-running `buildMergedRows` over every row → jank at scale. "Show drops only" toggle helps but doesn't fix the recompute storm.
- **Annoying but not blocking:** S3_ApproachConfig.jsx:50–118 — defaults silently re-fill on return; no "saved" indicator. Confusing, not a stopper.
- **Disagreement:** S6 hero "warn" tier (analysis.jsx:306–309) reads as "re-run me" but under Larger mode drops are *expected NCHRP behavior*. Add one line to the hero: "Movements can drop below raw — review in S7 if needed." Otherwise engineers will keep re-running thinking something's wrong.

### Web Designer
- **Token drift:** Hex hardcoding everywhere — `map.css:131,141`, `volumes.css:141` use literal `#0A84FF` instead of `var(--accent)`; analysis.css:202–204, 273 mix `#FFFFFF`/`#fff`. Add semantic `--ok / --warn / --fail` tokens, then audit. **Cleans up half the cross-session inconsistency in one pass.**
- **Spacing/hierarchy:** S6 run button (analysis.css:111–114) is 48px tall and dominates; S5 uses 38px, S1 uses 44px. Pick one (44px). Standardize 20px horizontal padding.
- **Primary-action audit:** S5 balancing rules card (balancing.css:234–242) competes with the sticky right panel; the Save CTA gets lost.
- **Sidebar progress:** **Don't add.** Cost is opacity bloat. Instead: 2px dot/underline on active step + router-level lock on unreachable steps. The sidebar is the affordance; the lock is the signal.
- **Disagreement:** Volume grid (volumes.css:272) — `220px` sticky-left + `36px` period column = 256px gone of 1024. Reduce sticky-left to 180px and period to 30px; otherwise S4 *will* clip on engineer laptops.

### Data-Viz
- **Data-presentation failure that affects hand-off:** S6 `LinkConservationTable` (S6:817–881) lacks units in headers. A colleague reading "18 (16)" can't tell veh / PCE / ratio. Fix: add `(veh)` to column headers or a table caption.
- **Viz that breaks at scale:** S7 drops table (S7:476–495) — 7 columns × 100+ rows at 1024 width clips the Override column off-screen. Sticky Int/Movement column + horizontal scroll, or compress to "drops only" by default.
- **Line diagram verdict:** `line_diagram.py` is print-clean for 4×4 in (FIG_INCHES=4, DPI=150) and scales to 8.5×11 fine. **BUT** — it renders per-intersection turning movements only, **not the link volumes between intersections**. A colleague with the Excel + diagram cannot tell whether `Int1→Int2` conserved or by how much. That's a **hand-off gap**, not a legibility gap.
- **Disagreement with PM:** S6 reporting isn't the highest data-viz risk — S8's export summary (S8:164–176) omits *all* per-intersection convergence detail. The colleague sees "Convergence 2/2" with no recourse. Export S6's per-intersection convergence list as a tab in the Excel.

### Architect (Ousterhout — push back on creep)
- **Headline:** Codebase is **not** structurally ready. S6 is now 881 lines after the redesign; mode lookup is duplicated; one piece of stored data is now dead.
- **Asymmetry / future bug:** `S7_ReviewDrops.jsx:52–56` defines `finalVolumeFor` as the source of truth for override-shadowed values. S6 `ResolvedTargets` (S6:589–672) hand-rolls mode lookup from a `${id}__${id}` key scheme and falls back to store links. When linkBalanceModes changes between runs but S6 hasn't re-run, **S6 and S7 will read different effective modes for the same link.** Engineer sees "1150 veh" in S6 and "1080" on S7 flow map and can't reconcile.
- **Dead/shallow code earning real cost:** `S6:240` stores `movementsReview` from the backend; S7 explicitly discards it (S7:85) and re-derives from intersections × movements. The fields ARE captured for one purpose (`dropsSummary` count) and re-derived everywhere else. Next engineer adding a T-intersection filter will pick the wrong path.
- **Do NOT add before real-corridor:** No "side-by-side AM/PM linked-scroll view," no "Download resolved-targets CSV." 200 lines each, on a file already at 881.
- **Push-back on the design review:** **Freeze S6.** If anything ships into it, it must REMOVE lines — move mode lookup into a store helper used by both S6 and S7. Otherwise the polish list earns its keep at the cost of a bug that explodes during the real-corridor run.

### Frontend
- **Most-likely cascade bug at scale:** `projectStore.js:316–336` (setIntersections) unconditionally clears `lastRun` on any intersection removal. `lastRunStaleness()` (`lib/flowMap.js:308–339`) checks staleness *after* render. At 10+ ints, reorder via S3 approach edits shifts nums; lastRun clears mid-render and the user briefly sees stale post-balance data until navigation. **Repro:** 12 ints → S6 run → S3 toggle approach on int#5 → back to S6: post-balance renders with cleared `lastRun` + old balanced volumes.
- **Brittle coupling:** `S3_ApproachConfig.jsx:55–57` auto-fills approaches in a useEffect. Delete + re-add a different intersection between mount and effect = `activeId` snaps to stale intersection. S4's `isIntersectionConfigured()` then redirects back to S3 = **redirect trap**.
- **Test verdict:** **No e2e exists.** Unit tests cover store integrity + bulk-paste parsing. The Willow self-heal test catches corruption recovery only. **Recommend ONE Playwright e2e** covering S1 → S8 happy path with intersection reorder. < 500 lines, catches: empty-state guards, lastRun staling, approach→volumes coupling, balance plumbing.
- **Disagreement with Architect:** Skip the documentation pass — the cheapest insurance is the e2e. Run it on every commit and the cascade bugs fail loudly instead of silently.

### Backend
- **Math/UI divergence at scale:** `balancer.py:315–369` (`resolve_link_volumes`) determines leg orientation from lat/lng. If two intersections share coordinates, it silently falls back to `a < b` (intersection number order). Lines 345–347 + 359–361 have no warning when fallback fires. **Consequence:** EB labeled in UI may be interpreted as WB internally → phantom NCHRP-LINK-DELTA residuals (lines 1245–1256) that look like data bugs but are geometry bugs. The engineer can't debug it.
- **Untested algorithm assumption on real data:** `balancer.py:1099–1101` — Level 2 IPF uses fixed 0.01 veh tolerance + max_iter up to 2000. Assumes Level 1 (network-level reconciliation) always converges in <500. Bodger fixture (synthetic, perfect data) doesn't exercise the cascade. Real corridor with zero rows / U-turn miscounts could jam Level 1 for 100+ iter and hand Level 2 borderline targets. Untested.
- **Hand-off verdict — NO.** `excel_export.py:99` reads `lastRun['convergence']` — which doesn't exist in the NCHRP-era lastRun shape. The export emits the wrong field; per-intersection `finalResidual` (just stored on S6) and `iterations` are computed by the backend, captured by the frontend, and **never reach the Excel**. Same for `intConverged`. Line diagram (`line_diagram.py`) renders per-int cells but no link-conservation status between them.
- **Disagreement with PM:** Don't polish UI surfaces before fixing the coordinate fallback. ½ day fix; without it, a tight-urban corridor with overlapping intersections produces mysterious balancing failures the engineer cannot debug.

---

## Where the table disagreed (and how the PM called it)

| Tension | Side A | Side B | Tie-breaker call |
|---|---|---|---|
| Polish vs consolidation | Web Designer wants token system + spacing fixes | Architect says freeze, fix dup mode lookup | **Architect.** Polish is shallow; the dup mode bug compounds when overrides + linkBalanceModes interact at scale. |
| Sidebar progress | Design review calls for it | Web Designer + Frontend reject | **Reject.** Cost > value; router locks are the honest signal. |
| Where v1 starts | PM says fix S6↔S8 reporting + S4 clip + S8 export | Backend says fix coordinate fallback first | **Both.** The export fix and coordinate fix are both ~1 day; do both. |
| S6 polish | Designer wants a one-line "drops are expected" hint | Architect wants S6 to stop growing | **Designer.** One inline string ≠ growth. Add the line, don't add a section. |
| S7 redesign in v1 | Product Designer flags 50+ drops table as blocking | PM defers S7 polish | **Designer.** Sticky Int column + drops-default-only filter is one CSS + one boolean. Cheap enough. |
| Tests vs docs | Frontend wants ONE e2e | Architect wants coupling docs | **Frontend.** Tests fail loudly; docs rot quietly. |

---

## DECISION

### Refine (v1, before real-corridor validation) — 5 items

1. **Excel export speaks the NCHRP-era language** — `backend/excel_export.py:99` currently reads `lastRun['convergence']` which doesn't exist post-redesign. Read `intConverged`, `iterations`, `finalResidual`, and the new `config` snapshot (just added on S6). Add a "Run Provenance" tab with method, windows, tolerance, per-intersection convergence. **Why over the alternatives:** without this, the deliverable cannot be audited by a colleague who doesn't open DemandIQ. Three roles flagged it independently.
2. **Line diagram renders link volumes between intersections** — `backend/line_diagram.py`. Today it draws per-intersection turning movements only. Add labels on the corridor segments showing AM (PM) resolved volume. **Why:** the diagram is half the hand-off; without link volumes a reader can't see the corridor flow story.
3. **S4 bulk-paste tolerance + 1024 column fit** — `S4_VolumeEntry.jsx:432–565` + `lib/bulkPaste` + `volumes.css:272`. Accept Excel-shaped paste: K-suffixes ("1.2K"), header variants, mixed column orders. Drop sticky-left from 220→180px and period from 36→30px. **Why:** the entry side chokes at N=10+; the deliverable fixes are moot if engineers can't even load data.
4. **Backend coordinate-degeneracy QC flag** — `backend/balancer.py:315–369` + `app.py /balance-nchrp`. When two intersections share lat/lng (or the fallback-to-num-order fires), emit a `qc_flag` ("Directional fallback used at Int N↔M — verify leg orientation"). S6 already renders qc_flags. **Why:** ½ day; without it, urban corridors with overlapping intersections produce mysterious residuals the engineer can't debug.
5. **One Playwright e2e covering S1→S8 happy path + intersection reorder** — new test under `frontend/`. Must hit: project create, 5 intersections + 4 corridor links, S3 auto-fill + edit, S4 bulk-paste, S5 defaults, S6 run + assert lastRun set, S7 view drops + one override, S8 export. **Why:** Frontend's lastRun-staling cascade and S3→S4 redirect trap are real; the e2e catches both. Single highest-leverage piece of insurance for a real-corridor run.

### Explicitly not refining (deferred to v2 — after the real-corridor run tells us what actually broke)

- **Sidebar workflow-progress indicator.** Web Designer + Frontend reject; router locks are the honest affordance.
- **S6 further polish or new panels.** Architect freeze. If anything ships into S6 it must REMOVE lines (move mode lookup to a store helper consumed by both S6 and S7).
- **CSS token system / hex-to-token migration.** Real, but cosmetic. Costs hours per session; defers without breaking the hand-off.
- **S1 analysis-period UI rework.** Engineers pick one peak; this is theoretical drag.
- **S2 basemap, S7 period toggle, 1440/1920 spacing.** Not in the deliverable path.
- **S6 button height / S5 vs S1 button standardization.** Visual rhythm, not blocking.
- **Approach-config "saved" indicator.** Confusing, not a stopper.

### Chosen approach & why

v1's story is **"the output ships."** Three roles independently named the *hand-off* — not any single screen — as the blocker. A colleague reading Akshaey's Excel + diagram today cannot verify which intersections converged, what method was used, or whether the corridor flow is internally consistent — they would have to open DemandIQ. We close that gap in five moves: two on the deliverable (export + diagram), one on entry (S4 paste + clip), one on math honesty (coordinate fallback warning), and one e2e to keep the workflow from silently breaking under the new pressure. We deliberately ship NO new screens, NO refactors of the recently-shipped S6, and NO visual-system polish. The polish list waits until a real corridor has shown us what *actually* fails — anything else is solving for the Bodger fixture, not the engineer.

### Open questions for grill-me

1. **Scale calibration.** Is the real-corridor target actually 10+ intersections / 50+ drops, or is the typical WSP job 5–7 ints? If smaller, the S7 50+ drops table is v2, not v1.
2. **Excel schema preference.** Single summary tab + raw movements (current), or multi-tab with one sheet per intersection? Affects exactly how Provenance tab is built.
3. **Line diagram layout.** AM and PM together on one figure (current), or separate figures for cleaner print? Link-volume labels make AM+PM in one figure crowded.
4. **Real-corridor dataset.** Do you have one available with the known data-quality issues (U-turns, zeros, header variants), or do we construct it as part of the e2e?
5. **Mode lookup unification (Architect's push-back).** Sign off on moving the resolved-link mode resolution into `projectStore.js` as a `resolveLinkMode(fromId, toId)` helper consumed by both S6 ResolvedTargets and S7 finalVolumeFor? Defer if too disruptive.

### Rough cost/value call

| Item | Est. | What it unlocks |
|---|---|---|
| 1. Excel export NCHRP-era + Provenance tab | ~1 day | Deliverable is self-describing; colleague can audit without DemandIQ. |
| 2. Line diagram link volumes | ~½ day | Diagram tells the corridor flow story, not just per-int detail. |
| 3. S4 bulk-paste tolerance + 1024 fit | ~1 day | Data entry doesn't choke at N=10+; engineer's time goes from hours to minutes. |
| 4. Coordinate degeneracy QC flag | ~½ day | Silent geometry bugs surface as named warnings; engineer can debug. |
| 5. One e2e S1→S8 (incl. reorder + paste) | ~1 day | Regression net for the entire workflow; cascades fail loudly. |
| **Total** | **~4 days** | DemandIQ produces a defensible WSP deliverable on a real corridor. |

After v1: run a real corridor. The v2 list is built from what *actually* broke, not from screen-by-screen QA.

### Next step

`grill-me` on the five open questions before `write-prd`. The mode-lookup unification (question 5) and the scale-calibration (question 1) both have downstream effects on item ordering.
