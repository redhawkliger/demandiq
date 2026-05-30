// convergenceLabel tests — pure ESM, no runner.
// Locks in F8: the threshold is veh, never %.

import { convergenceLabel } from './convergenceLabel.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

{
  const s = convergenceLabel({ intCount: 10, amConverged: 10, pmConverged: 10, convergenceThreshold: 0.5 })
  ok(s === 'AM 10/10 · PM 10/10 (0.50 veh threshold)', `happy path; got ${JSON.stringify(s)}`)
}

{
  // F8 bug class: the unit must never be a % sign.
  const s = convergenceLabel({ intCount: 10, amConverged: 10, pmConverged: 10, convergenceThreshold: 0.5 })
  ok(!s.includes('%'), `label must not contain '%'; got: ${s}`)
  ok(s.includes('veh'), `label must contain 'veh'; got: ${s}`)
}

{
  // Default threshold when convergenceThreshold is missing / NaN.
  const s = convergenceLabel({ intCount: 3, amConverged: 3, pmConverged: 3, convergenceThreshold: undefined })
  ok(s === 'AM 3/3 · PM 3/3 (0.50 veh threshold)', `undefined defaults to 0.50; got ${s}`)

  const s2 = convergenceLabel({ intCount: 3, amConverged: 3, pmConverged: 3, convergenceThreshold: NaN })
  ok(s2 === 'AM 3/3 · PM 3/3 (0.50 veh threshold)', `NaN defaults to 0.50; got ${s2}`)
}

{
  // Partial convergence.
  const s = convergenceLabel({ intCount: 10, amConverged: 8, pmConverged: 9, convergenceThreshold: 0.25 })
  ok(s === 'AM 8/10 · PM 9/10 (0.25 veh threshold)', `partial / tighter threshold; got ${s}`)
}

console.log(`\n  ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
