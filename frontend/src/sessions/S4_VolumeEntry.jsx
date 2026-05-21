import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, AlertTriangle, X } from 'lucide-react'

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
const PERIODS = ['AM', 'PM']

function hasAnyApproaches(intersections) {
  return intersections.some((it) => it.approaches)
}

function hasAnyVolumes(intersections) {
  for (const it of intersections) {
    for (const period of PERIODS) {
      const v = it.volumes?.[period]
      if (v && Object.keys(v).length > 0) return true
    }
  }
  return false
}

// Returns the list of empty periods for one intersection, e.g. ['AM'] or ['AM','PM'].
function missingPeriods(it) {
  return PERIODS.filter((p) => {
    const v = it.volumes?.[p]
    return !v || Object.keys(v).length === 0
  })
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

  // Unified extraction-buffer state. Each entry:
  //   { id, payload, appliedTo: projectId|null, autoMatchFailed: bool, dismissed: bool }
  // payload = { name, volumes, phf, hv_pct, sourceFile, vendorDetected, ... }
  const [extracted, setExtracted] = useState([])

  // Banner-surfaced backend warnings (e.g. "PDF has 52 pages but cap is 40 …").
  // Each entry: { file: string, message: string }. Cleared at the start of every
  // extraction run AND on user dismiss — but never on unrelated re-renders.
  const [extractWarnings, setExtractWarnings] = useState([])

  const uploadRegionRef = useRef(null)

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
    setExtractWarnings([])   // new run wipes stale warnings; new ones will replace
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

      // Flatten agent intersections + collect backend warnings
      const agentInts = []
      const newWarnings = []
      for (const result of data.results || []) {
        for (const inter of result.intersections || []) {
          agentInts.push({
            ...inter,
            sourceFile: result.source_file,
            vendorDetected: result.vendor_detected,
          })
        }
        if (Array.isArray(result.warnings)) {
          for (const message of result.warnings) {
            newWarnings.push({
              file: result.source_file || '(unknown file)',
              message,
            })
          }
        }
      }
      if (newWarnings.length > 0) setExtractWarnings(newWarnings)

      // Match against the latest project intersections (avoid stale state)
      const projectInts = getIntersections()
      const { matches } = matchAgentToProject(agentInts, projectInts)

      // matches: { [projectId]: agentIdx } — build the inverse for O(1) lookup
      const projectIdByAgentIdx = new Map(
        Object.entries(matches).map(([pid, idx]) => [idx, pid])
      )

      // Apply auto-matches to the store
      for (const [projectId, agentIdx] of Object.entries(matches)) {
        applyExtractedVolumes(projectId, agentInts[agentIdx])
      }

      // Add every extracted block to the buffer, stamped with auto-match result
      const newExtracted = agentInts.map((ag, idx) => {
        const matchedPid = projectIdByAgentIdx.get(idx) ?? null
        return {
          id: newId(),
          payload: ag,
          appliedTo: matchedPid,
          autoMatchFailed: matchedPid == null,
          dismissed: false,
        }
      })
      setExtracted((prev) => [...prev, ...newExtracted])
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

  // Apply a buffered extraction to a chosen project intersection.
  const applyBufferedExtraction = (extractedId, projectId) => {
    if (!projectId) return
    const e = extracted.find((x) => x.id === extractedId)
    if (!e) return
    applyExtractedVolumes(projectId, e.payload)
    setExtracted((prev) =>
      prev.map((x) => (x.id === extractedId ? { ...x, appliedTo: projectId } : x))
    )
  }
  const dismissExtraction = (extractedId) =>
    setExtracted((prev) =>
      prev.map((x) => (x.id === extractedId ? { ...x, dismissed: true } : x))
    )

  const scrollToUpload = () => {
    uploadRegionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

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

  // ── Derived panels ────────────────────────────────────────────────────
  // Agent-side orphans (kept for backward compat with original UX).
  const orphanExtractions = extracted.filter(
    (e) => e.autoMatchFailed && !e.appliedTo && !e.dismissed
  )

  // Project-side gaps — per-period.
  const gaps = intersections
    .map((it) => ({ it, missing: missingPeriods(it) }))
    .filter(({ missing }) => missing.length > 0)

  // Extractions available for manual assignment (not yet applied, not dismissed).
  const availableExtractions = extracted.filter(
    (e) => !e.appliedTo && !e.dismissed
  )

  return (
    <div className="di-s4">
      {extractWarnings.length > 0 && (
        <div className="di-s4__warnings" role="alert">
          <div className="di-s4__warn-header">
            <AlertTriangle size={16} className="di-s4__warn-icon" />
            <span className="di-s4__warn-title">
              Some data was dropped during extraction
            </span>
            <button
              type="button"
              className="di-s4__warn-dismiss"
              aria-label="Dismiss warnings"
              onClick={() => setExtractWarnings([])}
            >
              <X size={14} />
            </button>
          </div>
          <ul className="di-s4__warn-list">
            {extractWarnings.map((w, i) => (
              <li key={i} className="di-s4__warn-row">
                <span className="di-s4__warn-file">{w.file}:</span> {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="di-s4__upload-region" ref={uploadRegionRef}>
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

        {gaps.length > 0 && (
          <div className="di-vol-needs">
            <div className="di-vol-needs__title">
              Needs volumes ({gaps.length})
            </div>
            <div className="di-vol-needs__sub">
              These project intersections have at least one empty period. Pick an
              extracted file to assign, or upload a new one.
            </div>
            <div className="di-vol-needs__list">
              {gaps.map(({ it, missing }) => (
                <NeedsVolumeRow
                  key={it.id}
                  intersection={it}
                  missing={missing}
                  available={availableExtractions}
                  onAssign={(extractedId) => applyBufferedExtraction(extractedId, it.id)}
                  onUpload={scrollToUpload}
                />
              ))}
            </div>
          </div>
        )}

        {orphanExtractions.length > 0 && (
          <div className="di-vol-unmatched">
            <div className="di-vol-unmatched__title">
              Unmatched extractions ({orphanExtractions.length})
            </div>
            <div className="di-vol-unmatched__sub">
              The agent extracted these intersections but couldn't auto-match them
              to a project intersection. Pick the correct one for each, or dismiss.
            </div>
            <div className="di-vol-unmatched__list">
              {orphanExtractions.map((e) => (
                <UnmatchedRow
                  key={e.id}
                  agent={e.payload}
                  intersections={intersections}
                  onApply={(pid) => applyBufferedExtraction(e.id, pid)}
                  onDismiss={() => dismissExtraction(e.id)}
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

// ── Needs-volume row: project-side gap with optional dropdown ──────────
function NeedsVolumeRow({ intersection, missing, available, onAssign, onUpload }) {
  const [pick, setPick] = useState('')
  const missingLabel = missing.join(' + ')
  const hasOptions = available.length > 0

  return (
    <div className="di-vol-needs__row">
      <div className="di-vol-needs__col-name">
        <div className="di-vol-needs__name">
          {String(intersection.num).padStart(2, '0')} — {intersection.name}
        </div>
        <div className="di-vol-needs__missing">missing {missingLabel}</div>
      </div>
      {hasOptions ? (
        <>
          <select
            className="di-vol-unm__select"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
          >
            <option value="">Assign extracted file…</option>
            {available.map((e) => (
              <option key={e.id} value={e.id}>
                {e.payload.name || '(no name)'} — {e.payload.sourceFile || 'unknown source'}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="di-vol-unm__apply"
            disabled={!pick}
            onClick={() => { if (pick) onAssign(pick) }}
          >
            Apply
          </button>
        </>
      ) : (
        <>
          <div className="di-vol-needs__empty">No extracted files available</div>
          <button
            type="button"
            className="di-vol-needs__upload"
            onClick={onUpload}
          >
            <Upload size={12} /> Upload
          </button>
        </>
      )}
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
