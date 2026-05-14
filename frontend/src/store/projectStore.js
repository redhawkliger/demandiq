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
    corridorDir,
    peakMode: cur.peakMode ?? 'Corridor',
    amWindow: cur.amWindow ?? { start: '07:00', end: '09:00' },
    pmWindow: cur.pmWindow ?? { start: '16:00', end: '18:00' },
    convergenceThreshold: cur.convergenceThreshold ?? 0.01,
    maxIterations: cur.maxIterations ?? 200,
    linkBalanceModes: { ...defaultLinkModes, ...(cur.linkBalanceModes ?? {}) },
  }

  if (JSON.stringify(merged) === JSON.stringify(cur)) return
  _snapshot = { ..._snapshot, balancing: merged }
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
