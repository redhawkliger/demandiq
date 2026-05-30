// stopControl rule tests — pure ESM, no runner:
//   node frontend/src/lib/stopControl.test.mjs
//
// Locks the per-control stop-assignment contract that drives both the S2
// Inspector checkboxes and the line-diagram stop bars.

import {
  approachesForControl,
  crossStreetDirs,
  stopHint,
  incompleteStopControls,
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

// ── stopHint: the silent-empty guard for One-way / Side-street / diagonal ────
// Zero selected on ANY stop control prompts (no stops would render).
ok(stopHint('One-way stop', 0) !== null, 'One-way stop with 0 selected → hint')
ok(/no stop signs/i.test(stopHint('One-way stop', 0)), 'zero hint warns no stop signs will render')
ok(stopHint('Side-street stop', 0) !== null, 'Side-street stop with 0 selected → hint')
ok(stopHint('Two-way stop', 0) !== null, 'Two-way stop with 0 selected (diagonal/unknown corridor) → hint')
// One picked is fine for One-way / Side-street (no "typically 2" nag).
ok(stopHint('One-way stop', 1) === null, 'One-way stop with 1 selected → no hint')
ok(stopHint('Side-street stop', 1) === null, 'Side-street stop with 1 selected → no hint')
// Two-way keeps its "typically 2" refinement for non-zero, non-2 counts.
ok(/2 approaches/i.test(stopHint('Two-way stop', 1)), 'Two-way with 1 → typically-2 hint')
ok(/2 approaches/i.test(stopHint('Two-way stop', 3)), 'Two-way with 3 → typically-2 hint')
ok(stopHint('Two-way stop', 2) === null, 'Two-way with exactly 2 → no hint')
// Auto-fill / non-stop controls never hint (no engineer action expected).
ok(stopHint('All-way stop', 0) === null, 'All-way stop → no hint (auto-filled)')
ok(stopHint('Signalized', 0) === null, 'Signalized → no hint (no row)')

// ── incompleteStopControls: the hard-gate input ──────────────────────────────
const ap = (overrides = {}) => ({
  EB: { exists: true, stopControlled: false },
  WB: { exists: true, stopControlled: false },
  NB: { exists: true, stopControlled: false },
  SB: { exists: true, stopControlled: false },
  ...overrides,
})
const it = (id, num, control, approaches) => ({ id, num, control, approaches })

// A clean corridor: Two-way with 2 stops, All-way (auto), Signalized → none blocked.
{
  const list = [
    it('a', 1, 'Two-way stop', ap({ EB: { exists: true, stopControlled: true }, WB: { exists: true, stopControlled: true } })),
    it('b', 2, 'All-way stop', ap({ EB: { exists: true, stopControlled: true }, WB: { exists: true, stopControlled: true }, NB: { exists: true, stopControlled: true }, SB: { exists: true, stopControlled: true } })),
    it('c', 3, 'Signalized', ap()),
  ]
  ok(incompleteStopControls(list).length === 0, 'complete corridor → nothing blocks Continue')
}

// One-way with 0 stops + Two-way with 0 stops both block; reports their nums.
{
  const list = [
    it('a', 1, 'One-way stop', ap()),                  // 0 → blocked
    it('b', 2, 'Two-way stop', ap()),                  // 0 (diagonal/unknown) → blocked
    it('c', 3, 'Two-way stop', ap({ NB: { exists: true, stopControlled: true }, SB: { exists: true, stopControlled: true } })), // ok
  ]
  const blockers = incompleteStopControls(list)
  ok(blockers.length === 2, 'two zero-selected stop controls block Continue')
  ok(blockers.map((b) => b.num).join() === '1,2', 'blockers report the right intersection nums')
}

// All-way and Signalized never block even with no flags set.
ok(incompleteStopControls([it('a', 1, 'All-way stop', ap()), it('b', 2, 'Signalized', ap())]).length === 0,
  'All-way / Signalized never block')

// A flag on a non-existent leg does NOT satisfy the gate (must exist + be stopped).
{
  const list = [it('a', 1, 'Two-way stop', ap({ WB: { exists: false, stopControlled: true } }))]
  ok(incompleteStopControls(list).length === 1, 'stop flag on a non-existent leg still counts as incomplete')
}

// Missing approaches object → incomplete (needs stops set).
ok(incompleteStopControls([it('a', 1, 'One-way stop', undefined)]).length === 1,
  'stop control with no approaches object → incomplete')

console.log(`stopControl: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
