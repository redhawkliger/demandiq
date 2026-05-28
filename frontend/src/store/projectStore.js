// DemandIQ project store.
// One project at a time, persisted to browser localStorage. Reactive via a tiny
// pub-sub so components can subscribe with React's useSyncExternalStore.
//
// Snapshot shape (additive — sessions add their own slices over time):
//   {
//     project: {           ← S1 metadata
//       name, client, projectNumber, analyst, checker,
//       date, scenario, projectType, analysisPeriods,
//     },
//     // intersections, volumes, balancing, results, ...   (later sessions)
//   }

const STORAGE_KEY = 'demandiq:project'

let _snapshot = null
let _initialized = false
const _listeners = new Set()

function _initSnapshot() {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw) {
    try { _snapshot = JSON.parse(raw) } catch { _snapshot = {} }
  } else {
    _snapshot = {}
  }
  _initialized = true
  // Old projects (pre-links model) get default consecutive links generated
  // once, here at load time. Run-once: gated on links being empty/absent AND
  // intersections ≥ 2 — so this never re-fires after init for the same load,
  // and is skipped when the user already has links.
  if (_migrateLinksIfNeeded()) _persist()
}

// Internal link-ID generator. Matches the intersection ID style (crypto.randomUUID
// with a fallback) but prefixed `lnk_` so links are visually distinguishable
// from intersections in DevTools / exported JSON.
function _newLinkId() {
  const u =
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  return `lnk_${u}`
}

// Migration: if a project has ≥2 intersections but no `links` array, generate
// default consecutive links by num order to preserve the old "balance all
// intersections in num-order along corridorDir" semantics. Returns true iff
// _snapshot was mutated, so the caller can decide whether to _persist.
//
// IMPORTANT: called only from _initSnapshot (page load) and saveProject (import),
// NOT from getSnapshot. Putting it on a hot read path would re-trigger on every
// render and clobber any explicit user empty-state. The empty-links check is the
// run-once guard: once links is populated, future loads skip this entirely.
function _migrateLinksIfNeeded() {
  const intersections = _snapshot.intersections ?? []
  const existing = _snapshot.links ?? []
  if (existing.length > 0) return false
  if (intersections.length < 2) return false

  // Sort by num so the corridor order is preserved regardless of insertion order
  const sorted = [...intersections].sort((a, b) => (a.num ?? 0) - (b.num ?? 0))

  // Direction: prefer balancing.corridorDir (already 'EB/WB' | 'NB/SB' form),
  // fall back to analysis.corridorDir ('NS'/'EW' short form), fall back EB/WB.
  const balDir = _snapshot.balancing?.corridorDir
  const anlDir = _snapshot.analysis?.corridorDir
  let direction = 'EB/WB'
  if (balDir === 'NB/SB' || balDir === 'EB/WB') direction = balDir
  else if (anlDir === 'NS') direction = 'NB/SB'
  else if (anlDir === 'EW') direction = 'EB/WB'

  const generated = []
  for (let i = 0; i < sorted.length - 1; i++) {
    generated.push({
      id: _newLinkId(),
      fromId: sorted[i].id,
      toId: sorted[i + 1].id,
      direction,
      mode: 'Full',
      landUseThreshold: null,
    })
  }
  _snapshot = { ..._snapshot, links: generated }
  return true
}

function _emit() {
  for (const listener of _listeners) listener()
}

function _persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(_snapshot))
}

// ── Reactive surface (useSyncExternalStore) ───────────────────────────────────
export function subscribe(listener) {
  _listeners.add(listener)
  return () => _listeners.delete(listener)
}

export function getSnapshot() {
  if (!_initialized) _initSnapshot()
  return _snapshot
}

// ── S1 project-meta helpers ───────────────────────────────────────────────────
export function getProjectMeta() {
  return getSnapshot().project ?? null
}

export function setProjectMeta(meta) {
  if (!_initialized) _initSnapshot()
  _snapshot = { ..._snapshot, project: meta }
  _persist()
  _emit()
}

// ── S2 intersections + corridor direction ─────────────────────────────────────
export function getIntersections() {
  return getSnapshot().intersections ?? []
}

export function setIntersections(list) {
  if (!_initialized) _initSnapshot()
  _snapshot = { ..._snapshot, intersections: list }
  _persist()
  _emit()
}

// Atomic reorder: caller passes intersection IDs in the desired visual order.
// All `num` fields are reassigned (1..N) and the whole list is written in one
// emit, so subscribers never observe transient duplicate or missing numbers.
export function reorderIntersections(orderedIds) {
  const current = getIntersections()
  const byId = new Map(current.map((it) => [it.id, it]))
  const reordered = []
  for (let i = 0; i < orderedIds.length; i++) {
    const it = byId.get(orderedIds[i])
    if (it) reordered.push({ ...it, num: i + 1 })
  }
  // Defensive: if the caller dropped or added IDs, fall back to a no-op.
  if (reordered.length !== current.length) return
  setIntersections(reordered)
}

// ── Links (corridor topology — Stage 1: data model only) ─────────────────────
// A link is a directed-balancing edge between two intersections.
// Shape:
//   { id: 'lnk_<uuid>', fromId, toId, direction: 'EB/WB'|'NB/SB',
//     mode: 'Full'|'Land Use'|'None', landUseThreshold: number|null }
// fromId/toId reference intersection.id (stable across drag-reorder), NOT num.
export function getLinks() {
  return getSnapshot().links ?? []
}

// Append a new link. Dedupe: if a link already connects the same pair in
// either direction (A→B or B→A), do not create a duplicate — return the
// existing link's id. Reject self-links (fromId === toId). Returns the new
// or existing link id, or null on invalid input.
export function addLink({ fromId, toId, direction, mode = 'Full', landUseThreshold = null }) {
  if (!_initialized) _initSnapshot()
  if (!fromId || !toId || fromId === toId) return null
  const cur = _snapshot.links ?? []
  const existing = cur.find(
    (l) => (l.fromId === fromId && l.toId === toId) ||
           (l.fromId === toId && l.toId === fromId)
  )
  if (existing) return existing.id
  const link = {
    id: _newLinkId(),
    fromId,
    toId,
    direction,
    mode,
    landUseThreshold,
  }
  _snapshot = { ..._snapshot, links: [...cur, link] }
  _persist()
  _emit()
  return link.id
}

export function removeLink(linkId) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.links ?? []
  const next = cur.filter((l) => l.id !== linkId)
  if (next.length === cur.length) return
  _snapshot = { ..._snapshot, links: next }
  _persist()
  _emit()
}

// Shallow-merge update. Typically used to flip direction or change balancing
// mode + threshold. id is immutable; passing id in `partial` is ignored
// (preserved by spread ordering).
export function updateLink(linkId, partial) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.links ?? []
  let changed = false
  const next = cur.map((l) => {
    if (l.id !== linkId) return l
    changed = true
    return { ...l, ...partial, id: l.id }
  })
  if (!changed) return
  _snapshot = { ..._snapshot, links: next }
  _persist()
  _emit()
}

// Bulk replace — for migration paths and future agent-suggested topology.
export function setLinks(linksArray) {
  if (!_initialized) _initSnapshot()
  _snapshot = { ..._snapshot, links: Array.isArray(linksArray) ? linksArray : [] }
  _persist()
  _emit()
}

export function getCorridorDir() {
  return getSnapshot().analysis?.corridorDir ?? null
}

export function setCorridorDir(dir) {
  if (!_initialized) _initSnapshot()
  const analysis = { ...(_snapshot.analysis ?? {}), corridorDir: dir }
  _snapshot = { ..._snapshot, analysis }
  _persist()
  _emit()
}

// ── S3 approach configuration ─────────────────────────────────────────────────
export function getApproaches(intersectionId) {
  const it = getIntersections().find((x) => x.id === intersectionId)
  return it?.approaches ?? null
}

export function setApproaches(intersectionId, approaches) {
  const list = getIntersections().map((it) =>
    it.id === intersectionId ? { ...it, approaches } : it
  )
  setIntersections(list)
}

// True iff every existing approach (exists !== false) has at least one lane.
export function isIntersectionConfigured(intersectionId) {
  const a = getApproaches(intersectionId)
  if (!a) return false
  for (const dir of ['EB', 'WB', 'NB', 'SB']) {
    const ap = a[dir]
    if (ap && ap.exists !== false) {
      if (!Array.isArray(ap.lanes) || ap.lanes.length < 1) return false
    }
  }
  return true
}

// ── S4 volumes ────────────────────────────────────────────────────────────────
export function getVolumes(intersectionId) {
  const it = getIntersections().find((x) => x.id === intersectionId)
  return it?.volumes ?? null
}

// Bulk replace one period's volumes (rare — used by tests / restores).
export function setVolumes(intersectionId, period, volumes) {
  const list = getIntersections().map((it) => {
    if (it.id !== intersectionId) return it
    return { ...it, volumes: { ...(it.volumes ?? {}), [period]: volumes } }
  })
  setIntersections(list)
}

// Single cell. value === null/'' → delete the cell. source = 'agent' | 'manual'.
export function setCellValue(intersectionId, period, movement, value, source) {
  const list = getIntersections().map((it) => {
    if (it.id !== intersectionId) return it
    const periodVols = { ...((it.volumes ?? {})[period] ?? {}) }
    if (value === null || value === '' || value === undefined) {
      delete periodVols[movement]
    } else {
      periodVols[movement] = { value, _source: source }
    }
    return { ...it, volumes: { ...(it.volumes ?? {}), [period]: periodVols } }
  })
  setIntersections(list)
}

export function setPhf(intersectionId, period, value) {
  const list = getIntersections().map((it) =>
    it.id === intersectionId ? { ...it, phf: { ...(it.phf ?? {}), [period]: value } } : it
  )
  setIntersections(list)
}

export function setHvPct(intersectionId, period, value) {
  const list = getIntersections().map((it) =>
    it.id === intersectionId ? { ...it, hvPct: { ...(it.hvPct ?? {}), [period]: value } } : it
  )
  setIntersections(list)
}

// Apply one agent-extracted intersection block (from the /api/extract response)
// to a project intersection. Wraps every numeric value as { value, _source: 'agent' }.
export function applyExtractedVolumes(intersectionId, payload) {
  const wrap = (raw) => {
    const out = {}
    if (!raw) return out
    for (const [mvt, val] of Object.entries(raw)) {
      if (val !== null && val !== undefined) {
        out[mvt] = { value: val, _source: 'agent' }
      }
    }
    return out
  }
  const list = getIntersections().map((it) => {
    if (it.id !== intersectionId) return it
    return {
      ...it,
      volumes: {
        AM: wrap(payload.volumes?.AM),
        PM: wrap(payload.volumes?.PM),
      },
      phf: payload.phf ?? it.phf ?? null,
      hvPct: payload.hv_pct ?? it.hvPct ?? null,
      vendorDetected: payload.vendorDetected ?? it.vendorDetected,
      sourceFile: payload.sourceFile ?? it.sourceFile,
      amPeakStart: payload.am_peak_start ?? it.amPeakStart,
      pmPeakStart: payload.pm_peak_start ?? it.pmPeakStart,
    }
  })
  setIntersections(list)
}

// ── S5 balancing settings ─────────────────────────────────────────────────────
export function getBalancing() {
  return getSnapshot().balancing ?? null
}

// Shallow-merge into state.balancing.
export function setBalancing(partial) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  _snapshot = { ..._snapshot, balancing: { ...cur, ...partial } }
  _persist()
  _emit()
}

// ── Stage 5: per-cell engineer overrides ──────────────────────────────────────
// Shape: balancing.overrides = { AM: {intNumStr: {movement: number}}, PM: {...} }
// Overrides are LOCAL — they replace the post-balance value for that cell in
// every downstream view (Link Conservation Table, Excel export, line diagrams)
// but do NOT trigger re-balancing or any cascade.
export function getOverrides() {
  return getSnapshot().balancing?.overrides ?? { AM: {}, PM: {} }
}

export function setOverride(period, intNum, movement, value) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  const overrides = { AM: {}, PM: {}, ...(cur.overrides ?? {}) }
  const periodMap = { ...(overrides[period] ?? {}) }
  const intMap = { ...(periodMap[String(intNum)] ?? {}) }
  intMap[movement] = value
  periodMap[String(intNum)] = intMap
  overrides[period] = periodMap
  _snapshot = { ..._snapshot, balancing: { ...cur, overrides } }
  _persist()
  _emit()
}

export function clearOverride(period, intNum, movement) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  const overrides = { AM: {}, PM: {}, ...(cur.overrides ?? {}) }
  const periodMap = { ...(overrides[period] ?? {}) }
  const intMap = { ...(periodMap[String(intNum)] ?? {}) }
  delete intMap[movement]
  if (Object.keys(intMap).length === 0) {
    delete periodMap[String(intNum)]
  } else {
    periodMap[String(intNum)] = intMap
  }
  overrides[period] = periodMap
  _snapshot = { ..._snapshot, balancing: { ...cur, overrides } }
  _persist()
  _emit()
}

export function clearAllOverrides() {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  _snapshot = { ..._snapshot, balancing: { ...cur, overrides: { AM: {}, PM: {} } } }
  _persist()
  _emit()
}

// Clamp a single movement at one intersection to its raw collected value.
// Convenience for the "Clamp all visible to raw" bulk action.
export function clampOverrideToRaw(period, intNum, movement, rawValue) {
  setOverride(period, intNum, movement, rawValue)
}

export function setLinkBalanceMode(linkId, mode, threshold) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  const linkBalanceModes = {
    ...(cur.linkBalanceModes ?? {}),
    [linkId]: { mode, threshold },
  }
  _snapshot = { ..._snapshot, balancing: { ...cur, linkBalanceModes } }
  _persist()
  _emit()
}

// Idempotent — fills in any missing fields with defaults; preserves user edits.
// Generates default linkBalanceModes for every consecutive S2-sorted intersection pair.
export function ensureBalancingDefaults() {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.balancing ?? {}
  const corridorDir =
    cur.corridorDir ??
    (_snapshot.analysis?.corridorDir === 'NS' ? 'NB/SB' : 'EB/WB')

  const intersections = _snapshot.intersections ?? []
  const defaultLinkModes = {}
  for (let i = 0; i < intersections.length - 1; i++) {
    const id = `${intersections[i].id}__${intersections[i + 1].id}`
    defaultLinkModes[id] = { mode: 'Full', threshold: 0 }
  }

  const merged = {
    enabled: cur.enabled ?? true,
    // Stage 4 / NCHRP rewrite: link disagreement resolution method.
    // 'larger' (default) keeps the higher of the two adjacent counts;
    // 'average' uses the mean. See S5 info modal for full guidance.
    // The old 'mode' field (conservative/furness) is no longer used — both
    // were variants of the same buggy link-by-link algorithm and have been
    // replaced by real NCHRP 255/765 per-intersection Fratar factoring.
    linkResolution: cur.linkResolution ?? 'larger',
    corridorDir,
    peakMode: cur.peakMode ?? 'Corridor',
    amWindow: cur.amWindow ?? { start: '07:00', end: '09:00' },
    pmWindow: cur.pmWindow ?? { start: '16:00', end: '18:00' },
    convergenceThreshold: cur.convergenceThreshold ?? 0.01,
    // Stage 4c: IPF default — converges via matrix stability on imbalanced
    // targets, which can take more iterations than the old residual-to-target
    // criterion. 500 is comfortable headroom for branching corridors.
    maxIterations: cur.maxIterations ?? 500,
    linkBalanceModes: { ...defaultLinkModes, ...(cur.linkBalanceModes ?? {}) },
  }

  if (JSON.stringify(merged) === JSON.stringify(cur)) return
  _snapshot = { ..._snapshot, balancing: merged }
  _persist()
  _emit()
}

// ── S6 analysis run + balanced volumes ────────────────────────────────────────
export function setBalancedVolumes(intersectionId, period, balanced) {
  const list = getIntersections().map((it) =>
    it.id === intersectionId
      ? { ...it, balanced: { ...(it.balanced ?? {}), [period]: balanced } }
      : it
  )
  setIntersections(list)
}

// Bulk: write one /balance response's `balanced.{AM,PM}` into every matching
// intersection by num. One write, one emit.
export function applyBalancedRun(balancedByPeriod) {
  const list = getIntersections().map((it) => {
    const merged = { ...(it.balanced ?? {}) }
    let touched = false
    for (const period of ['AM', 'PM']) {
      const periodData = balancedByPeriod?.[period]
      if (!periodData) continue
      const periodBalanced = periodData[String(it.num)]
      if (periodBalanced) {
        merged[period] = periodBalanced
        touched = true
      }
    }
    return touched ? { ...it, balanced: merged } : it
  })
  setIntersections(list)
}

export function setLastRun(runResult) {
  if (!_initialized) _initSnapshot()
  const analysis = { ...(_snapshot.analysis ?? {}), lastRun: runResult }
  _snapshot = { ..._snapshot, analysis }
  _persist()
  _emit()
}

export function getLastRun() {
  return getSnapshot().analysis?.lastRun ?? null
}

// ── S7 results view (period + viewMode persistence) ───────────────────────────
export function getResultsView() {
  return getSnapshot().results ?? null
}

export function setResultsView(partial) {
  if (!_initialized) _initSnapshot()
  const cur = _snapshot.results ?? {}
  _snapshot = { ..._snapshot, results: { ...cur, ...partial } }
  _persist()
  _emit()
}

// ── Original API (preserved) ──────────────────────────────────────────────────
export function loadProject() {
  const snap = getSnapshot()
  return snap && Object.keys(snap).length ? snap : null
}

export function saveProject(project) {
  _snapshot = project
  _initialized = true
  // If an imported project pre-dates the links model, migrate before persisting
  // so the on-disk shape stays consistent with what the store exposes.
  _migrateLinksIfNeeded()
  _persist()
  _emit()
}

export function clearProject() {
  _snapshot = {}
  _initialized = true
  localStorage.removeItem(STORAGE_KEY)
  _emit()
}

// TODO (later session): implement .demandiq.json download/upload via Blob + File API.
export function exportProjectFile() {
  throw new Error('exportProjectFile: not implemented yet')
}

export function importProjectFile() {
  throw new Error('importProjectFile: not implemented yet')
}
