// frontend/src/lib/reviewMovements.test.mjs
// Pure-ESM tests, no runner:  node frontend/src/lib/reviewMovements.test.mjs
import { reconciliationVerdict, gapCaption } from './reviewMovements.js'
import { changelog } from './reviewMovements.js'
import { methodLabel } from './reviewMovements.js'
import { detailsModalData, IPF_TOLERANCE_VEH } from './reviewMovements.js'

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

// ADR pin #2 — direct anchor on the exact caption wording
eq(gapCaption(13), 'worst leg off its target by 13 veh', 'gapCaption exact wording (ADR pin #2)')

// changelog tests
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

eq(methodLabel({ method: 'larger' }),
   { label: 'Larger', meaning: 'each shared link takes the larger of its two raw counts' },
   'larger label+meaning')
eq(methodLabel({ method: 'average' }),
   { label: 'Average', meaning: 'each shared link takes the mean of its two raw counts' },
   'average label+meaning')
// falls back to config.linkResolution when top-level method missing
ok(methodLabel({ config: { linkResolution: 'average' } }).label === 'Average',
   'falls back to config.linkResolution')

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

console.log(`reviewMovements: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
