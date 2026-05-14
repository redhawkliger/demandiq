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
