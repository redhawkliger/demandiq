// stopControl rule tests — pure ESM, no runner:
//   node frontend/src/lib/stopControl.test.mjs
//
// Locks the per-control stop-assignment contract that drives both the S2
// Inspector checkboxes and the line-diagram stop bars.

import {
  approachesForControl,
  crossStreetDirs,
  STOP_CONTROL_TYPES,
  AUTO_FILL_TYPES,
} from './stopControl.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

const fourLeg = () => ({
  EB: { exists: true, lanes: [{ movement: 'T' }] },
  WB: { exists: true, lanes: [{ movement: 'T' }] },
  NB: { exists: true, lanes: [{ movement: 'T' }] },
  SB: { exists: true, lanes: [{ movement: 'T' }] },
})
const stopped = (a) => Object.keys(a).filter((d) => a[d].stopControlled).sort()

// ── crossStreetDirs: both long and short corridor forms ──────────────────
ok(crossStreetDirs('EB/WB').join() === 'NB,SB', 'EB/WB corridor → cross NB,SB')
ok(crossStreetDirs('EW').join() === 'NB,SB', 'EW corridor → cross NB,SB')
ok(crossStreetDirs('NB/SB').join() === 'EB,WB', 'NB/SB corridor → cross EB,WB')
ok(crossStreetDirs('NS').join() === 'EB,WB', 'NS corridor → cross EB,WB')
ok(crossStreetDirs(undefined) === null, 'unknown corridor → null')

// ── All-way stop auto-fills every existing approach ──────────────────────
{
  const r = approachesForControl(fourLeg(), 'All-way stop', null)
  ok(stopped(r).join() === 'EB,NB,SB,WB', 'All-way stop → all four stopped')
}

// ── Two-way stop: smart default to the cross street ──────────────────────
{
  const nsCorridor = approachesForControl(fourLeg(), 'Two-way stop', 'NB/SB')
  ok(stopped(nsCorridor).join() === 'EB,WB', 'Two-way + NB/SB corridor → cross EB,WB stopped')
  const ewCorridor = approachesForControl(fourLeg(), 'Two-way stop', 'EB/WB')
  ok(stopped(ewCorridor).join() === 'NB,SB', 'Two-way + EB/WB corridor → cross NB,SB stopped')
  const unknown = approachesForControl(fourLeg(), 'Two-way stop', null)
  ok(stopped(unknown).length === 0, 'Two-way + unknown corridor → none (engineer picks)')
}

// ── Side-street stop uses the same cross-street default ──────────────────
{
  const r = approachesForControl(fourLeg(), 'Side-street stop', 'NS')
  ok(stopped(r).join() === 'EB,WB', 'Side-street + NS corridor → cross EB,WB stopped')
}

// ── One-way stop starts empty regardless of corridor ─────────────────────
{
  const r = approachesForControl(fourLeg(), 'One-way stop', 'NB/SB')
  ok(stopped(r).length === 0, 'One-way stop → starts empty')
}

// ── Non-stop control types clear every flag ──────────────────────────────
{
  const seeded = approachesForControl(fourLeg(), 'All-way stop', null) // all true
  const cleared = approachesForControl(seeded, 'Signalized', 'NB/SB')
  ok(stopped(cleared).length === 0, 'Signalized → clears all stop flags')
  ok(approachesForControl(seeded, 'Roundabout', 'NB/SB') && stopped(approachesForControl(seeded, 'Roundabout', 'NB/SB')).length === 0,
    'Roundabout → clears all stop flags')
}

// ── Non-existing legs never get stopped, other fields preserved ──────────
{
  const threeLeg = { ...fourLeg(), SB: { exists: false } }
  const r = approachesForControl(threeLeg, 'All-way stop', null)
  ok(r.SB.stopControlled === false, 'All-way stop: non-existing SB stays false')
  ok(stopped(r).join() === 'EB,NB,WB', 'All-way stop: only existing legs stopped')
  ok(r.EB.lanes.length === 1 && r.SB.exists === false, 'approach fields (lanes, exists) preserved')
}

// ── Membership sets are correct ──────────────────────────────────────────
ok(STOP_CONTROL_TYPES.has('Two-way stop') && STOP_CONTROL_TYPES.has('Side-street stop') && STOP_CONTROL_TYPES.has('One-way stop'),
  'STOP_CONTROL_TYPES holds the three toggle types')
ok(AUTO_FILL_TYPES.has('All-way stop') && !AUTO_FILL_TYPES.has('Two-way stop'),
  'AUTO_FILL_TYPES holds only All-way stop')

console.log(`stopControl: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
