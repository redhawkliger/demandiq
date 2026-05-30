// diagramPayload.stoppedApproaches tests — pure ESM, no runner:
//   node frontend/src/lib/diagramPayload.test.mjs
//
// Locks the stop-placement fix: stop legs come from per-approach `stopControlled`
// flags, NOT from control type. Exercises the full frontend chain
// (control → approachesForControl flags → stoppedApproaches legs) for the spec's
// scenarios, which is what the backend renderer then draws.

import { stoppedApproaches, activeLegs, intersectionGeo } from './diagramPayload.js'
import { approachesForControl } from './stopControl.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// 4-leg intersection with the canonical approach shape.
function fourLeg(control, corridorDir) {
  const approaches = approachesForControl(
    {
      EB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      WB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      NB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      SB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
    },
    control,
    corridorDir,
  )
  return { num: 1, name: 'Main & Cross', control, mainDir: 'NB/SB', approaches }
}
const stops = (it) => stoppedApproaches(it, activeLegs(it)).slice().sort()

// ── Two-way stop on an NB/SB corridor → cross street EB/WB ────────────────
ok(stops(fourLeg('Two-way stop', 'NB/SB')).join() === 'EB,WB',
  'Two-way stop (NB/SB corridor) → stops at EB,WB only')

// ── All-way stop → every leg ─────────────────────────────────────────────
ok(stops(fourLeg('All-way stop', 'NB/SB')).join() === 'EB,NB,SB,WB',
  'All-way stop → stops at all four legs')

// ── Signalized → no stops anywhere ───────────────────────────────────────
ok(stops(fourLeg('Signalized', 'NB/SB')).length === 0,
  'Signalized → no stops')

// ── Side-street stop on an NB/SB corridor → cross street EB/WB ────────────
ok(stops(fourLeg('Side-street stop', 'NB/SB')).join() === 'EB,WB',
  'Side-street stop (NB/SB corridor) → stops at EB,WB only')

// ── Stop legs are flag-driven, independent of control type ───────────────
// A hand-set flag combo (e.g. only NB) is honored verbatim, proving the
// placement no longer derives from control or mainDir.
{
  const it = {
    num: 2, name: 'X & Y', control: 'One-way stop', mainDir: 'EB/WB',
    approaches: {
      EB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      WB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      NB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: true },
      SB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
    },
  }
  ok(stops(it).join() === 'NB', 'explicit single-leg flag (NB) honored verbatim')
}

// ── A non-existing leg is never returned, even if flagged ────────────────
{
  const it = {
    num: 3, name: 'T-int', control: 'Two-way stop', mainDir: 'NB/SB',
    approaches: {
      EB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: true },
      NB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: true },
      SB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: true },
      WB: { exists: false, stopControlled: true }, // flagged but doesn't exist
    },
  }
  ok(!stops(it).includes('WB'), 'non-existing WB leg excluded despite stopControlled flag')
}

// ── intersectionGeo carries the flag-derived array into the payload ──────
{
  const geo = intersectionGeo(fourLeg('Two-way stop', 'NB/SB'))
  ok(geo.stopped_approaches.slice().sort().join() === 'EB,WB',
    'intersectionGeo.stopped_approaches reflects the flags')
}

console.log(`diagramPayload: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
