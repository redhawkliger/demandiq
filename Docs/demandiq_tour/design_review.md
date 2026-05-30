# DemandIQ — S1–S8 Design Review

Review of the 72-screenshot tour in `/tmp/demandiq_tour/` (8 sessions × empty/filled/edge × 1024/1440/1920). Critique applies the 10-criterion QA framework. Filenames referenced are in this folder.

**Method note / caveat:** the "filled"/"edge" states use the Alpine/I-8 tour fixture. One fixture gap matters for honesty: it does **not** carry per-intersection convergence detail, which amplifies the S6 convergence display (see S6). Items that depend on that are flagged "verify against a real run."

---

## S1 — Project Setup

**Job-to-be-done:** Stamp the study (name, client, analyst, scenario, periods) once so every downstream export is attributed correctly.

**What works:**
- 2-second clarity: title "New project" + subtitle "Set up the project once. These details flow through every step." (`S1_empty_1440.png`).
- Required fields marked with `*`; primary "Save and continue →" is disabled until valid (`S1_empty_1440.png` shows it greyed) — good gating.
- Project Type / Analysis Period as segmented pills; provenance fields (client, analyst, checker, scenario, date) all captured up front.

**What's broken or weak:**
- The page header reads **"New project" even when editing an existing project** — `S1_filled_1440.png` shows the header "New project" while the title bar reads "Alpine / I-8 Interchange Study." On a return visit this is misleading.
- **Analysis Period selection is incoherent:** in `S1_filled_1440.png` all three pills — "AM peak", "PM peak", AND "Both" — are simultaneously lit blue. "Both" is not modeled as mutually exclusive with AM/PM, so the control can't tell the user what's actually selected.
- Large dead space below and to the right at 1440/1920 (`S1_filled_1920.png` — content occupies the left ~65%, the rest is empty).

**Critical gaps (Tier 1 — must fix):**
- None. Nothing here is broken-broken.

**Should fix (Tier 2):**
- Header should reflect state: "Project Setup" (or the project name) when a project exists, "New project" only for a genuinely new one.
- Rework the Analysis Period control so it's one coherent choice: either drop "Both" (selecting AM+PM = both) or make {AM, PM, Both} mutually exclusive so exactly one is lit.

**Polish (Tier 3):**
- Use the horizontal space at ≥1440 (e.g. a "what these fields feed" preview) or narrow the content column so it doesn't read as half-empty.

**Overall verdict:** Ready. Two small correctness/clarity fixes (header label, period control) and it's clean.

---

## S2 — Map / Intersection

**Job-to-be-done:** Define *what* is being analyzed — place corridor intersections and draw the balancing links between them.

**What works:**
- Strong empty state: centered "No intersections yet" CTA pointing at "＋ Add intersection" (`S2_empty_1440.png`).
- Modeless editor reads well: numbered pins + corridor link, right-hand Intersections list with control/legs/direction pills, undo/redo, search (`S2_filled_1024.png`).
- Long names truncate cleanly with ellipsis in the list (`S2_edge_1440.png`).

**What's broken or weak:**
- **Two competing "primary" actions:** "＋ Add intersection" (top-left, accent) and "Continue →" (bottom-right, accent) are both prominent. For a first-time user the primary is Add; the screen doesn't disambiguate.
- **Destructive action adjacent to the primary:** "Reset project" sits directly above "Continue →" in the right rail (`S2_filled_1024.png`) — a misclick hazard next to the forward CTA.
- Dark CARTO tiles are low-contrast; pins/links read, but the basemap is muddy.

**Critical gaps (Tier 1 — must fix):**
- None (this screen was recently rebuilt and is functionally solid).

**Should fix (Tier 2):**
- Separate "Reset project" from "Continue" (move it into the global "New project" affordance in the header, which already exists, and remove the in-rail duplicate) to kill the misclick risk.

**Polish (Tier 3):**
- Consider a lighter/“positron” basemap option for print-quality legibility.

**Overall verdict:** Ready. The only real risk is Reset-next-to-Continue.

---

## S3 — Approach Config

**Job-to-be-done:** Tell the model which legs/movements physically exist at each intersection so balancing only touches real movements.

**What works:**
- **Best state-legibility in the app:** the left intersection nav shows green checkmarks per configured intersection (`S3_filled_1440.png`) — the only place that surfaces per-item completion.
- Movement diagrams per leg with lane counters and "Does not exist" toggles are concrete and engineer-legible.
- Page-advance ("Continue to volume entry →") is now always present and gated on all intersections being configured, with a hint when blocked (recently fixed; visible in `S3_filled_1440.png`).

**What's broken or weak:**
- Dense single-intersection view: at 1440 only NB + SB + EB legs fit; WB is below the fold and requires scrolling per intersection (`S3_filled_1440.png`). Each leg card is tall.
- Empty state is graceful: "Add intersections first. Redirecting to the map…" (`S3_empty_1440.png`).

**Critical gaps (Tier 1 — must fix):**
- None (the navigation trap here was already fixed).

**Should fix (Tier 2):**
- None blocking.

**Polish (Tier 3):**
- Tighten the per-leg cards (or 2-up the four legs) so a whole intersection fits without vertical scroll at 1440.

**Overall verdict:** Ready. Functional and the most orientation-friendly screen.

---

## S4 — Volume Entry

**Job-to-be-done:** Get raw observed AM/PM turning counts into the project — typed, pasted, or auto-extracted from count sheets.

**What works:**
- Three input paths surfaced: drag-drop file zone (.xlsx/.xls/.pdf/.csv) + "Extract counts", "Bulk paste from spreadsheet", and the manual grid (`S4_filled_1440.png`).
- PHF and HV% columns are present (they affect analysis — good to capture here).
- Long names wrap cleanly in the intersection cell rather than truncating (`S4_edge_1440.png`) — right call for a data table.

**What's broken or weak:**
- **The volume table clips at 1024:** `S4_filled_1024.png` shows EB/WB and only part of NB; **SB, PHF, and HV% are off-screen on the right** with no visible horizontal-scroll affordance. On a 1366×768 laptop (common for engineers) the rightmost counts are effectively hidden.
- **U-turn columns are dead weight:** four U columns (EB/WB/NB/SB) render all "·" (`S4_filled_1440.png`) — 4 of ~18 columns earn no space in the typical project.
- Period convention: AM/PM are shown as **separate rows** (Per column), not the "AM (PM)" parenthetical used elsewhere (defensible for *entry*, but it's a third period-UI pattern — see cross-cutting).

**Critical gaps (Tier 1 — must fix):**
- **Table horizontal overflow hides critical columns at ≤1024.** Make the grid horizontally scrollable with a sticky intersection column + a visible scroll affordance, or compress columns so SB/PHF/HV are reachable. As shipped, a laptop user can't see SB counts. *(Verify the exact breakpoint; clipping is visible at 1024.)*

**Should fix (Tier 2):**
- Sticky header row + sticky first column so movement/intersection context survives scrolling.

**Polish (Tier 3):**
- Collapse the U-turn columns by default (expandable) when no U volumes exist.

**Overall verdict:** Functional and feature-rich, but **not ready at laptop widths** until the table stops hiding columns.

---

## S5 — Balancing Settings

**Job-to-be-done:** Configure *how* the corridor will be balanced before running.

**What works:**
- **Strongest defensibility surface in the app.** The right "Configuration" card states the **method verbatim** ("NCHRP 255/765 turning-movement refinement. Per-intersection Fratar factoring…") plus a parameter summary (link resolution, direction, peak mode, windows, convergence, max iterations, link counts) — `S5_filled_1440.png`.
- **"Locked rules"** section (Rounding, U-turns) with lock icons makes invariants explicit — exactly what an engineer needs to trust the math.
- Clear controls with inline rationale ("NCHRP 255/765 requires resolving these into one value per link…").

**What's broken or weak:**
- **Config card clips at 1024:** `S5_filled_1024.png` — the summary card's right edge is cut at the viewport ("Full: 2 · Land Use: 0 · None: 0" truncated).
- "Peak hour mode" label wraps to three lines beside its toggle at 1024 (minor).

**Critical gaps (Tier 1 — must fix):**
- None.

**Should fix (Tier 2):**
- Make the two-column (settings + config card) layout stack or shrink gracefully ≤1100px so the config card isn't clipped.

**Polish (Tier 3):**
- Prevent the "Peak hour mode" label wrap.

**Overall verdict:** Ready and genuinely trustworthy — the model screen for the rest of the app to emulate.

---

## S6 — Run Analysis

**Job-to-be-done:** Run the NCHRP balance and confirm it converged cleanly before trusting the numbers.

**What works:**
- Good provenance: config summary (method, direction, windows, tolerance, max iterations, link counts), "Re-run analysis", link-conservation table with per-link Δ, and QC cards (`S6_filled_1440.png`).
- Link conservation shows all four directed links at Δ 0.0 ✓ — concrete, checkable output.

**What's broken or weak:**
- **Contradictory convergence/trust signals on the same screen.** `S6_filled_1440.png` shows **"0/3 AM CONVERGED · 3 did not converge ⚠"**, **"0/3 PM CONVERGED ⚠"**, and per-intersection "AM: did NOT stabilize / PM: did NOT stabilize" — while *simultaneously* showing **"4 links · all balanced ✓"**, **"QC FLAGS 0 / Clean / All QC checks passed"**, and an **enabled "Continue to review drops →"**. The screen tells the engineer both "this run failed to converge" and "everything's clean, proceed."
- **The same run is reported as converged on S8.** `S8_filled_1440.png` says **"Convergence 1.0% (2/2 converged)."** So S6 counts convergence per-*intersection* (0/3) and S8 counts it per-*period* (2/2) — opposite impressions from one run.
- Period handling: the link-conservation table uses an **AM/PM toggle** (`S6_filled_1440.png`), not the AM (PM) convention.

**Critical gaps (Tier 1 — must fix):**
- **Reconcile convergence reporting to one definition and make S6 and S8 agree.** Right now "converged" means different things on the two screens (0/3 intersections vs 2/2 periods) for identical data — an engineer cannot answer "did it converge?" from this product. Pick one denominator (per-intersection is the more honest one) and show it identically on S6 and S8.
  - *Honesty caveat:* the per-intersection "did NOT stabilize" is partly amplified because the tour fixture lacks per-intersection convergence detail. **Verify against a real backend run.** But the S6-vs-S8 denominator mismatch is real regardless, and the "0/X converged + QC Clean + Continue enabled" combination is a design state that should not be possible.

**Should fix (Tier 2):**
- If a run genuinely doesn't converge, gate or warn on "Continue" (don't present "QC Clean" + enabled CTA next to "0/3 converged"). At minimum, surface *why* it didn't converge inline (the truncated "did NOT stabilize i…" text is cut off).
- Replace the AM/PM toggle on the conservation table with both periods shown (AM (PM)) for consistency.

**Polish (Tier 3):**
- "Tolerance 0.5 veh" (S6) vs "Convergence 1.0%" (S5/S8) — name the same concept consistently.

**Overall verdict:** **Not ready.** The convergence story is self-contradictory across S6/S8 — and convergence trust is the entire reason this tool exists. This is the highest-priority issue in the app.

---

## S7 — Results

**Job-to-be-done:** Visually QA the balanced result and apply engineer overrides where a drop needs clamping.

**What works:**
- **Industry-aligned output:** standard turning-movement line diagrams per intersection (`S7_filled_1024.png`) — looks like a deliverable an engineer would defend, not a generic web form.
- Provenance: "Last run: 5/28/2026, 2:12:00 AM" timestamp shown in the toolbar.
- View selector (Combined / Balanced / Unbalanced / Delta) supports raw-vs-balanced QA; per-diagram note field and download.
- Graceful empty state: "Run analysis first. Redirecting…" (`S7_empty_1440.png`).

**What's broken or weak:**
- **Mixed period convention:** the toolbar has an **AM/PM toggle** AND the diagrams already render values as **"AM (PM)"** parenthetical (`S7_filled_1024.png`). So the toggle and the diagram labels encode period two different ways at once — redundant and confusing.
- The **drops-review / link-conservation / overrides screen (`/review-drops`)** — where the actual "clamp a drop" job is done — was **not captured in this 8-session tour** (the tour's S7 = `/results`). A core part of the S7 job-to-be-done is unreviewed here.

**Critical gaps (Tier 1 — must fix):**
- None observed on the captured screen.

**Should fix (Tier 2):**
- Resolve the period double-encoding: if diagrams show "AM (PM)", the AM/PM toggle is redundant for them — scope the toggle to whatever genuinely needs a single period (e.g. Delta view) or drop it.
- Capture and review `/review-drops` separately — it owns the override workflow.

**Polish (Tier 3):**
- Diagram cards are generously sized; a denser grid would let more intersections be compared without scrolling.

**Overall verdict:** Strong and trustworthy-looking; mostly ready pending the period-convention cleanup and a review of the drops screen.

---

## S8 — Export

**Job-to-be-done:** Hand off the finished corridor as report-ready artifacts.

**What works:**
- **Provenance summary card** (client, analyst, intersections, date, scenario, corridor, convergence, QC) — `S8_filled_1440.png` — exactly the header a reviewer wants.
- Clear artifact set: Excel Workbook, Project File (.demandiq.json), Diagram Grid (with Period/View options); filename field with auto-extensions; friendly "Project complete — download before starting new" nudge.
- Phase-2 PDF Report is clearly signposted as not-yet-available.

**What's broken or weak:**
- **"Convergence 1.0% (2/2 converged)" contradicts S6's "0/3 converged"** (see S6 Tier 1) — and this is the *handoff* screen, so the misleading number is the one that ends up in front of a reviewer.
- The **method is not restated** on the export summary (it's on S5/S6). For a defensible deliverable header, the method belongs here too.
- The disabled "PDF Report — PHASE 2" card occupies a full slot (`S8_filled_1440.png`) — mild placeholder noise.

**Critical gaps (Tier 1 — must fix):**
- Convergence wording must match S6 once S6 is reconciled (tracked under S6 Tier 1).

**Should fix (Tier 2):**
- Add the balancing method line to the summary card so the export header is self-describing.

**Polish (Tier 3):**
- De-emphasize the Phase-2 placeholder (smaller, or a single "coming soon" footnote) so it doesn't compete with live export cards.

**Overall verdict:** Ready *except* it currently prints a convergence figure that disagrees with S6. Fix that and it's a clean handoff screen.

---

## Cross-cutting issues

1. **Convergence is reported two incompatible ways.** S6 = "0/3 converged" (per-intersection); S8 = "2/2 converged" (per-period); S6 also uses "Tolerance 0.5 veh" while S5/S8 say "Convergence 1.0%". Same run, three framings. This is the #1 trust problem. (`S6_filled_1440.png`, `S8_filled_1440.png`)
2. **The "AM (PM)" convention is not applied consistently.** Four different period UIs across the app: S1 = AM/PM/Both pills, S4 = separate AM/PM rows, S6/S7 = AM/PM toggle, S7 diagrams = "AM (PM)" parenthetical. Every data screen makes the engineer re-learn how period is shown.
3. **No global workflow progress.** The left 01–08 nav only highlights the active step — it never shows which steps are complete or locked. The only completion feedback anywhere is S3's internal intersection checkmarks (`S3_filled_1440.png`). This weak state-legibility is what let the earlier S3 "can't advance" trap go unnoticed.
4. **Responsive breakage at laptop widths.** Wide tables/cards clip at 1024: the S4 volume table hides SB/PHF/HV (`S4_filled_1024.png`) and the S5 config card is cut off (`S5_filled_1024.png`). Conversely, several screens (S1) waste large horizontal space at 1920.
5. **Destructive actions near primaries.** "Reset project" sits beside "Continue" on S2 (`S2_filled_1024.png`); the global "New project" reset is top-right on every screen.
6. **Positives worth keeping:** empty states are uniform and graceful everywhere ("X first. Redirecting…"); S5/S6/S8 carry genuine provenance (method, params, QC, timestamp); the S7 diagrams look like a real engineering deliverable.

## Recommended order of operations (top 3 this week)

1. **Fix the convergence story (S6 ↔ S8).** Pick one convergence definition (per-intersection, the honest one), show it identically on S6 and S8, and never present "QC Clean + Continue enabled" alongside "0/X converged." *Biggest impact:* convergence trust is the product's entire reason to exist; a self-contradictory convergence readout makes every deliverable indefensible. (Verify the per-intersection display against a real backend run first — the tour fixture exaggerates it.)
2. **Unify the period (AM (PM)) convention.** One display pattern app-wide — "AM (PM)" for read-only displays (S6 conservation, S7 diagrams), stacked rows only for *entry* (S4), and drop the redundant toggles. *Biggest impact:* it touches every data screen and removes a recurring "how is period shown here?" tax that erodes polish everywhere.
3. **Add workflow completion state to the sidebar.** Mark each 01–08 step done / current / not-yet-available. *Biggest impact:* cheapest change with the broadest payoff — it orients the user on all 8 screens at once and structurally prevents "I can't tell how to advance" confusion like the S3 trap.

*Why these three over the responsive/table fixes:* #1 and #3 are about whether the engineer can *trust* and *navigate* the tool at all; #2 removes the most pervasive inconsistency. The 1024 table clipping (S4) is a real Tier-1-for-that-screen bug and should follow immediately, but it's contained to one screen, whereas the top three each improve the whole app.
