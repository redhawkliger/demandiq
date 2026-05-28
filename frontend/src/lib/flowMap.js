// Stage 6 — directed-link computation for the S2 balance flow map.
//
// One S2 link object represents both directions of travel on a physical
// segment (its `direction` field is the AXIS — 'EB/WB' or 'NB/SB'). The
// flow-map view renders TWO labels per link (one per directed direction).
// This module is the single source of truth for that decomposition and
// for all derived numbers (outflow / inflow / resolved / residual /
// imbalance %) — used by both the map render and the click popup.

// Movement composition per directed direction. Mirrors the backend
// DIRECTION_SPEC in balancer.py — keep them in sync.
export const DIR_OUTFLOW = {
  EB: ['EBT', 'SBL', 'NBR'],
  WB: ['WBT', 'NBL', 'SBR'],
  NB: ['NBT', 'EBL', 'WBR'],
  SB: ['SBT', 'WBL', 'EBR'],
}
export const DIR_OUTFLOW_U = { EB: 'WBU', WB: 'EBU', NB: 'SBU', SB: 'NBU' }
export const DIR_APPROACH = {
  EB: ['EBL', 'EBT', 'EBR'],
  WB: ['WBL', 'WBT', 'WBR'],
  NB: ['NBL', 'NBT', 'NBR'],
  SB: ['SBL', 'SBT', 'SBR'],
}

export const AXIS_TO_DIRS = {
  'EB/WB': ['EB', 'WB'],
  'NB/SB': ['NB', 'SB'],
}

export const PERIODS = ['AM', 'PM']

// Imbalance color thresholds (% disagreement between upstream out and
// downstream in). Matches the spec exactly.
export const IMBALANCE_COLORS = {
  green: '#10B981',   // <= 5%
  amber: '#F59E0B',   // 5% < pct <= 15%
  red:   '#EF4444',   // > 15%
  gray:  '#6B7280',   // missing data fallback
}

export function imbalanceBucket(pct) {
  if (pct == null || !Number.isFinite(pct)) return 'gray'
  if (pct <= 5) return 'green'
  if (pct <= 15) return 'amber'
  return 'red'
}

export function imbalanceColor(pct) {
  return IMBALANCE_COLORS[imbalanceBucket(pct)]
}

// Resolve a raw-volumes cell that may be either a primitive number or a
// { value, _source } object (intersection.volumes shape).
function rawValue(cell) {
  if (cell == null) return 0
  if (typeof cell === 'object') return Number(cell.value ?? 0)
  return Number(cell) || 0
}

// Final value = override (if set) ELSE balanced. Mirrors S7's helper.
export function finalVolume(period, intNum, mv, intersection, overrides) {
  const o = overrides?.[period]?.[String(intNum)]?.[mv]
  if (o != null) return Number(o)
  return Number(intersection?.balanced?.[period]?.[mv] ?? 0)
}

// Sum of outflow movements at `intersection` heading in `direction`,
// using either RAW or FINAL (override-or-balanced) values.
export function outflowAt(intersection, period, direction, { useFinal, overrides }) {
  if (!intersection) return 0
  let total = 0
  for (const mv of DIR_OUTFLOW[direction]) {
    if (useFinal) {
      total += finalVolume(period, intersection.num, mv, intersection, overrides)
    } else {
      total += rawValue(intersection.volumes?.[period]?.[mv])
    }
  }
  const uMv = DIR_OUTFLOW_U[direction]
  if (uMv) {
    if (useFinal) {
      total += finalVolume(period, intersection.num, uMv, intersection, overrides)
    } else {
      total += rawValue(intersection.volumes?.[period]?.[uMv])
    }
  }
  return total
}

// Sum of approach movements at `intersection` arriving FROM `direction`.
// (Same direction code — e.g. an EB-directed link feeds the EB approach
// at its downstream intersection.)
export function inflowAt(intersection, period, direction, { useFinal, overrides }) {
  if (!intersection) return 0
  let total = 0
  for (const mv of DIR_APPROACH[direction]) {
    if (useFinal) {
      total += finalVolume(period, intersection.num, mv, intersection, overrides)
    } else {
      total += rawValue(intersection.volumes?.[period]?.[mv])
    }
  }
  return total
}

// Given an S2 link (axis-coded) + the two endpoint intersections, return
// the two directed entries `[{from, to, direction}, ...]`. Mirrors the
// backend's `_build_link_modes`: lng-ordering for EB/WB, lat-ordering
// for NB/SB.
export function decomposeLink(link, intsById) {
  const a = intsById.get(link.fromId)
  const b = intsById.get(link.toId)
  if (!a || !b) return []
  if (link.direction === 'EB/WB') {
    const [west, east] = a.lng <= b.lng ? [a, b] : [b, a]
    return [
      { from: west, to: east, direction: 'EB' },
      { from: east, to: west, direction: 'WB' },
    ]
  }
  if (link.direction === 'NB/SB') {
    const [south, north] = a.lat <= b.lat ? [a, b] : [b, a]
    return [
      { from: south, to: north, direction: 'NB' },
      { from: north, to: south, direction: 'SB' },
    ]
  }
  return []
}

// Enumerate every directed link with its endpoint refs. One physical S2
// link → two entries. The `axis` and `linkId` fields let callers group
// labels back to their parent link for popup display.
export function enumerateDirectedLinks(links, intersections) {
  const intsById = new Map(intersections.map((it) => [it.id, it]))
  const out = []
  for (const link of links) {
    for (const d of decomposeLink(link, intsById)) {
      out.push({
        linkId: link.id,
        axis: link.direction,
        mode: link.mode || 'Full',
        ...d,
      })
    }
  }
  return out
}

// Look up `resolved` and `link_conservation` entries from lastRun by
// (fromNum, toNum, direction). Returns a Map for O(1) lookup.
function indexLastRun(lastRun, period) {
  const resolvedMap = new Map()
  for (const r of lastRun?.resolvedLinks?.[period] ?? []) {
    resolvedMap.set(`${r.fromNum}|${r.toNum}|${r.direction}`, Number(r.volume))
  }
  const conservationMap = new Map()
  for (const c of lastRun?.linkConservation?.[period] ?? []) {
    conservationMap.set(`${c.fromNum}|${c.toNum}|${c.direction}`, c)
  }
  return { resolvedMap, conservationMap }
}

// Full per-period derivation for one directed link.
//   viewMode: 'pre' | 'post'
// Returns `{ upOut, downIn, imbalancePct, color, resolved, postValue, residual }`.
// resolved / postValue / residual are null when viewMode === 'pre' or
// when lastRun lacks the entry.
export function deriveFlow(directed, period, viewMode, ctx) {
  const { lastRun, overrides } = ctx
  const useFinal = viewMode === 'post'

  const upOut = outflowAt(directed.from, period, directed.direction, { useFinal, overrides })
  const downIn = inflowAt(directed.to,   period, directed.direction, { useFinal, overrides })

  const denom = Math.max(upOut, downIn, 1)
  const imbalancePct = (Math.abs(upOut - downIn) / denom) * 100
  const color = imbalanceColor(imbalancePct)

  let resolved = null
  let postValue = null
  let residual = null

  if (viewMode === 'post' && lastRun) {
    const { resolvedMap } = indexLastRun(lastRun, period)
    const key = `${directed.from.num}|${directed.to.num}|${directed.direction}`
    const r = resolvedMap.get(key)
    if (r != null) {
      resolved = r
      // Post-balance value reported on this directed link = upstream outflow
      // computed from the final (override-or-balanced) matrix. The residual
      // is how much the engineer's overrides have pulled it off the
      // resolved target.
      postValue = upOut
      residual  = postValue - resolved
    }
  }

  return { upOut, downIn, imbalancePct, color, resolved, postValue, residual }
}

// Convenience: derive both periods at once.
export function deriveFlowBoth(directed, viewMode, ctx) {
  return {
    AM: deriveFlow(directed, 'AM', viewMode, ctx),
    PM: deriveFlow(directed, 'PM', viewMode, ctx),
  }
}

// Color for the LINK polyline. Worst (red > amber > green > gray) of AM
// and PM. Reason: one polyline carries both periods' label, so the link
// should warn about whichever period is worse.
const RANK = { green: 0, amber: 1, red: 2, gray: -1 }
export function worstColor(amColor, pmColor) {
  const amB = nameFromHex(amColor)
  const pmB = nameFromHex(pmColor)
  return (RANK[pmB] > RANK[amB]) ? pmColor : amColor
}
function nameFromHex(hex) {
  for (const [k, v] of Object.entries(IMBALANCE_COLORS)) {
    if (v === hex) return k
  }
  return 'gray'
}

// Per-link aggregate: one entry per S2 link (NOT per directed direction),
// with both directed entries nested inside. Used by LinkLayers to color
// the polyline and by the click popup to render both directions.
//
// In POST view, a link is "no-data" when its directed pair isn't present
// in lastRun.resolvedLinks (newly added since last balance, or balance
// not yet run). No-data links render with a neutral-gray polyline and no
// volume labels — spec §1, fix v2.
export function buildLinkFlows(links, intersections, viewMode, ctx) {
  const intsById = new Map(intersections.map((it) => [it.id, it]))
  const out = []

  // Pre-index lastRun resolved keys once so the "no data" check is O(1).
  const lastRunKeys = new Set()
  if (viewMode === 'post' && ctx?.lastRun) {
    for (const r of ctx.lastRun.resolvedLinks?.AM ?? []) {
      lastRunKeys.add(`${r.fromNum}|${r.toNum}|${r.direction}`)
    }
  }

  for (const link of links) {
    const directeds = decomposeLink(link, intsById)
    if (directeds.length === 0) continue
    const perDirected = directeds.map((d) => ({
      directed: { linkId: link.id, axis: link.direction, mode: link.mode || 'Full', ...d },
      flows: deriveFlowBoth(d, viewMode, ctx),
    }))

    // In post view, "no data" = NEITHER directed entry appears in lastRun.
    // (lastRun always emits links as pairs, so checking one side is enough,
    // but we OR both for safety.)
    let hasLastRunData = true
    if (viewMode === 'post') {
      hasLastRunData = directeds.some((d) =>
        lastRunKeys.has(`${d.from.num}|${d.to.num}|${d.direction}`)
      )
    }

    // Polyline color: gray when post + no lastRun data; otherwise worst
    // imbalance across both periods × both directions.
    let polyColor = IMBALANCE_COLORS.green
    let worstPct = 0
    if (viewMode === 'post' && !hasLastRunData) {
      polyColor = IMBALANCE_COLORS.gray
    } else {
      for (const pd of perDirected) {
        for (const period of PERIODS) {
          const f = pd.flows[period]
          if (f.imbalancePct > worstPct) {
            worstPct = f.imbalancePct
            polyColor = f.color
          }
        }
      }
    }
    out.push({
      link,
      from: directeds[0].direction === 'EB' || directeds[0].direction === 'NB' ? directeds[0].from : directeds[1].from,
      to:   directeds[0].direction === 'EB' || directeds[0].direction === 'NB' ? directeds[0].to   : directeds[1].to,
      directeds: perDirected,
      polyColor,
      worstImbalancePct: worstPct,
      hasLastRunData,
    })
  }
  return out
}

// Format an AM (PM) label string.
export function fmtPair(am, pm) {
  return `${formatNum(am)} (${formatNum(pm)})`
}
function formatNum(n) {
  if (n == null || !Number.isFinite(n)) return '—'
  return Math.round(n).toLocaleString()
}

// Detect whether a post-balance render would be operating on stale data:
// if the current store has S2 links that the lastRun didn't see, OR if
// the lastRun knows about (fromNum,toNum) pairs that no longer exist in
// the current intersection set. Used by S2 to show a banner.
export function lastRunStaleness(lastRun, links, intersections) {
  if (!lastRun) return { stale: false, reason: null }
  const intNums = new Set(intersections.map((it) => it.num))
  const intsById = new Map(intersections.map((it) => [it.id, it]))

  // Current directed pairs from the S2 link list
  const currentPairs = new Set()
  for (const link of links) {
    for (const d of decomposeLink(link, intsById)) {
      currentPairs.add(`${d.from.num}|${d.to.num}|${d.direction}`)
    }
  }
  // lastRun pairs (use AM as canonical; PM mirrors AM)
  const knownPairs = new Set()
  for (const r of lastRun.resolvedLinks?.AM ?? []) {
    knownPairs.add(`${r.fromNum}|${r.toNum}|${r.direction}`)
  }

  const newPairs = [...currentPairs].filter((k) => !knownPairs.has(k))
  const goneInts = [...(lastRun.resolvedLinks?.AM ?? [])]
    .map((r) => [r.fromNum, r.toNum])
    .flat()
    .filter((n) => !intNums.has(n))

  if (newPairs.length > 0) {
    return { stale: true, reason: `${newPairs.length} new link(s) since last run` }
  }
  if (goneInts.length > 0) {
    return { stale: true, reason: `intersection(s) removed since last run` }
  }
  return { stale: false, reason: null }
}
