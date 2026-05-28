import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  subscribe,
  getSnapshot,
  setResultsView,
} from '../store/projectStore'
import DiagramCard from '../components/DiagramCard'
import ResultsMap from '../components/ResultsMap'

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

// ── /balance result → /line-diagram payload helpers ──────────────────
function stripVols(period, intersection) {
  const out = {}
  const cells = intersection.volumes?.[period] ?? {}
  for (const [mv, cell] of Object.entries(cells)) {
    if (cell?.value != null) out[mv] = cell.value
  }
  return out
}

function activeLegs(intersection) {
  return ['EB', 'WB', 'NB', 'SB'].filter(
    (d) => intersection.approaches?.[d]?.exists !== false
  )
}

function parseStreets(intersection) {
  const parts = (intersection.name || '').split(' & ').map((s) => s.trim())
  const first = parts[0] || ''
  const second = parts[1] || ''
  if (intersection.mainDir === 'NB/SB') return { NS: first, EW: second }
  // Default + 'EB/WB' + diagonals: first street goes on EW axis.
  return { EW: first, NS: second }
}

function stoppedApproaches(intersection, legs) {
  const c = intersection.control
  if (c === 'All-way stop') return legs
  if (c === 'Two-way stop') {
    const minor = intersection.mainDir === 'NB/SB' ? ['EB', 'WB'] : ['NB', 'SB']
    return legs.filter((d) => minor.includes(d))
  }
  return []
}

function buildPayload(intersection, period, viewMode, overrides) {
  const legs = activeLegs(intersection)
  return {
    intersection: {
      num: intersection.num,
      name: intersection.name,
      active_legs: legs,
      control: intersection.control,
      streets: parseStreets(intersection),
      stopped_approaches: stoppedApproaches(intersection, legs),
    },
    u_vols: stripVols(period, intersection),
    b_vols: intersection.balanced?.[period] ?? {},
    // Stage 5: per-cell engineer overrides for this intersection's period.
    // Replaces b_vols values + adds "*" suffix to overridden cell labels.
    overrides: overrides?.[period]?.[String(intersection.num)] ?? {},
    view_mode: viewMode,
  }
}

const safeFilename = (s) => String(s ?? '').replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '')

async function fetchDiagram(payload) {
  const res = await fetch('/api/line-diagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch {}
    throw new Error(detail)
  }
  return await res.json()
}

export default function S7_Results() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
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
  diagramsRef.current = diagrams

  const updateEntry = (key, entry) => {
    setDiagrams((prev) => {
      const next = new Map(prev).set(key, entry)
      diagramsRef.current = next
      return next
    })
  }

  const triggerFetch = (it, p, v, ts, ovKey) => {
    // Cache key includes overridesKey so override edits invalidate stale PNGs
    const key = `${it.id}-${p}-${v}-${ts}-${ovKey}`
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
      const key = `${it.id}-${period}-${viewMode}-${timestamp}-${overridesKey}`
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

      <div className="di-s7__body">
        <div className="di-s7__left">
          {intersections.map((it) => {
            const key = `${it.id}-${period}-${viewMode}-${timestamp}-${overridesKey}`
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
              />
            )
          })}
        </div>

        <div className="di-s7__right">
          <ResultsMap
            intersections={intersections}
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
