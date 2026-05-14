import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  subscribe,
  getSnapshot,
  getIntersections,
  applyExtractedVolumes,
} from '../store/projectStore'
import UploadBar from '../components/UploadBar'
import VolumeGrid from '../components/VolumeGrid'
import { matchAgentToProject } from '../lib/matching'

import '../styles/forms.css'
import '../styles/map.css'         // .di-modal*, .di-banner, .di-btn-secondary, .di-btn-primary
import '../styles/volumes.css'

const newId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `f-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

const STANDARD_DIRS = new Set(['EB/WB', 'NB/SB'])

function hasAnyApproaches(intersections) {
  return intersections.some((it) => it.approaches)
}

function hasAnyVolumes(intersections) {
  for (const it of intersections) {
    for (const period of ['AM', 'PM']) {
      const v = it.volumes?.[period]
      if (v && Object.keys(v).length > 0) return true
    }
  }
  return false
}

export default function S4_VolumeEntry() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []

  const skewed = intersections.filter(
    (it) => it.mainDir && !STANDARD_DIRS.has(it.mainDir)
  )

  // ── Empty / un-configured guard ─────────────────────────────────────
  const needsConfig = intersections.length === 0 || !hasAnyApproaches(intersections)
  useEffect(() => {
    if (!needsConfig) return
    const t = setTimeout(() => navigate('/approaches'), 1000)
    return () => clearTimeout(t)
  }, [needsConfig, navigate])

  // ── Files + extraction ──────────────────────────────────────────────
  const [files, setFiles] = useState([])
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState(null)
  const [unmatched, setUnmatched] = useState([])
  // unmatched = [{ name, volumes, phf, hv_pct, am_peak_start, pm_peak_start, sourceFile, vendorDetected }]

  const addFiles = (fileList) => {
    const next = Array.from(fileList).map((f) => ({
      id: newId(),
      file: f,
      name: f.name,
      status: 'pending',
    }))
    setFiles((prev) => [...prev, ...next])
  }
  const removeFile = (id) => setFiles((prev) => prev.filter((f) => f.id !== id))

  const runExtract = async () => {
    const pending = files.filter((f) => f.status === 'pending')
    if (pending.length === 0 || extracting) return

    setExtractError(null)
    setExtracting(true)
    setFiles((prev) =>
      prev.map((f) => (f.status === 'pending' ? { ...f, status: 'processing' } : f))
    )

    try {
      const fd = new FormData()
      pending.forEach((p) => fd.append('files', p.file))

      const res = await fetch('/api/extract', { method: 'POST', body: fd })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch {}
        throw new Error(detail)
      }
      const data = await res.json()

      // Per-file status from the response
      const errMap = new Map((data.errors || []).map((e) => [e.file, e.error]))
      setFiles((prev) =>
        prev.map((f) => {
          if (f.status !== 'processing') return f
          if (errMap.has(f.name)) return { ...f, status: 'error', error: errMap.get(f.name) }
          return { ...f, status: 'done' }
        })
      )

      // Flatten agent intersections
      const agentInts = []
      for (const result of data.results || []) {
        for (const inter of result.intersections || []) {
          agentInts.push({
            ...inter,
            sourceFile: result.source_file,
            vendorDetected: result.vendor_detected,
          })
        }
      }

      // Match against the latest project intersections (avoid stale state)
      const projectInts = getIntersections()
      const { matches, unmatched: unm } = matchAgentToProject(agentInts, projectInts)

      for (const [projectId, agentIdx] of Object.entries(matches)) {
        applyExtractedVolumes(projectId, agentInts[agentIdx])
      }
      setUnmatched((prev) => [...prev, ...unm])
    } catch (err) {
      setExtractError(
        `Extraction failed: ${err.message}. Make sure the backend is running at localhost:8000 (cd backend && python3.12 app.py).`
      )
      setFiles((prev) =>
        prev.map((f) =>
          f.status === 'processing' ? { ...f, status: 'error', error: err.message } : f
        )
      )
    } finally {
      setExtracting(false)
    }
  }

  const applyUnmatched = (idx, projectId) => {
    if (!projectId) return
    applyExtractedVolumes(projectId, unmatched[idx])
    setUnmatched((prev) => prev.filter((_, i) => i !== idx))
  }
  const dismissUnmatched = (idx) => setUnmatched((prev) => prev.filter((_, i) => i !== idx))

  if (needsConfig) {
    return (
      <div className="di-s4 di-s4--center">
        <div className="di-s4-empty">
          <div className="di-banner">Configure approaches first.</div>
          <p className="di-s3-empty__sub">Redirecting…</p>
        </div>
      </div>
    )
  }

  const canContinue = hasAnyVolumes(intersections)

  return (
    <div className="di-s4">
      <div className="di-s4__upload-region">
        <UploadBar
          files={files}
          extracting={extracting}
          extractError={extractError}
          onAdd={addFiles}
          onRemove={removeFile}
          onExtract={runExtract}
        />
      </div>

      {skewed.length > 0 && (
        <div className="di-s4__skew-notice">
          ⚠ {skewed.length} skewed intersection{skewed.length === 1 ? '' : 's'} (
          {skewed.map((s) => s.mainDir).join(', ')}). Verify direction mapping
          before relying on extracted volumes — the agent labels by EB/WB/NB/SB.
        </div>
      )}

      <div className="di-s4__grid-region">
        <VolumeGrid intersections={intersections} />

        {unmatched.length > 0 && (
          <div className="di-vol-unmatched">
            <div className="di-vol-unmatched__title">
              Unmatched extractions ({unmatched.length})
            </div>
            <div className="di-vol-unmatched__sub">
              The agent extracted these intersections but couldn't auto-match them
              to a project intersection. Pick the correct one for each, or dismiss.
            </div>
            <div className="di-vol-unmatched__list">
              {unmatched.map((u, idx) => (
                <UnmatchedRow
                  key={`${u.sourceFile}-${u.name}-${idx}`}
                  agent={u}
                  intersections={intersections}
                  onApply={(pid) => applyUnmatched(idx, pid)}
                  onDismiss={() => dismissUnmatched(idx)}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <footer className="di-s4__footer">
        {!canContinue && (
          <span className="di-s4__footer-hint">
            Add or extract volumes for at least one intersection
          </span>
        )}
        <button
          type="button"
          className="di-btn-primary"
          disabled={!canContinue}
          onClick={() => navigate('/balancing')}
        >
          Continue to balancing →
        </button>
      </footer>
    </div>
  )
}

// ── Single unmatched row with a per-row "selected target" choice ────────
function UnmatchedRow({ agent, intersections, onApply, onDismiss }) {
  const [target, setTarget] = useState('')
  return (
    <div className="di-vol-unm">
      <div>
        <div className="di-vol-unm__name">{agent.name || '(no name)'}</div>
        <div className="di-vol-unm__source">
          {agent.vendorDetected || 'Unknown vendor'} · {agent.sourceFile || ''}
        </div>
      </div>
      <select
        className="di-vol-unm__select"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
      >
        <option value="">Map to project intersection…</option>
        {intersections.map((it) => (
          <option key={it.id} value={it.id}>
            {String(it.num).padStart(2, '0')} — {it.name}
          </option>
        ))}
      </select>
      <div style={{ display: 'flex', gap: 6 }}>
        <button type="button" className="di-vol-unm__dismiss" onClick={onDismiss}>
          Dismiss
        </button>
        <button
          type="button"
          className="di-vol-unm__apply"
          disabled={!target}
          onClick={() => onApply(target)}
        >
          Apply
        </button>
      </div>
    </div>
  )
}
