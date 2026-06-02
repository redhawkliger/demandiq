import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Play } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  getIntersections,
  getLinks,
  resolveLinkMode,
  setForecasting,
  isExistingAnalysisDone,
} from '../store/projectStore'

import '../styles/forms.css'
import '../styles/forecasting.css'

const DIRS = ['NB', 'SB', 'EB', 'WB']
const RESOLUTIONS = [
  { id: 'larger', label: 'Larger' },
  { id: 'average', label: 'Average' },
]
const METHODS = [
  { id: 'ratio', label: 'Ratio' },
  { id: 'difference', label: 'Difference' },
  { id: 'combined', label: 'Combined' },
]

function legNeedsReview(leg) {
  if (!leg) return false
  if (leg.status === 'ambiguous') return true
  if (leg.status === 'unmatched') {
    if (leg.decision === 'skip') return false
    if (leg.decision === 'manual') {
      const i = leg.manual?.inbound
      const o = leg.manual?.outbound
      return !(i !== '' && i != null && Number(i) >= 0 && o !== '' && o != null && Number(o) >= 0)
    }
    return true
  }
  return false
}

export default function F3_RunForecast() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const gateOpen = isExistingAnalysisDone()
  const fc = snap.forecasting ?? {}
  const matches = fc.matches ?? null
  const hasBase = !!fc.layers?.base
  const hasHorizon = !!fc.layers?.horizon
  const results = fc.results ?? null

  const [settings, setSettings] = useState(() => ({
    method: snap.balancing?.linkResolution ?? 'larger',
    refineMethod: 'ratio',
    peakHourFactor: '',
    ...(fc.settings ?? {}),
  }))
  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)

  useEffect(() => {
    if (gateOpen) return
    const t = setTimeout(() => navigate('/results'), 1200)
    return () => clearTimeout(t)
  }, [gateOpen, navigate])

  // Persist settings (debounced).
  const saveTimer = useRef(null)
  useEffect(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => setForecasting({ settings }), 400)
    return () => { if (saveTimer.current) clearTimeout(saveTimer.current) }
  }, [settings])

  if (!gateOpen) {
    return (
      <div className="di-page di-fc">
        <div className="di-eyebrow">Forecasting · Step 3</div>
        <h1 className="di-h1">Run forecast</h1>
        <p className="di-subtitle">Balance the existing volumes first. Redirecting…</p>
      </div>
    )
  }

  // Difference/Combined are only dimensionally valid with a peak-hour factor K.
  const kRaw = settings.peakHourFactor
  const kValid = kRaw !== '' && kRaw != null && Number(kRaw) > 0
  const refineMethod = kValid ? settings.refineMethod : 'ratio'

  const unresolved = (matches ?? []).reduce(
    (n, m) => n + DIRS.filter((d) => legNeedsReview(m.legs?.[d])).length,
    0
  )

  const update = (key, value) => setSettings((s) => ({ ...s, [key]: value }))

  const canRun = hasBase && hasHorizon && unresolved === 0 && (matches?.length ?? 0) > 0 && status !== 'loading'

  const run = async () => {
    setStatus('loading')
    setError(null)
    try {
      const intersections = getIntersections()
      const byId = new Map(intersections.map((it) => [it.id, it.num]))

      // Balanced existing TMCs → {AM:{num:{mv}}, PM:{...}} (the count C).
      const balanced_tmcs = { AM: {}, PM: {} }
      for (const it of intersections) {
        for (const p of ['AM', 'PM']) {
          const b = it.balanced?.[p]
          if (b && Object.keys(b).length) balanced_tmcs[p][it.num] = b
        }
      }

      // Corridor links by num, with their effective (S5) modes.
      const links = getLinks()
        .map((l) => ({
          fromNum: byId.get(l.fromId),
          toNum: byId.get(l.toId),
          direction: l.direction,
          mode: resolveLinkMode(l.fromId, l.toId),
        }))
        .filter((l) => l.fromNum != null && l.toNum != null)

      const coords = {}
      for (const it of intersections) coords[it.num] = { lat: it.lat, lng: it.lng }

      // Manual targets for unmatched legs the engineer entered by hand.
      const manual_targets = {}
      for (const m of matches) {
        for (const d of DIRS) {
          const leg = m.legs?.[d]
          if (leg?.status === 'unmatched' && leg.decision === 'manual' && leg.manual) {
            manual_targets[m.intersection_num] ??= {}
            manual_targets[m.intersection_num][d] = {
              inbound: Number(leg.manual.inbound),
              outbound: Number(leg.manual.outbound),
            }
          }
        }
      }

      const periods = snap.project?.analysisPeriods?.length
        ? snap.project.analysisPeriods
        : ['AM', 'PM']

      const res = await fetch('/api/forecast/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          layers: fc.layers,
          matches,
          balanced_tmcs,
          links,
          coords,
          periods,
          method: settings.method,
          refine_method: refineMethod,
          peak_hour_factor: kValid ? Number(kRaw) : null,
          manual_targets,
        }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* non-JSON */ }
        throw new Error(detail)
      }
      const data = await res.json()
      setForecasting({ results: data, settings })
      setStatus('idle')
    } catch (err) {
      setError(`${err.message}. Make sure the backend is running under the combined venv (cd backend && .venv-forecasting/bin/python app.py).`)
      setStatus('error')
    }
  }

  return (
    <div className="di-page di-fc">
      <div className="di-eyebrow">Forecasting · Step 3</div>
      <h1 className="di-h1">Run forecast</h1>
      <p className="di-subtitle">
        Grow the balanced base-year counts to the horizon year (NCHRP 255
        refinement → per-intersection IPF → corridor balancing).
      </p>

      {!matches ? (
        <div className="di-fc-note">
          Pull and match the SANDAG network first.{' '}
          <button
            type="button"
            onClick={() => navigate('/forecast/match')}
            style={{ background: 'none', border: 'none', color: 'var(--signal-amber)', cursor: 'pointer', padding: 0, font: 'inherit', textDecoration: 'underline' }}
          >
            Go to Network Match →
          </button>
        </div>
      ) : (
        <div className="di-form">
          {/* ── Link resolution ─────────────────────────────────────── */}
          <div className="di-field">
            <label className="di-label">Link disagreement resolution</label>
            <div className="di-pill-group">
              {RESOLUTIONS.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  aria-pressed={settings.method === r.id}
                  className={`di-pill${settings.method === r.id ? ' di-pill--selected' : ''}`}
                  onClick={() => update('method', r.id)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {/* ── Refinement method ───────────────────────────────────── */}
          <div className="di-field">
            <label className="di-label">Refinement method</label>
            <div className="di-pill-group">
              {METHODS.map((m) => {
                const locked = m.id !== 'ratio' && !kValid
                const selected = refineMethod === m.id
                return (
                  <button
                    key={m.id}
                    type="button"
                    disabled={locked}
                    aria-pressed={selected}
                    className={`di-pill${selected ? ' di-pill--selected' : ''}`}
                    style={locked ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
                    onClick={() => !locked && update('refineMethod', m.id)}
                  >
                    {m.label}
                  </button>
                )
              })}
            </div>
            <p className="di-help" style={{ lineHeight: 1.5 }}>
              Ratio is the default because SANDAG model flows are <strong>period</strong>{' '}
              volumes while DemandIQ counts are <strong>peak-hour</strong> — the ratio
              method is time-base invariant. Difference and Combined need a peak-hour
              factor K to be dimensionally valid; enter one below to unlock them.
            </p>
          </div>

          {/* ── Advanced: peak-hour factor ──────────────────────────── */}
          <div className="di-field">
            <label className="di-label" htmlFor="fc-k">Peak-hour factor K (optional)</label>
            <input
              id="fc-k"
              className="di-input"
              type="number"
              inputMode="decimal"
              step="0.01"
              placeholder="e.g. 0.40 — leave blank to use Ratio"
              value={settings.peakHourFactor}
              onChange={(e) => update('peakHourFactor', e.target.value)}
              style={{ maxWidth: 280 }}
            />
          </div>

          {!hasHorizon && (
            <div className="di-fc-note">
              A <strong>horizon network</strong> isn&apos;t loaded yet — Method 1 grows the
              count by the model&apos;s base→horizon change, so it needs both years.
              Add the {snap.forecasting?.horizonYear || '2030'} network in step 1 and re-pull
              in step 2. (You can dry-run today by tagging the same file as both base and
              horizon in step 1 — identity growth returns the existing counts.)
            </div>
          )}

          {unresolved > 0 && (
            <div className="di-fc-banner di-fc-banner--warn">
              {unresolved} leg{unresolved === 1 ? '' : 's'} still need a decision in{' '}
              <button
                type="button"
                onClick={() => navigate('/forecast/match')}
                style={{ background: 'none', border: 'none', color: 'var(--signal-amber)', cursor: 'pointer', padding: 0, font: 'inherit', textDecoration: 'underline' }}
              >
                Network Match
              </button>{' '}
              before running.
            </div>
          )}

          <div className="di-actions">
            <button type="button" className="di-btn-amber" disabled={!canRun} onClick={run}>
              {status === 'loading' ? (
                <><Loader2 size={15} className="di-spin" /> Running…</>
              ) : (
                <><Play size={15} /> Run forecast</>
              )}
            </button>
          </div>

          {status === 'error' && error && (
            <div className="di-fc-banner di-fc-banner--error" role="alert">{error}</div>
          )}

          {results && <RunDiagnostics results={results} />}
        </div>
      )}
    </div>
  )
}

function RunDiagnostics({ results }) {
  const navigate = useNavigate()
  return (
    <div className="di-fc-diag">
      <div className="di-fc-summary" style={{ marginBottom: 4 }}>Run complete</div>
      {Object.entries(results).map(([period, data]) => (
        <PeriodDiag key={period} period={period} data={data} />
      ))}
      <div className="di-actions">
        <button
          type="button"
          className="di-btn-amber"
          onClick={() => navigate('/forecast/results')}
        >
          Continue to Future Results →
        </button>
      </div>
    </div>
  )
}

function PeriodDiag({ period, data }) {
  const balanced = data.pass2?.balanced ?? {}
  const nums = Object.keys(balanced)
  const conv = data.pass2?.converged ?? {}
  const converged = nums.filter((n) => conv[n]).length
  const qc = data.pass2?.qc_flags?.length ?? 0

  const refFlags = []
  for (const r of data.refinement ?? []) {
    for (const d of ['NB', 'SB', 'EB', 'WB']) {
      const leg = r.approaches?.[d]
      if (!leg) continue
      for (const dir of ['inbound', 'outbound']) {
        for (const f of leg[dir]?.flags ?? []) {
          refFlags.push(`Int ${r.intersection_num} ${d} ${dir}: ${f.message}`)
        }
      }
    }
  }
  const residuals = nums.map((n) => data.pass1?.meta?.[n]?.residual ?? 0)
  const maxResid = residuals.length ? Math.max(...residuals) : 0

  return (
    <div className="di-fc-diag__period">
      <div className="di-fc-diag__head">
        <strong>{period}</strong>
        <span>{nums.length} intersection{nums.length === 1 ? '' : 's'}</span>
        <span className={converged === nums.length ? 'di-fc-gate--ok' : 'di-fc-gate--todo'}>
          {converged}/{nums.length} converged
        </span>
        <span>max Pass-1 residual {maxResid.toFixed(1)} veh</span>
        <span className={qc === 0 ? 'di-fc-gate--ok' : 'di-fc-gate--todo'}>
          {qc === 0 ? 'no QC flags' : `${qc} QC flag${qc === 1 ? '' : 's'}`}
        </span>
      </div>
      {refFlags.length > 0 && (
        <details className="di-fc-diag__flags">
          <summary>{refFlags.length} refinement flag{refFlags.length === 1 ? '' : 's'}</summary>
          <ul>{refFlags.map((f, i) => <li key={i}>{f}</li>)}</ul>
        </details>
      )}
    </div>
  )
}
