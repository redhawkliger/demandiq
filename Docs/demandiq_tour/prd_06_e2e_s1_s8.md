# PRD-06 — End-to-end test: S1→S8 happy path + intersection reorder

**Status:** ready to build
**Owner:** frontend
**Order:** 6 of 6 (last — runs after PRDs 1–5 ship so it covers the new shape)
**Est:** ~1 day

## Why

No e2e test exists. Unit tests cover `projectStore` integrity + bulk-paste parsing; the Willow self-heal test covers corruption recovery. None of them catch the cascade bugs Frontend flagged at the kickoff:

- `projectStore.js:316–336` (setIntersections) unconditionally clears `lastRun` on any intersection removal. At N=10+, an S3 approach edit can trigger a reorder; `lastRun` clears mid-render and the user briefly sees stale post-balance data until navigation refreshes.
- `S3_ApproachConfig.jsx:55–57` auto-fills approaches in a useEffect; delete+re-add of an intersection between mount and effect snaps `activeId` to a stale ref → S4's `isIntersectionConfigured()` returns false → S3 → S4 redirect loop trap.

One Playwright e2e covering the full happy path + a reorder stress sub-test is the single highest-leverage piece of insurance for a real-corridor run. Frontend's call.

## What (scope in / out)

**In — happy path:**
- Project create → name + analysisPeriods.
- S2: add 5 intersections + 4 corridor links (`Full` mode).
- S3: auto-fill approaches, edit one intersection's leg config.
- S4: bulk-paste AM + PM volumes for all 5 intersections (uses the tolerance-enabled parser from PRD-04).
- S5: accept defaults; no edits.
- S6: click Run analysis; wait for `.di-s6-hero2`; assert `lastRun.intConverged` keys match intersection nums; assert no GEOMETRY-FALLBACK flag.
- S7: navigate; assert flow map renders; apply one override; assert override persists.
- S8: navigate; trigger export; assert 3 tabs present (Provenance / Combined View / Raw Movements per PRD-02); assert two line-diagram files (AM + PM per PRD-03).

**In — reorder stress sub-test:**
- 10 intersections + 9 corridor links → S6 run → S3 toggle approach on int #5 (triggers reorder) → back to S6.
- Assert `lastRun` is null (cleared honestly), assert no stale balanced volumes render, assert no S3→S4 redirect loop fires.

**Out:**
- Visual regression / screenshot diffing.
- Multi-browser matrix (Chrome only via `channel:'chrome'`, matching the verification pattern we've used).
- CI integration as a code change in this PRD — just provide the runnable command; CI wiring is its own decision.

## How

- New file: `frontend/tests/e2e/s1_s8_happy.spec.mjs` (location subject to existing convention — check first).
- Reuse the verification-script pattern: `playwright-core --no-save`, system Chrome `channel:'chrome'`, `localhost` (not `127.0.0.1`).
- Use `localStorage` seeding for setup state where it shortcuts UI clicks (e.g. project create can be a click-through; intersections are added via UI to exercise S2; volumes via paste to exercise PRD-04).
- Backend running on `:8000` is a prerequisite — fail fast with a clear message if `/api/balance-nchrp` 5xx's.

## Acceptance criteria

- [ ] Test runs in <60s wall-clock on developer machine.
- [ ] Asserts URL transition: `/setup → /map → /approach → /volumes → /balancing → /analysis → /review-drops → /results`.
- [ ] `lastRun.intConverged` keys are exactly the integer-string forms of the seeded intersection nums.
- [ ] S8 export downloads (filename match: `<project>_*.xlsx`) AND opens to verify 3 tabs (use a small zip/xlsx peek, no full parse).
- [ ] Line diagram files exist in the export bundle, both AM and PM.
- [ ] Reorder sub-test: after toggling S3 approach on int #5 of 10, `lastRun` is null on next S6 render — NOT stale data showing.
- [ ] Reorder sub-test: no redirect bounces between S3 and S4 (assert URL doesn't oscillate within 2s after reorder).
- [ ] Test cleans up after itself: localStorage cleared, no leftover backend state.
- [ ] Runnable via single command (`node tests/e2e/s1_s8_happy.spec.mjs` or `npx playwright test` — match existing convention).
- [ ] Documented in README or test-suite index with the prerequisite ("backend must be running on :8000").

## Risks / open

- The reorder cascade isn't perfectly deterministic — if it flakes, capture the failing state to a screenshot + JSON dump rather than retrying.
- If CI infrastructure doesn't exist yet, deferring CI wiring is fine; the test is still useful as a pre-merge gate run locally.
- If the bulk-paste parser from PRD-04 ships late, the e2e can fall back to per-cell entry; flag that as a regression risk if PRD-04 slips past PRD-06.
