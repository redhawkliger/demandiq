import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  subscribe,
  getSnapshot,
  setResultsView,
  setDiagramNote,
} from '../store/projectStore'
import DiagramCard from '../components/DiagramCard'
import ResultsMap from '../components/ResultsMap'
import { buildPayload } from '../lib/diagramPayload'

import '../styles/forms.css'
import '../styles/map.css'         // .di-modal, .di-banner, .di-btn-primary, .di-pin
import '../styles/balancing.css'   // .di-segmented
import '../styles/results.css'

const VIEW_MODES = [
  { value: 'combined',   label: 'Combined' },
  { value: 'balanced',   label: 'Balanced' },
  { value: 'unbalanced', label: 'Unbalanced' },
  { value: 'delta',      label: 'Delta' },
]
const PERIODS = [
  { value: 'AM', label: 'AM' },
  { value: 'PM', label: 'PM' },
]

function hasAnyBalanced(intersections) {
  for (const it of intersections) {
    if (it.balanced?.AM && Object.keys(it.balanced.AM).length > 0) return true
    if (it.balanced?.PM && Object.keys(it.balanced.PM).length > 0) return true
  }
  return false
}

const safeFilename = (s) => String(s ?? '').replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '')

// Diagram cache key. Per-intersection (id) + period + view + run timestamp +
// overrides + the diagram note — so any of those changing re-renders the PNG.
const diagramKey = (it, p, v, ts, ovKey) =>
  `${it.id}-${p}-${v}-${ts}-${ovKey}-${encodeURIComponent(it.diagramNote || '')}`

async function fetchDiagram(payload) {
  const res = await fetch('/api/intersection-diagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* body not JSON — keep HTTP-status detail */ }
    throw new Error(detail)
  }
  return await res.json()
}

export default function S7_Results() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const links = snap.links || []   // explicit corridor graph — same source S2 uses
  const lastRun = snap.analysis?.lastRun ?? null
  const period   = snap.results?.period   ?? 'AM'
  const viewMode = snap.results?.viewMode ?? 'combined'
  const timestamp = lastRun?.timestamp ?? ''
  // Stage 5: engineer overrides invalidate diagram cache (any override change
  // means a different rendered PNG). Hash-stringify for cache-key suffix.
  const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }
  const overridesKey = JSON.stringify(overrides)

  const needsRun = intersections.length === 0 || !hasAnyBalanced(intersections)

  useEffect(() => {
    if (!needsRun) return
    const t = setTimeout(() => navigate('/analysis'), 1000)
    return () => clearTimeout(t)
  }, [needsRun, navigate])

  // ── Diagram cache ──────────────────────────────────────────────────
  // Keyed by `${id}-${period}-${viewMode}-${timestamp}` so re-running S6
  // (which mints a new timestamp) invalidates everything cleanly.
  const [diagrams, setDiagrams] = useState(() => new Map())
  const diagramsRef = useRef(diagrams)
  // eslint-disable-next-line react-hooks/refs -- latest-value ref so stable callbacks read the current map without re-creation; idempotent
  diagramsRef.current = diagrams

  const updateEntry = (key, entry) => {
    setDiagrams((prev) => {
      const next = new Map(prev).set(key, entry)
      diagramsRef.current = next
      return next
    })
  }

  const triggerFetch = (it, p, v, ts, ovKey) => {
    // Cache key includes overridesKey + the per-intersection diagram note so
    // override edits AND annotation edits both invalidate stale PNGs.
    const key = diagramKey(it, p, v, ts, ovKey)
    updateEntry(key, { status: 'loading' })
    fetchDiagram(buildPayload(it, p, v, overrides))
      .then((data) => updateEntry(key, { status: 'done', png: data.png_base64 }))
      .catch((err) => updateEntry(key, { status: 'error', error: err.message }))
  }

  // Kick off any missing fetches. Fire-and-forget — each updates state
  // independently so cards fill in as their PNGs land.
  useEffect(() => {
    if (needsRun) return
    for (const it of intersections) {
      const key = diagramKey(it, period, viewMode, timestamp, overridesKey)
      if (diagramsRef.current.has(key)) continue
      triggerFetch(it, period, viewMode, timestamp, overridesKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intersections, period, viewMode, timestamp, overridesKey, needsRun])

  // ── Selection ──────────────────────────────────────────────────────
  const [selectedId, setSelectedId] = useState(null)

  // ── Empty redirect state ───────────────────────────────────────────
  if (needsRun) {
    return (
      <div className="di-s7 di-s7--center">
        <div className="di-s7-empty">
          <div className="di-banner">Run analysis first.</div>
          <p style={{ fontSize: 13, color: 'var(--text-tertiary)', margin: 0 }}>Redirecting…</p>
        </div>
      </div>
    )
  }

  const canContinue = Array.from(diagrams.values()).some((d) => d.status === 'done')

  // KPI figures for the strip below the toolbar. Both are null when the run
  // did not produce the underlying data, which the strip renders as an em dash
  // rather than a zero.
  const enteringTotal = intersections.reduce((sum, it) => {
    const bal = (it.balanced || {})[period]
    if (!bal) return sum
    return sum + Object.values(bal).reduce(
      (a, v) => a + (typeof v === 'number' ? v : 0), 0)
  }, 0) || null

  const convergedMap = (lastRun?.intConverged || {})[period]
  const convergedCount = convergedMap
    ? Object.values(convergedMap).filter(Boolean).length
    : null

  return (
    <div className="di-s7">
      <div className="di-s7__toolbar">
        <div className="di-s7__toolbar-l">
          <span className="di-s7__toolbar-label">Period</span>
          <Segmented
            options={PERIODS}
            value={period}
            onChange={(v) => setResultsView({ period: v })}
          />
          <span className="di-s7__toolbar-label" style={{ marginLeft: 16 }}>View</span>
          <Segmented
            options={VIEW_MODES}
            value={viewMode}
            onChange={(v) => setResultsView({ viewMode: v })}
          />
        </div>
        <div className="di-s7__toolbar-r">
          {timestamp && (
            <span className="di-s7__toolbar-meta">
              Last run: {new Date(timestamp).toLocaleString()}
            </span>
          )}
        </div>
      </div>

      {/* Signal Flow KPI strip — real figures only, read from the balanced
          result for the period on screen. Entering/ for a missing value rather
          than 0, so "not computed" never reads as "zero vehicles". */}
      <div className="sf-kpis di-s7__kpis">
        <div className="sf-kpi">
          <span className="sf-kpi__label">Intersections</span>
          <span className="sf-kpi__value">{intersections.length}</span>
        </div>
        <div className="sf-kpi">
          <span className="sf-kpi__label">{period} entering volume</span>
          <span className="sf-kpi__value">
            {enteringTotal === null ? '—' : enteringTotal.toLocaleString()}
            <small>veh/h</small>
          </span>
        </div>
        <div className="sf-kpi">
          <span className="sf-kpi__label">Converged</span>
          <span className="sf-kpi__value">
            {convergedCount === null ? '—' : `${convergedCount}/${intersections.length}`}
          </span>
        </div>
      </div>

      <div className="di-s7__body">
        <div className="di-s7__left">
          {intersections.map((it) => {
            const key = diagramKey(it, period, viewMode, timestamp, overridesKey)
            const filename = `Int_${String(it.num).padStart(2, '0')}_${safeFilename(it.name)}_${period}_${viewMode}.png`
            return (
              <DiagramCard
                key={it.id}
                intersection={it}
                diagram={diagrams.get(key)}
                isSelected={selectedId === it.id}
                onSelect={() => setSelectedId(it.id)}
                onRetry={() => triggerFetch(it, period, viewMode, timestamp, overridesKey)}
                filename={filename}
                note={it.diagramNote ?? ''}
                onNoteCommit={(v) => setDiagramNote(it.id, v)}
              />
            )
          })}
        </div>

        <div className="di-s7__right">
          <ResultsMap
            intersections={intersections}
            links={links}
            selectedId={selectedId}
            onSelect={setSelectedId}
            period={period}
            viewMode={viewMode}
          />
        </div>
      </div>

      <footer className="di-s7__footer">
        <button
          type="button"
          className="di-btn-primary"
          disabled={!canContinue}
          onClick={() => navigate('/export')}
        >
          Continue to export →
        </button>
      </footer>
    </div>
  )
}

// ── Inline segmented control (matches the visual from S5's .di-segmented) ──
function Segmented({ options, value, onChange }) {
  return (
    <div className="di-segmented">
      {options.map((opt) => {
        const on = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={on}
            className={`di-segmented__opt${on ? ' di-segmented__opt--on' : ''}`}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
