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
