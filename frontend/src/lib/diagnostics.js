// Stage 10.6 — one-click diagnostics dump for remote debugging.
//
// Builds a JSON snapshot of project state + last run + overrides so a user
// hitting a bug can send it over and we reproduce locally. Contains traffic
// count data + project config ONLY — never credentials/tokens/PII. The app
// stores auth via HTTP Basic (browser-managed), not localStorage, so there's
// nothing sensitive in the dump; we still strip auth-pattern keys defensively.

import { version as appVersion } from '../../package.json'
import { getSnapshot } from '../store/projectStore'

const STORAGE_KEY = 'demandiq:project'
const AUTH_KEY_RE = /(auth|token|password|secret|credential|session|apikey|api_key)/i

// Defensive: drop any top-level key whose name looks auth-related. The
// current project object has none, but this guards against future additions.
function stripAuthKeys(obj) {
  if (!obj || typeof obj !== 'object') return obj
  const out = {}
  for (const [k, v] of Object.entries(obj)) {
    if (AUTH_KEY_RE.test(k)) continue
    out[k] = v
  }
  return out
}

function safeName(s) {
  return String(s || 'project').replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '') || 'project'
}

function stamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`
}

// Build the diagnostics object (pure — exported for testing/inspection).
export function buildDiagnostics() {
  const snap = getSnapshot() || {}

  let project = null
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    project = raw ? stripAuthKeys(JSON.parse(raw)) : null
  } catch {
    project = null
  }

  return {
    exportedAt: new Date().toISOString(),
    appVersion,
    userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
    project,
    lastRun: snap.analysis?.lastRun ?? null,
    overrides: snap.balancing?.overrides ?? null,
  }
}

// Build + trigger a download of the diagnostics JSON.
export function exportDiagnostics() {
  const data = buildDiagnostics()
  const projectName = data.project?.project?.name || data.project?.name || 'project'
  const filename = `demandiq_diagnostics_${safeName(projectName)}_${stamp()}.json`

  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  return filename
}
