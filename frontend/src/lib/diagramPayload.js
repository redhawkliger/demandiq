// Shared helpers that turn a project intersection into the payload shape the
// backend diagram renderer expects (/intersection-diagram and /export-diagram-grid).
// Extracted from S7_Results so the S8 batch grid can build cells too.

export function stripVols(period, intersection) {
  const out = {}
  const cells = intersection.volumes?.[period] ?? {}
  for (const [mv, cell] of Object.entries(cells)) {
    if (cell?.value != null) out[mv] = cell.value
  }
  return out
}

export function activeLegs(intersection) {
  return ['EB', 'WB', 'NB', 'SB'].filter(
    (d) => intersection.approaches?.[d]?.exists !== false
  )
}

export function parseStreets(intersection) {
  const parts = (intersection.name || '').split(' & ').map((s) => s.trim())
  const first = parts[0] || ''
  const second = parts[1] || ''
  if (intersection.mainDir === 'NB/SB') return { NS: first, EW: second }
  // Default + 'EB/WB' + diagonals: first street goes on the EW axis.
  return { EW: first, NS: second }
}

// Stop bars are placed per-approach now: an approach is stop-controlled iff its
// `stopControlled` flag is set (engineer-toggled in the S2 Inspector). This drops
// the old control-type derivation (which mis-placed bars for Two-way / Side-
// street / One-way stops). The backend renderer draws a stop sign at each leg
// returned here — unchanged. `legs` are the active legs, so only existing
// approaches can be returned.
export function stoppedApproaches(intersection, legs) {
  const approaches = intersection.approaches || {}
  return legs.filter((d) => approaches[d]?.stopControlled === true)
}

export function intersectionGeo(intersection) {
  const legs = activeLegs(intersection)
  return {
    num: intersection.num,
    name: intersection.name,
    active_legs: legs,
    control: intersection.control,
    streets: parseStreets(intersection),
    stopped_approaches: stoppedApproaches(intersection, legs),
  }
}

// /intersection-diagram payload for one intersection + period + view.
export function buildPayload(intersection, period, viewMode, overrides) {
  return {
    intersection: intersectionGeo(intersection),
    u_vols: stripVols(period, intersection),
    b_vols: intersection.balanced?.[period] ?? {},
    // Stage 5: per-cell engineer overrides for this intersection's period.
    overrides: overrides?.[period]?.[String(intersection.num)] ?? {},
    // Stage 10.4: free-text caption rendered below the cell.
    annotation: intersection.diagramNote ?? '',
    view_mode: viewMode,
  }
}

// One /export-diagram-grid cell for an intersection + period. period_label is
// the AM/PM tag drawn on the cell. Annotations are intentionally omitted —
// the composite grid keeps cells uniform; notes live on the per-card PNGs.
export function buildGridCell(intersection, period, overrides) {
  return {
    intersection: intersectionGeo(intersection),
    u_vols: stripVols(period, intersection),
    b_vols: intersection.balanced?.[period] ?? {},
    overrides: overrides?.[period]?.[String(intersection.num)] ?? {},
    period_label: period,
  }
}
