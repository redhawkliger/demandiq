// Single source of truth for rendering corridor adjacency on a map.
//
// Corridor topology is the explicit `links` graph (fromId/toId reference
// intersection.id — NOT num, NOT array position). Any map that draws segments
// between intersections must derive them from THIS — never by re-sorting or by
// array/numeric order, which drifts from the real corridor (see the
// corridor-order invariant: a surface that re-derives adjacency by number will
// wrongly pair numerically-adjacent intersections, e.g. 4→3 instead of 4→2).
//
// Returns one entry per renderable link: { id, direction, from: [lat,lng],
// to: [lat,lng] }. Orphan links (an endpoint id not in `intersections`) are
// skipped, mirroring MapView's LinkLayer.
export function buildCorridorSegments(intersections, links) {
  const byId = new Map((intersections || []).map((it) => [it.id, it]))
  const segments = []
  for (const link of links || []) {
    const from = byId.get(link.fromId)
    const to = byId.get(link.toId)
    if (!from || !to) continue // orphaned link — render nothing
    segments.push({
      id: link.id,
      direction: link.direction,
      from: [from.lat, from.lng],
      to: [to.lat, to.lng],
    })
  }
  return segments
}
