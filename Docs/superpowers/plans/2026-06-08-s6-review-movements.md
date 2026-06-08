# S6 Review Movements Detail View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-intersection "Review Movements" detail view for S6 — a line-diagram-anchored screen that surfaces decision-bearing balanced-movement data legibly and hides solver plumbing behind a Details modal.

**Architecture:** All decision logic lives in one tested pure-function lib (`lib/reviewMovements.js`); every component is a dumb renderer of `(lastRun, selectedIntNum, period)`. The reconciliation verdict is a read-only function of `intConverged` + `finalResidual` (never re-derived from movement sums — ADR 0001). No backend change anywhere: the diagram reuses `/intersection-diagram`'s existing `view_mode` param.

**Tech Stack:** React (custom `useSyncExternalStore` pub-sub store), Vite, pure-ESM `node` logic tests (no Vitest/RTL — matches existing repo pattern), CSS custom properties.

**Source of truth:** `docs/adr/0001-s6-review-movements-reconciliation-verdict.md`, system-design §1 (data contract) and §4 (component tree), memory `corridor-order-invariant`.

---

## Testing approach (read before starting)

- **Logic = real TDD.** Every function in `lib/reviewMovements.js` gets a failing `node` test first (pattern: `frontend/src/lib/diagramPayload.test.mjs`). This is where the ADR pins, the verdict semantics, and the theme-rule disjointness are enforced and verified.
- **Components = build-verification**, not unit tests (no RTL in repo). After each component, verify the Vite transform: dev server returns HTTP 200 and the new symbol/class is present. Use `localhost`, not `127.0.0.1` (memory: IPv6-only). Components hold **zero logic** — they render lib output — so logic tests cover the risk.
- **If you want React component tests instead:** stop and add Vitest + RTL + jsdom as a setup task. The default plan does NOT, to avoid a new dependency surface the user didn't request.

## File structure

| File | Responsibility |
|---|---|
| `frontend/src/lib/reviewMovements.js` (create) | All pure derivations + the two ADR pins + status/delta class mapping. The brain. |
| `frontend/src/lib/reviewMovements.test.mjs` (create) | Node-ESM tests for every export. |
| `frontend/src/styles/themes.css` (modify) | Add `--delta-up` / `--delta-down` tokens, explicitly separate from `--signal-*`. |
| `frontend/src/styles/reviewMovements.css` (create) | `di-rm-*` styles; consumes signal tokens for status, delta tokens for direction. |
| `frontend/src/components/reviewMovements/ProvenanceHeader.jsx` (create) | Method label+meaning, period toggle, ◀▶ stepper, Details button. |
| `frontend/src/components/reviewMovements/IntersectionDiagram.jsx` (create) | Anchor PNG; Balanced⇄Changes via `view_mode`. |
| `frontend/src/components/reviewMovements/ChangelogCard.jsx` (create) | Changed movements + "N of M" + inline unchanged grid. |
| `frontend/src/components/reviewMovements/ReconciliationCard.jsx` (create) | Single verdict line from `reconciliationVerdict`. |
| `frontend/src/components/reviewMovements/CorridorRail.jsx` (create) | Corridor-order nav rail. |
| `frontend/src/components/reviewMovements/FlagIndicator.jsx` (create) | Per-int flag badge → links to verdict screen. |
| `frontend/src/components/reviewMovements/DetailsModal.jsx` (create) | Convergence · stats · link-res · config plumbing. |
| `frontend/src/sessions/S6_ReviewMovements.jsx` (create) | Container: owns `selectedIntNum` + `period`; assembles the tree. |
| `frontend/src/main.jsx` or router file (modify) | Mount the route + entry point from the S6 verdict screen. |

---

## Task 1: Reconciliation verdict — the load-bearing function (ADR 0001)

**Files:**
- Create: `frontend/src/lib/reviewMovements.js`
- Test: `frontend/src/lib/reviewMovements.test.mjs`

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/src/lib/reviewMovements.test.mjs
// Pure-ESM tests, no runner:  node frontend/src/lib/reviewMovements.test.mjs
import { reconciliationVerdict } from './reviewMovements.js'

let passed = 0, failed = 0
function ok(cond, msg) { if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) } }
function eq(a, b, msg) { ok(JSON.stringify(a) === JSON.stringify(b), `${msg} (got ${JSON.stringify(a)})`) }

// Helper: a lastRun where movement sums are DELIBERATELY imbalanced,
// to prove the verdict reads solver flags and NEVER re-derives in/out sums.
function run({ converged, residual }) {
  return {
    intConverged: { AM: { 3: converged } },
    finalResidual: { AM: { 3: residual } },
    // wildly imbalanced movements — must be IGNORED by the verdict:
    movementsReview: { AM: [
      { int_num: 3, movement: 'EBT', raw: 9999, balanced: 9999, delta: 0 },
      { int_num: 3, movement: 'WBT', raw: 1, balanced: 1, delta: 0 },
    ] },
  }
}

// converged + zero residual → balanced (green)
eq(reconciliationVerdict(run({ converged: true, residual: 0 }), 3, 'AM'),
   { state: 'balanced', status: 'green', gap: 0, label: 'balanced' },
   'converged + 0 residual → balanced')

// converged + residual → gap (amber), gap rounded, exact caption (ADR pin #2)
eq(reconciliationVerdict(run({ converged: true, residual: 12.6 }), 3, 'AM'),
   { state: 'gap', status: 'amber', gap: 13, label: 'worst leg off its target by 13 veh' },
   'converged + residual → gap with rounded veh and exact caption')

// NOT converged → red, regardless of residual being zero (must never show green)
eq(reconciliationVerdict(run({ converged: false, residual: 0 }), 3, 'AM'),
   { state: 'did-not-converge', status: 'red', gap: 0, label: 'did not converge' },
   'not converged → red even with 0 residual')

// missing flag → treated as not-converged (never green without explicit true)
eq(reconciliationVerdict({ intConverged: { AM: {} }, finalResidual: { AM: {} } }, 3, 'AM').status,
   'red', 'missing intConverged → red (safe default)')

// sub-vehicle residual rounds to 0 → balanced (rounding noise)
eq(reconciliationVerdict(run({ converged: true, residual: 0.4 }), 3, 'AM').state,
   'balanced', 'residual 0.4 rounds to 0 → balanced')

// PROPERTY: caption never contains the forbidden word "unaccounted" (ADR pin #2)
ok(!reconciliationVerdict(run({ converged: true, residual: 30 }), 3, 'AM').label.includes('unaccounted'),
   'gap caption never says "unaccounted"')

console.log(`reviewMovements: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: FAIL — `Cannot find module './reviewMovements.js'` (or `reconciliationVerdict is not a function`).

- [ ] **Step 3: Write minimal implementation**

```javascript
// frontend/src/lib/reviewMovements.js
//
// Pure derivations for the S6 Review Movements detail view.
// Every export is a pure function of (lastRun, intNum, period). Components
// render these outputs and hold NO logic — see docs/adr/0001-*.
//
// The reconciliation verdict is a READ-ONLY function of the solver's own
// intConverged + finalResidual. It NEVER re-derives in/out movement sums
// (that would be a tautology AND could disagree with the solver — ADR 0001 §0).

// ADR 0001 pin #2 — exact caption. The intersection total always reconciles,
// so the gap is the worst leg vs its TARGET, never "unaccounted".
export function gapCaption(gap) {
  return `worst leg off its target by ${gap} veh`
}

export function reconciliationVerdict(lastRun, intNum, period) {
  const converged = lastRun?.intConverged?.[period]?.[intNum] === true
  const gap = Math.round(lastRun?.finalResidual?.[period]?.[intNum] ?? 0)
  if (!converged) return { state: 'did-not-converge', status: 'red', gap, label: 'did not converge' }
  if (gap === 0)  return { state: 'balanced', status: 'green', gap: 0, label: 'balanced' }
  return { state: 'gap', status: 'amber', gap, label: gapCaption(gap) }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: PASS — `reviewMovements: 6 passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/reviewMovements.js frontend/src/lib/reviewMovements.test.mjs
git commit -m "feat(s6): reconciliation verdict reads intConverged+finalResidual (ADR 0001)"
```

---

## Task 2: Changelog derivation (changed/unchanged split + headline)

**Files:**
- Modify: `frontend/src/lib/reviewMovements.js`
- Test: `frontend/src/lib/reviewMovements.test.mjs`

- [ ] **Step 1: Append the failing test**

```javascript
// append to reviewMovements.test.mjs (before the console.log summary)
import { changelog } from './reviewMovements.js'

const mr = { AM: [
  { int_num: 3, movement: 'EBL', raw: 120, balanced: 145, delta: 25 },
  { int_num: 3, movement: 'WBT', raw: 300, balanced: 288, delta: -12 },
  { int_num: 3, movement: 'NBR', raw: 40,  balanced: 55,  delta: 15 },
  { int_num: 3, movement: 'SBT', raw: 200, balanced: 200, delta: 0 },
  { int_num: 3, movement: 'EBT', raw: 410, balanced: 410, delta: 0 },
  { int_num: 5, movement: 'EBL', raw: 99,  balanced: 50,  delta: -49 }, // other int — excluded
] }
const cl = changelog({ movementsReview: mr }, 3, 'AM')
ok(cl.totalCount === 5, `totalCount counts only int 3 rows (got ${cl.totalCount})`)
ok(cl.adjustedCount === 3, `adjustedCount = delta!=0 rows (got ${cl.adjustedCount})`)
eq(cl.changed.map(m => m.movement), ['EBL', 'NBR', 'WBT'],
   'changed sorted by |delta| desc: 25, 15, 12')
eq(cl.unchanged.map(m => m.movement), ['SBT', 'EBT'], 'unchanged = delta 0 rows, source order')
ok(cl.headline === '3 of 5 adjusted', `headline (got "${cl.headline}")`)
// zero-change case
const cl0 = changelog({ movementsReview: { AM: [
  { int_num: 7, movement: 'EBT', raw: 5, balanced: 5, delta: 0 },
] } }, 7, 'AM')
ok(cl0.adjustedCount === 0 && cl0.headline === 'No movements changed — raw counts already balanced',
   'zero-change headline')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: FAIL — `changelog is not a function`.

- [ ] **Step 3: Append the implementation**

```javascript
// append to reviewMovements.js
export function changelog(lastRun, intNum, period) {
  const rows = (lastRun?.movementsReview?.[period] ?? []).filter(m => m.int_num === intNum)
  const changed = rows.filter(m => m.delta !== 0)
    .slice().sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  const unchanged = rows.filter(m => m.delta === 0)
  const adjustedCount = changed.length
  const totalCount = rows.length
  const headline = adjustedCount === 0
    ? 'No movements changed — raw counts already balanced'
    : `${adjustedCount} of ${totalCount} adjusted`
  return { changed, unchanged, adjustedCount, totalCount, headline }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: PASS — all assertions, exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/reviewMovements.js frontend/src/lib/reviewMovements.test.mjs
git commit -m "feat(s6): changelog derivation — changed/unchanged split, |delta| sort"
```

---

## Task 3: Method label + plain-English meaning (visible, not hover-gated)

**Files:**
- Modify: `frontend/src/lib/reviewMovements.js`
- Test: `frontend/src/lib/reviewMovements.test.mjs`

- [ ] **Step 1: Append the failing test**

```javascript
import { methodLabel } from './reviewMovements.js'

eq(methodLabel({ method: 'larger' }),
   { label: 'Larger', meaning: 'each shared link takes the larger of its two raw counts' },
   'larger label+meaning')
eq(methodLabel({ method: 'average' }),
   { label: 'Average', meaning: 'each shared link takes the mean of its two raw counts' },
   'average label+meaning')
// falls back to config.linkResolution when top-level method missing
ok(methodLabel({ config: { linkResolution: 'average' } }).label === 'Average',
   'falls back to config.linkResolution')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: FAIL — `methodLabel is not a function`.

- [ ] **Step 3: Append the implementation**

```javascript
// append to reviewMovements.js
const METHOD_COPY = {
  larger:  { label: 'Larger',  meaning: 'each shared link takes the larger of its two raw counts' },
  average: { label: 'Average', meaning: 'each shared link takes the mean of its two raw counts' },
}
export function methodLabel(lastRun) {
  const key = (lastRun?.method ?? lastRun?.config?.linkResolution ?? 'larger')
  return METHOD_COPY[key] ?? METHOD_COPY.larger
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/reviewMovements.js frontend/src/lib/reviewMovements.test.mjs
git commit -m "feat(s6): method label + visible plain-English meaning"
```

---

## Task 4: Details-modal payload + the real IPF tolerance (ADR 0001 pin #1)

**Files:**
- Modify: `frontend/src/lib/reviewMovements.js`
- Test: `frontend/src/lib/reviewMovements.test.mjs`

- [ ] **Step 1: Append the failing test**

```javascript
import { detailsModalData, IPF_TOLERANCE_VEH } from './reviewMovements.js'

const lr = {
  iterations:   { AM: { 3: 14 } },
  finalResidual:{ AM: { 3: 0.006 } },
  intConverged: { AM: { 3: true } },
  maxIterations: undefined,
  config: { maxIterations: 500, convergenceThreshold: 0.5 }, // 0.5 is a DECOY
  qcFlags: [
    { check: 'SOURCE-OUTLIER', int: 3, period: 'AM', message: 'Int 3 EB ... robust σ=92 ... 15.3σ' },
    { check: 'NCHRP-LEVEL1', int: 0, message: 'corridor-level — must NOT appear for int 3' },
    { check: 'GEOMETRY-FALLBACK', int: 3, period: null, message: 'period-agnostic — should appear' },
  ],
  resolvedLinks: { AM: [
    { fromNum: 2, toNum: 3, direction: 'EB', volume: 465, reconciliation_delta: 5 },
    { fromNum: 3, toNum: 4, direction: 'EB', volume: 470, reconciliation_delta: -3 },
    { fromNum: 6, toNum: 7, direction: 'EB', volume: 100, reconciliation_delta: 0 }, // unrelated
  ] },
}
const d = detailsModalData(lr, 3, 'AM')

// ADR pin #1: tolerance is the REAL IPF tol (0.01), NOT config.convergenceThreshold (0.5)
ok(IPF_TOLERANCE_VEH === 0.01, 'IPF tolerance constant is 0.01 veh')
ok(d.toleranceVeh === 0.01, `modal tolerance is 0.01 not config 0.5 (got ${d.toleranceVeh})`)
ok(d.iterations === 14 && d.finalResidual === 0.006 && d.converged === true, 'convergence fields')
ok(d.maxIterations === 500, 'maxIterations from config')
eq(d.flags.map(f => f.check), ['SOURCE-OUTLIER', 'GEOMETRY-FALLBACK'],
   'flags: this int (incl period:null), excludes corridor-level int:0')
eq(d.resolvedLinks.map(l => `${l.fromNum}->${l.toNum}`), ['2->3', '3->4'],
   'resolvedLinks touching int 3 only')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: FAIL — `detailsModalData is not a function`.

- [ ] **Step 3: Append the implementation**

```javascript
// append to reviewMovements.js
// ADR 0001 pin #1 — the tolerance that actually governs intConverged is the
// per-intersection IPF Level-2 tol, hardcoded in backend/balancer.py:1161.
// It is NOT config.convergenceThreshold (a different Level-1 value). The
// Details modal is a defend-the-work surface, so it must show the real number.
export const IPF_TOLERANCE_VEH = 0.01

export function detailsModalData(lastRun, intNum, period) {
  const flags = (lastRun?.qcFlags ?? []).filter(
    f => f.int === intNum && (f.period == null || f.period === period),
  )
  const resolvedLinks = (lastRun?.resolvedLinks?.[period] ?? []).filter(
    l => l.fromNum === intNum || l.toNum === intNum,
  )
  return {
    iterations: lastRun?.iterations?.[period]?.[intNum],
    finalResidual: lastRun?.finalResidual?.[period]?.[intNum],
    converged: lastRun?.intConverged?.[period]?.[intNum] === true,
    toleranceVeh: IPF_TOLERANCE_VEH,
    maxIterations: lastRun?.config?.maxIterations,
    flags,
    resolvedLinks,
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/reviewMovements.js frontend/src/lib/reviewMovements.test.mjs
git commit -m "feat(s6): details modal payload + real IPF tolerance 0.01 (ADR 0001 pin #1)"
```

---

## Task 5: Navigation + the two-color-system separation (theme rule as a fitness function)

**Files:**
- Modify: `frontend/src/lib/reviewMovements.js`
- Test: `frontend/src/lib/reviewMovements.test.mjs`

- [ ] **Step 1: Append the failing test**

```javascript
import { stepIndex, statusClass, deltaClass } from './reviewMovements.js'

// nav clamps at both ends, operates on given array order (corridor invariant)
ok(stepIndex(8, 2, +1) === 3, 'next')
ok(stepIndex(8, 2, -1) === 1, 'prev')
ok(stepIndex(8, 0, -1) === 0, 'clamp at start')
ok(stepIndex(8, 7, +1) === 7, 'clamp at end')

// THEME RULE (ADR/locked): status = traffic-light (good/attention/bad);
// delta = direction (up/down), a SEPARATE system. The two class namespaces
// must be DISJOINT so a green/up delta can never read as "pass".
ok(statusClass('green') === 'di-rm-status--green', 'status green class')
ok(statusClass('amber') === 'di-rm-status--amber', 'status amber class')
ok(statusClass('red') === 'di-rm-status--red', 'status red class')
ok(deltaClass(25) === 'di-rm-delta--up', 'positive delta → up class')
ok(deltaClass(-12) === 'di-rm-delta--down', 'negative delta → down class')
const statusClasses = ['green', 'amber', 'red'].map(statusClass)
const deltaClasses = [25, -12].map(deltaClass)
ok(statusClasses.every(c => c.startsWith('di-rm-status--')), 'all status classes in status namespace')
ok(deltaClasses.every(c => c.startsWith('di-rm-delta--')), 'all delta classes in delta namespace')
ok(statusClasses.filter(c => deltaClasses.includes(c)).length === 0,
   'status and delta class namespaces are DISJOINT (two color systems never collide)')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: FAIL — `stepIndex is not a function`.

- [ ] **Step 3: Append the implementation**

```javascript
// append to reviewMovements.js

// Corridor navigation. `count` is the length of the intersections array in its
// GIVEN order (= corridor order). NEVER sort by int number — see memory
// corridor-order-invariant. Callers pass the array index, not the int num.
export function stepIndex(count, currentIndex, dir) {
  return Math.max(0, Math.min(count - 1, currentIndex + dir))
}

// Two distinct color systems, enforced as disjoint class namespaces:
//  - STATUS  → traffic-light signal palette (good/attention/bad)
//  - DELTA   → direction (a number went up vs down); NOT good vs bad
export function statusClass(status) { return `di-rm-status--${status}` }
export function deltaClass(delta)  { return `di-rm-delta--${delta >= 0 ? 'up' : 'down'}` }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: PASS — `reviewMovements: N passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/reviewMovements.js frontend/src/lib/reviewMovements.test.mjs
git commit -m "feat(s6): corridor-order nav + disjoint status/delta class namespaces"
```

---

## Task 6: Color tokens — status (signal) vs delta (direction), kept separate

**Files:**
- Modify: `frontend/src/styles/themes.css`
- Create: `frontend/src/styles/reviewMovements.css`

- [ ] **Step 1: Add delta tokens to themes.css (both theme blocks)**

In `frontend/src/styles/themes.css`, inside the `:root` / night-traffic block where `--signal-green/amber/red` are defined, add directly after them:

```css
  /* Delta colors — DIRECTION (a movement went up/down), NOT status.
     Deliberately distinct from --signal-* so "a number changed" never
     reads as "pass/fail". Values are the line-diagram renderer constants
     (backend/line_diagram.py DG_DELTA_UP / DG_DELTA_DOWN). */
  --delta-up:   #2D8050;
  --delta-down: #B0413E;
```

Add the same two lines to the sunshine (light theme) block so both themes define them.

- [ ] **Step 2: Create reviewMovements.css with the two systems wired separately**

```css
/* frontend/src/styles/reviewMovements.css
   Status uses the traffic-light signal palette. Delta uses the direction
   tokens. The two never share a color — see ADR 0001 / locked theme rule. */

.di-rm { background: var(--bg-base); color: var(--text-primary); font-family: var(--font-sans); }
.di-rm__body { display: grid; grid-template-columns: 1fr 320px; gap: 16px; padding: 20px; }
.di-rm__anchor { background: var(--surface, var(--bg-elevated)); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.di-rm__rail { display: flex; flex-direction: column; gap: 12px; }

.di-rm-card { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.di-rm-card__label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); margin-bottom: 8px; }

/* STATUS — traffic-light. green=good, amber=attention, red=bad. */
.di-rm-status { font-family: var(--font-display); font-size: 15px; display: flex; align-items: center; gap: 8px; }
.di-rm-status--green { color: var(--signal-green); }
.di-rm-status--amber { color: var(--signal-amber); }
.di-rm-status--red   { color: var(--signal-red); }

/* DELTA — direction. up/down, NOT good/bad. Separate palette on purpose. */
.di-rm-delta { font-variant-numeric: tabular-nums; }
.di-rm-delta--up   { color: var(--delta-up); }
.di-rm-delta--down { color: var(--delta-down); }

.di-rm-change { display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; font-size: 12px; font-variant-numeric: tabular-nums; padding: 4px 0; }
.di-rm-unchanged-toggle { background: none; border: none; color: var(--text-secondary); font-size: 11px; cursor: pointer; padding: 6px 0; }

.di-rm-prov { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--border); background: var(--bg-elevated); }
.di-rm-prov__method { font-size: 12px; color: var(--text-secondary); }
.di-rm-prov__method b { color: var(--text-primary); }
.di-rm-chip { border: 1px solid var(--accent, #60A5FA); color: var(--text-secondary); border-radius: 8px; padding: 3px 8px; font-size: 11px; }
```

- [ ] **Step 3: Verify the dev server transforms the CSS**

Run (dev server already on :3000 per project): `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/src/styles/reviewMovements.css`
Expected: `200`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles/themes.css frontend/src/styles/reviewMovements.css
git commit -m "feat(s6): delta tokens distinct from signal palette + review-movements styles"
```

---

## Task 7: ReconciliationCard — single verdict line, no twin totals

**Files:**
- Create: `frontend/src/components/reviewMovements/ReconciliationCard.jsx`

- [ ] **Step 1: Write the component (renders lib output only — no logic, no twin totals)**

```jsx
// frontend/src/components/reviewMovements/ReconciliationCard.jsx
import { reconciliationVerdict, statusClass } from '../../lib/reviewMovements'

// Single verdict line. Per ADR 0001: NO twin in/out totals (they are always
// equal — a check that cannot fail). The verdict is read from the solver.
export default function ReconciliationCard({ lastRun, intNum, period }) {
  const v = reconciliationVerdict(lastRun, intNum, period)
  const glyph = v.status === 'green' ? '✓' : '⚠'
  return (
    <div className="di-rm-card">
      <div className="di-rm-card__label">Flow reconciles</div>
      <div className={`di-rm-status ${statusClass(v.status)}`}>
        <span aria-hidden="true">{glyph}</span>
        <span>{v.label}</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify Vite transforms the module**

Temporarily import it where it will be used (or rely on Task 13's container). Run:
`curl -s http://localhost:3000/src/components/reviewMovements/ReconciliationCard.jsx | grep -c reconciliationVerdict`
Expected: `1` (module is served and references the lib).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/reviewMovements/ReconciliationCard.jsx
git commit -m "feat(s6): ReconciliationCard — single verdict line, no twin totals"
```

---

## Task 8: ChangelogCard — changed rows + inline unchanged disclosure

**Files:**
- Create: `frontend/src/components/reviewMovements/ChangelogCard.jsx`

- [ ] **Step 1: Write the component**

```jsx
// frontend/src/components/reviewMovements/ChangelogCard.jsx
import { useState } from 'react'
import { changelog, deltaClass } from '../../lib/reviewMovements'
import MovementSvg from '../MovementSvg'

function Row({ m }) {
  const sign = m.delta > 0 ? '+' : ''
  const arrow = m.delta > 0 ? '▲' : '▼'
  return (
    <div className="di-rm-change">
      <MovementSvg code={m.movement} height={20} color="var(--delta-up)" />
      <span>{m.movement}&nbsp;&nbsp;{m.raw} → {m.balanced}</span>
      <span className={`di-rm-delta ${deltaClass(m.delta)}`}>{sign}{m.delta} {arrow}</span>
    </div>
  )
}

export default function ChangelogCard({ lastRun, intNum, period }) {
  const [showUnchanged, setShowUnchanged] = useState(false)
  const cl = changelog(lastRun, intNum, period)
  return (
    <div className="di-rm-card">
      <div className="di-rm-card__label">What changed · {cl.headline}</div>
      {cl.changed.map((m, i) => <Row key={i} m={m} />)}
      {cl.unchanged.length > 0 && (
        <>
          <button className="di-rm-unchanged-toggle" onClick={() => setShowUnchanged(s => !s)}>
            {showUnchanged ? '▾' : '▸'} {cl.unchanged.length} unchanged
          </button>
          {showUnchanged && cl.unchanged.map((m, i) => (
            <div className="di-rm-change" key={`u${i}`}>
              <MovementSvg code={m.movement} height={20} color="var(--text-tertiary)" />
              <span>{m.movement}&nbsp;&nbsp;{m.raw} → {m.balanced}</span>
              <span className="di-rm-delta">0</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
```

Note: changed-row glyphs use the delta tokens (direction), never the signal palette.

- [ ] **Step 2: Verify Vite transforms the module**

Run: `curl -s http://localhost:3000/src/components/reviewMovements/ChangelogCard.jsx | grep -c "changelog"`
Expected: `1`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/reviewMovements/ChangelogCard.jsx
git commit -m "feat(s6): ChangelogCard — changed rows + inline unchanged disclosure"
```

---

## Task 9: IntersectionDiagram — anchor PNG with Balanced⇄Changes toggle

**Files:**
- Create: `frontend/src/components/reviewMovements/IntersectionDiagram.jsx`

- [ ] **Step 1: Write the component (reuses /intersection-diagram view_mode — no backend change)**

```jsx
// frontend/src/components/reviewMovements/IntersectionDiagram.jsx
import { useEffect, useState } from 'react'
import { buildPayload } from '../../lib/diagramPayload'

// Same fetch shape as S7_Results.jsx:45 — POST /api/intersection-diagram → { png: base64 }.
async function fetchDiagram(payload) {
  const res = await fetch('/api/intersection-diagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* keep status */ }
    throw new Error(detail)
  }
  return await res.json()
}

export default function IntersectionDiagram({ intersection, period }) {
  // 'balanced' is the default (the deliverable). 'delta' is the Changes lens.
  const [mode, setMode] = useState('balanced')
  const [png, setPng] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    if (!intersection) return
    setErr(null); setPng(null)
    fetchDiagram(buildPayload(intersection, period, mode))
      .then(d => { if (live) setPng(d.png) })
      .catch(e => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [intersection, period, mode])

  return (
    <div className="di-rm__anchor">
      <div className="di-segmented" role="group" aria-label="diagram view mode">
        <button aria-pressed={mode === 'balanced'} onClick={() => setMode('balanced')}>Balanced</button>
        <button aria-pressed={mode === 'delta'} onClick={() => setMode('delta')}>Changes</button>
      </div>
      {err && <div className="di-banner">{err}</div>}
      {png && (
        <img
          src={`data:image/png;base64,${png}`}
          alt={`Intersection ${intersection?.num} line diagram (${mode})`}
          draggable={false}
          style={{ width: '100%', display: 'block' }}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify Vite transforms + the param wiring**

Run: `curl -s http://localhost:3000/src/components/reviewMovements/IntersectionDiagram.jsx | grep -c "buildPayload"`
Expected: `1`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/reviewMovements/IntersectionDiagram.jsx
git commit -m "feat(s6): IntersectionDiagram anchor + Balanced/Changes via view_mode reuse"
```

---

## Task 10: DetailsModal — the plumbing, including the real tolerance

**Files:**
- Create: `frontend/src/components/reviewMovements/DetailsModal.jsx`

- [ ] **Step 1: Write the component (renders detailsModalData — tolerance comes from the lib)**

```jsx
// frontend/src/components/reviewMovements/DetailsModal.jsx
import { detailsModalData } from '../../lib/reviewMovements'

// Defend-the-work surface. The tolerance shown is data.toleranceVeh (0.01,
// the real IPF tol from the lib) — the component NEVER reaches for
// config.convergenceThreshold. ADR 0001 pin #1 lives in the lib, not here.
export default function DetailsModal({ lastRun, intNum, period, onClose }) {
  const d = detailsModalData(lastRun, intNum, period)
  return (
    <div className="di-modal" role="dialog" aria-modal="true" aria-label="Details — show the math">
      <div className="di-modal__body">
        <button className="di-modal__close" onClick={onClose} aria-label="Close">×</button>

        <h3>Convergence</h3>
        <p>{d.converged ? 'Converged ✓' : 'Did not converge'} in {d.iterations} iterations ·
           final residual {d.finalResidual} veh
           (tolerance {d.toleranceVeh} veh · max {d.maxIterations} iter)</p>

        <h3>Source statistics</h3>
        {d.flags.length === 0 ? <p>No flags for this intersection.</p>
          : <ul>{d.flags.map((f, i) => <li key={i}><b>{f.check}</b> — {f.message}</li>)}</ul>}

        <h3>Link resolution</h3>
        <table className="di-s6-rt__table">
          <thead><tr><th>link</th><th>dir</th><th>target</th><th>reconciliation Δ</th></tr></thead>
          <tbody>
            {d.resolvedLinks.map((l, i) => (
              <tr key={i}>
                <td>{l.fromNum}→{l.toNum}</td><td>{l.direction}</td>
                <td>{l.volume}</td><td>{l.reconciliation_delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify Vite transforms + the tolerance source**

Run: `curl -s http://localhost:3000/src/components/reviewMovements/DetailsModal.jsx | grep -c "toleranceVeh"`
Expected: `1`. Also confirm the component does NOT reference the decoy:
`curl -s http://localhost:3000/src/components/reviewMovements/DetailsModal.jsx | grep -c "convergenceThreshold"`
Expected: `0`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/reviewMovements/DetailsModal.jsx
git commit -m "feat(s6): DetailsModal — plumbing + real IPF tolerance via lib (ADR 0001 pin #1)"
```

---

## Task 11: ProvenanceHeader — method (visible meaning), period toggle, stepper, Details

**Files:**
- Create: `frontend/src/components/reviewMovements/ProvenanceHeader.jsx`

- [ ] **Step 1: Write the component**

```jsx
// frontend/src/components/reviewMovements/ProvenanceHeader.jsx
import { methodLabel } from '../../lib/reviewMovements'

export default function ProvenanceHeader({
  lastRun, intersection, position, total, period,
  onPrev, onNext, onPeriod, onOpenDetails,
}) {
  const m = methodLabel(lastRun)
  return (
    <div className="di-rm-prov">
      <button onClick={onPrev} aria-label="Previous intersection">◀</button>
      <span>Int {position} / {total} · {intersection?.name}</span>
      <button onClick={onNext} aria-label="Next intersection">▶</button>

      <div className="di-segmented" role="group" aria-label="peak period">
        <button aria-pressed={period === 'AM'} onClick={() => onPeriod('AM')}>AM</button>
        <button aria-pressed={period === 'PM'} onClick={() => onPeriod('PM')}>PM</button>
      </div>

      {/* Method meaning is VISIBLE surface text — not hover-gated (locked design). */}
      <span className="di-rm-prov__method">
        Resolution: <b>{m.label}</b> — {m.meaning}
      </span>

      <button className="di-btn-ghost" onClick={onOpenDetails} style={{ marginLeft: 'auto' }}>
        ▦ Details — show the math
      </button>
    </div>
  )
}
```

- [ ] **Step 2: Verify Vite transforms + visible meaning (not hover-gated)**

Run: `curl -s http://localhost:3000/src/components/reviewMovements/ProvenanceHeader.jsx | grep -c "m.meaning"`
Expected: `1` (the meaning is rendered as text, not in a title/hover attribute).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/reviewMovements/ProvenanceHeader.jsx
git commit -m "feat(s6): ProvenanceHeader — visible method meaning, period+stepper+Details"
```

---

## Task 12: CorridorRail + FlagIndicator

**Files:**
- Create: `frontend/src/components/reviewMovements/CorridorRail.jsx`
- Create: `frontend/src/components/reviewMovements/FlagIndicator.jsx`

- [ ] **Step 1: Write CorridorRail (consumes intersections in GIVEN order)**

```jsx
// frontend/src/components/reviewMovements/CorridorRail.jsx
// Iterates intersections in array order (= corridor order). NEVER sorts by num
// — see memory corridor-order-invariant. Selection is by array index.
export default function CorridorRail({ intersections, selectedIndex, onSelect }) {
  return (
    <div className="di-rm-rail-strip" role="tablist" aria-label="corridor intersections">
      {intersections.map((it, i) => (
        <button
          key={it.id ?? i}
          role="tab"
          aria-selected={i === selectedIndex}
          onClick={() => onSelect(i)}
          style={{ fontWeight: i === selectedIndex ? 700 : 400 }}
        >
          {it.num}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Write FlagIndicator**

```jsx
// frontend/src/components/reviewMovements/FlagIndicator.jsx
import { detailsModalData } from '../../lib/reviewMovements'

// Light per-intersection flag badge; links back to the S6 verdict/queue screen
// where flags are actioned. Reuses the same flag filter as the modal.
export default function FlagIndicator({ lastRun, intNum, period, onGoToVerdict }) {
  const { flags } = detailsModalData(lastRun, intNum, period)
  if (flags.length === 0) return null
  return (
    <button className="di-btn-ghost" onClick={onGoToVerdict}>
      ⚠ {flags.length} flag{flags.length > 1 ? 's' : ''} — review →
    </button>
  )
}
```

- [ ] **Step 3: Verify both transform**

Run: `for f in CorridorRail FlagIndicator; do curl -s -o /dev/null -w "$f %{http_code}\n" "http://localhost:3000/src/components/reviewMovements/$f.jsx"; done`
Expected: both `200`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/reviewMovements/CorridorRail.jsx frontend/src/components/reviewMovements/FlagIndicator.jsx
git commit -m "feat(s6): CorridorRail (corridor-order nav) + FlagIndicator"
```

---

## Task 13: ReviewMovementsView container — owns selectedIntNum + period, assembles the tree

**Files:**
- Create: `frontend/src/sessions/S6_ReviewMovements.jsx`

- [ ] **Step 1: Write the container**

```jsx
// frontend/src/sessions/S6_ReviewMovements.jsx
import { useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { subscribe, getSnapshot } from '../store/projectStore'
import { stepIndex } from '../lib/reviewMovements'

import ProvenanceHeader from '../components/reviewMovements/ProvenanceHeader'
import IntersectionDiagram from '../components/reviewMovements/IntersectionDiagram'
import ChangelogCard from '../components/reviewMovements/ChangelogCard'
import ReconciliationCard from '../components/reviewMovements/ReconciliationCard'
import CorridorRail from '../components/reviewMovements/CorridorRail'
import FlagIndicator from '../components/reviewMovements/FlagIndicator'
import DetailsModal from '../components/reviewMovements/DetailsModal'

import '../styles/forms.css'
import '../styles/balancing.css' // .di-segmented
import '../styles/map.css'       // .di-modal, .di-banner, .di-btn-ghost
import '../styles/reviewMovements.css'

export default function S6_ReviewMovements() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const navigate = useNavigate()
  const lastRun = snap.analysis?.lastRun ?? null
  const intersections = snap.intersections || [] // GIVEN order = corridor order

  const [selectedIndex, setSelectedIndex] = useState(0)
  const [period, setPeriod] = useState('AM')
  const [showDetails, setShowDetails] = useState(false)

  if (!lastRun) return <div className="di-rm"><p style={{ padding: 20 }}>No analysis run yet.</p></div>
  if (intersections.length === 0) return <div className="di-rm"><p style={{ padding: 20 }}>No corridor.</p></div>

  const idx = Math.min(selectedIndex, intersections.length - 1)
  const intersection = intersections[idx]
  const intNum = intersection.num

  return (
    <div className="di-rm">
      <ProvenanceHeader
        lastRun={lastRun}
        intersection={intersection}
        position={idx + 1}
        total={intersections.length}
        period={period}
        onPrev={() => setSelectedIndex(stepIndex(intersections.length, idx, -1))}
        onNext={() => setSelectedIndex(stepIndex(intersections.length, idx, +1))}
        onPeriod={setPeriod}
        onOpenDetails={() => setShowDetails(true)}
      />

      <div className="di-rm__body">
        <IntersectionDiagram intersection={intersection} period={period} />
        <div className="di-rm__rail">
          <ChangelogCard lastRun={lastRun} intNum={intNum} period={period} />
          <ReconciliationCard lastRun={lastRun} intNum={intNum} period={period} />
          <FlagIndicator lastRun={lastRun} intNum={intNum} period={period}
                         onGoToVerdict={() => navigate('/s6')} />
        </div>
      </div>

      <CorridorRail intersections={intersections} selectedIndex={idx} onSelect={setSelectedIndex} />

      {showDetails && (
        <DetailsModal lastRun={lastRun} intNum={intNum} period={period}
                      onClose={() => setShowDetails(false)} />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify Vite transforms the container**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/src/sessions/S6_ReviewMovements.jsx`
Expected: `200`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/sessions/S6_ReviewMovements.jsx
git commit -m "feat(s6): ReviewMovementsView container — owns selectedIntNum + period"
```

---

## Task 14: Mount the route + entry from the S6 verdict screen

**Files:**
- Modify: the app router (grep first — see Step 1)
- Modify: `frontend/src/sessions/S6_RunAnalysis.jsx` (footer link)

- [ ] **Step 1: Locate the router and the route convention**

Run: `grep -rn "react-router" frontend/src/main.jsx frontend/src/App.jsx 2>/dev/null; grep -rn "path=\"/s" frontend/src/`
Expected: the file (likely `frontend/src/App.jsx` or `main.jsx`) with `<Route path="/s7" .../>` style entries. Use the same pattern.

- [ ] **Step 2: Add the route**

In the router file, add alongside the existing S-route entries (matching their exact import + `<Route>` style):

```jsx
import S6_ReviewMovements from './sessions/S6_ReviewMovements'
// ...inside <Routes>:
<Route path="/s6/review-movements" element={<S6_ReviewMovements />} />
```

- [ ] **Step 3: Add the entry link in the S6 verdict footer**

In `frontend/src/sessions/S6_RunAnalysis.jsx`, in the action footer (around lines 412–465), add a button consistent with the existing footer buttons:

```jsx
<button className="di-btn-secondary" onClick={() => navigate('/s6/review-movements')}>
  Review movements →
</button>
```

(If `navigate` isn't already in scope there, it is via `useNavigate()` — S6 already imports react-router per the recon.)

- [ ] **Step 4: Verify the route renders**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/s6/review-movements`
Expected: `200` (SPA index served). Then load it in the browser and confirm the diagram + rail render for a run.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sessions/S6_RunAnalysis.jsx <router-file>
git commit -m "feat(s6): mount Review Movements route + entry from verdict screen"
```

---

## Task 15: Full lib test sweep + principal-engineer review

**Files:** none (verification + review gate)

- [ ] **Step 1: Run the complete lib test suite**

Run: `node frontend/src/lib/reviewMovements.test.mjs`
Expected: `reviewMovements: N passed, 0 failed`, exit 0.

- [ ] **Step 2: Confirm no ADR-pin regressions via grep**

Run:
```bash
grep -n "unaccounted" frontend/src/ -r ; echo "expect: no matches"
grep -n "convergenceThreshold" frontend/src/components/reviewMovements/ -r ; echo "expect: no matches"
grep -n "IPF_TOLERANCE_VEH = 0.01" frontend/src/lib/reviewMovements.js ; echo "expect: 1 match"
```
Expected: caption word absent from the view; the decoy config field never referenced by the modal; the tolerance constant present.

- [ ] **Step 3: Principal-engineer review (REQUIRED SUB-SKILL: superpowers:requesting-code-review)**

Request a code review of the full diff against this plan and ADR 0001. The reviewer must confirm:
- Reconciliation verdict reads `intConverged` + `finalResidual` only; no movement-sum re-derivation anywhere (ADR 0001 §0).
- No twin in/out totals rendered.
- DetailsModal tolerance is `0.01` from the lib, never `config.convergenceThreshold` (pin #1).
- Gap caption is exactly "worst leg off its target by N veh"; "unaccounted" never appears (pin #2).
- Status classes (signal palette) and delta classes (direction palette) are disjoint; no green/up delta reads as "pass".
- CorridorRail iterates intersections in given array order; no sort-by-num (corridor-order-invariant).
- No backend files modified.

- [ ] **Step 4: Address review findings (REQUIRED SUB-SKILL: superpowers:receiving-code-review), then deliver.**

---

## Self-review (against spec + ADR)

- **§1 data contract coverage:** changelog (T2), unchanged grid (T2/T8), reconciliation verdict (T1/T7), method label (T3/T11), Details modal incl. all four sections (T4/T10), diagram view_mode (T9), corridor rail (T5/T12), AM/PM (T11/T13), flag indicator (T4/T12). ✓
- **§4 component tree:** all seven children + container present (T7–T13). ✓
- **ADR pin #1 (tolerance):** T4 (lib constant + test) and T10 (modal renders it; decoy grep). ✓
- **ADR pin #2 (caption):** T1 (exact string + "unaccounted" property test). ✓
- **Theme rule:** T5 (disjoint namespaces test) + T6 (separate tokens). ✓
- **Corridor order:** T5 (`stepIndex` on index, documented) + T12 (rail given-order). ✓
- **No backend change:** confirmed — every task touches `frontend/` only; diagram reuses existing `view_mode`. ✓
- **Placeholder scan:** no TBD/TODO; every code step has complete code. One deliberate grep-first in T14 Step 1 (router file location is environment-specific) — resolved within the same task, not a placeholder in delivered code. ✓
```
