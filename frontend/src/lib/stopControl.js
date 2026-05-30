// Stop-control rules for intersection approaches.
//
// Each approach carries a boolean `stopControlled` (see projectStore.defaultApproach).
// This module centralizes which approaches are stop-controlled for a given
// control type, so the S2 Inspector, pin creation, and any future caller all
// agree — and so the logic is unit-testable independent of React.
//
// Control-type behavior:
//   Two-way / Side-street stop → smart default to the CROSS street (when the
//                                corridor direction is known); engineer overrides.
//   One-way stop               → starts empty; engineer picks the one leg.
//   All-way stop               → every existing approach is stop-controlled
//                                (auto-filled, shown read-only in the UI).
//   anything else (Signalized, → no stop control; all flags cleared so the data
//   Roundabout, …)               stays clean.

// Control types whose approaches the engineer toggles individually.
export const STOP_CONTROL_TYPES = new Set(['Two-way stop', 'Side-street stop', 'One-way stop'])
// Control types that auto-fill every existing approach (read-only in the UI).
export const AUTO_FILL_TYPES = new Set(['All-way stop'])

export const ACTIVE_DIRS = ['EB', 'WB', 'NB', 'SB']

// The cross-street legs for a corridor running along `corridorDir`. Accepts both
// the long ('EB/WB' | 'NB/SB') and short ('EW' | 'NS') forms. Returns null when
// the direction is unknown — caller should then leave all approaches unstopped.
export function crossStreetDirs(corridorDir) {
  if (corridorDir === 'EB/WB' || corridorDir === 'EW') return ['NB', 'SB']
  if (corridorDir === 'NB/SB' || corridorDir === 'NS') return ['EB', 'WB']
  return null
}

const isActive = (ap) => Boolean(ap) && ap.exists !== false

// Pure: given the current approaches map, a new control type, and the known
// corridor direction, return a NEW approaches map with `stopControlled` set per
// the rules above. Non-existing approaches are always false. Other approach
// fields (exists, lanes) are preserved. Returns the input unchanged if there
// are no approaches to act on.
export function approachesForControl(approaches, control, corridorDir) {
  if (!approaches || typeof approaches !== 'object') return approaches

  const withFlag = (decide) =>
    Object.fromEntries(
      Object.entries(approaches).map(([dir, ap]) => [
        dir,
        { ...ap, stopControlled: isActive(ap) ? decide(dir) : false },
      ])
    )

  if (AUTO_FILL_TYPES.has(control)) return withFlag(() => true)

  if (control === 'Two-way stop' || control === 'Side-street stop') {
    const cross = crossStreetDirs(corridorDir)
    if (!cross) return withFlag(() => false) // unknown corridor → engineer picks
    return withFlag((dir) => cross.includes(dir))
  }

  // One-way stop starts empty; Signalized / Roundabout / others clear all.
  return withFlag(() => false)
}
