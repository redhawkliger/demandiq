// Stub project store. Persistence = browser localStorage (one project at a time).
// Download/upload of .demandiq.json is wired up in a later session.

const STORAGE_KEY = 'demandiq:project'

export function loadProject() {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function saveProject(project) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(project))
}

export function clearProject() {
  localStorage.removeItem(STORAGE_KEY)
}

// TODO (later session): implement .demandiq.json download/upload via Blob + File API.
export function exportProjectFile() {
  throw new Error('exportProjectFile: not implemented yet')
}

export function importProjectFile() {
  throw new Error('importProjectFile: not implemented yet')
}
