import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Info } from 'lucide-react'

import { subscribe, getSnapshot, isExistingAnalysisDone } from '../store/projectStore'
import { buildPayload } from '../lib/diagramPayload'

import '../styles/forms.css'
import '../styles/forecasting.css'

const MOVEMENTS = ['NBL', 'NBT', 'NBR', 'SBL', 'SBT', 'SBR', 'EBL', 'EBT', 'EBR', 'WBL', 'WBT', 'WBR']
const DIRS = ['NB', 'SB', 'EB', 'WB']

async function fetchDiagram(payload) {
  const res = await fetch('/api/intersection-diagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* non-JSON */ }
    throw new Error(detail)
  }
  return res.json()
}

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const num = (v) => (v == null ? 0 : Math.round(v))

export default function F4_FutureResults() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const gateOpen = isExistingAnalysisDone()
  const fc = snap.forecasting ?? {}
  const results = fc.results ?? null
  const intersections = snap.intersections ?? []
  const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }

  const periods = results ? Object.keys(results) : []
  const [period, setPeriod] = useState(periods[0] ?? 'AM')
  const effPeriod = results && results[period] ? period : (periods[0] ?? 'AM')

  const numsWithResults = results?.[effPeriod]
    ? Object.keys(results[effPeriod].pass2?.balanced ?? {}).map(Number)
    : []
  const [activeNum, setActiveNum] = useState(numsWithResults[0] ?? null)
  const effActive = activeNum != null && numsWithResults.includes(activeNum)
    ? activeNum
    : (numsWithResults[0] ?? null)

  const [showProv, setShowProv] = useState(false)

  const [diagrams, setDiagrams] = useState(() => new Map())

  useEffect(() => {
    if (gateOpen) return
    const t = setTimeout(() => navigate('/results'), 1200)
    return () => clearTimeout(t)
  }, [gateOpen, navigate])

  const it = intersections.find((x) => x.num === effActive) ?? null
  const futureBal = results?.[effPeriod]?.pass2?.balanced?.[String(effActive)] ?? {}
  const existingBal = it?.balanced?.[effPeriod] ?? {}

  // Render existing + future diagrams for the active intersection/period. The
  // future diagram reuses the existing renderer with balanced volumes swapped
  // for the forecast — same locked engine, different input.
  useEffect(() => {
    if (!results || !it) return
    const ensure = (which, payload) => {
      const key = `${effActive}-${effPeriod}-${which}`
      if (diagrams.has(key)) return
      setDiagrams((prev) => new Map(prev).set(key, { status: 'loading' }))
      fetchDiagram(payload)
        .then((d) => setDiagrams((prev) => new Map(prev).set(key, { status: 'done', png: d.png_base64 })))
        .catch((e) => setDiagrams((prev) => new Map(prev).set(key, { status: 'error', error: e.message })))
    }
    const baseLabel = `${fc.baseYear || 'Base'} existing`
    const horizonLabel = `${fc.horizonYear || 'Horizon'} forecast`
    ensure('existing', buildPayload({ ...it, diagramNote: baseLabel }, effPeriod, 'balanced', overrides))
    ensure('future', buildPayload(
      { ...it, balanced: { ...it.balanced, [effPeriod]: futureBal }, diagramNote: horizonLabel },
      effPeriod, 'balanced', {}
    ))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effActive, effPeriod, results])

  if (!gateOpen) {
    return (
      <div className="di-page di-fc">
        <div className="di-eyebrow">Forecasting · Step 4</div>
        <h1 className="di-h1">Future results</h1>
        <p className="di-subtitle">Balance the existing volumes first. Redirecting…</p>
      </div>
    )
  }

  if (!results) {
    return (
      <div className="di-page di-fc">
        <div className="di-eyebrow">Forecasting · Step 4</div>
        <h1 className="di-h1">Future results</h1>
        <div className="di-fc-note">
          Run the forecast first.{' '}
          <button
            type="button"
            onClick={() => navigate('/forecast/run')}
            style={{ background: 'none', border: 'none', color: 'var(--signal-amber)', cursor: 'pointer', padding: 0, font: 'inherit', textDecoration: 'underline' }}
          >
            Go to Run Forecast →
          </button>
        </div>
      </div>
    )
  }

  const kRaw = fc.settings?.peakHourFactor
  const kValid = kRaw !== '' && kRaw != null && Number(kRaw) > 0
  const methodLabel = cap(kValid ? (fc.settings?.refineMethod || 'ratio') : 'ratio')
  const existImg = diagrams.get(`${effActive}-${effPeriod}-existing`)
  const futImg = diagrams.get(`${effActive}-${effPeriod}-future`)
  const refinement = (results[effPeriod].refinement ?? []).find((r) => r.intersection_num === effActive)

  const rows = MOVEMENTS
    .map((mv) => ({ mv, ex: num(existingBal[mv]), fu: num(futureBal[mv]) }))
    .filter((r) => r.ex > 0 || r.fu > 0)

  return (
    <div className="di-page di-fc" style={{ maxWidth: 960 }}>
      <div className="di-eyebrow">Forecasting · Step 4</div>
      <h1 className="di-h1" style={{ marginBottom: 4 }}>Future results</h1>
      <p className="di-subtitle" style={{ marginBottom: 12 }}>
        Forecast turning movements, balanced across the corridor, beside existing conditions.
      </p>

      {/* Methodology citation chip — persistent, click to expand provenance. */}
      <button type="button" className="di-fc-cite" onClick={() => setShowProv((v) => !v)}>
        <Info size={13} />
        <span>
          NCHRP 765 ({methodLabel}) · SANDAG · {fc.baseYear || 'base'} → {fc.horizonYear || 'horizon'}
          {' · '}K={kValid ? Number(kRaw) : '—'}
        </span>
        <span className="di-fc-cite__toggle">{showProv ? 'Hide provenance' : 'Show provenance'}</span>
      </button>

      {showProv && refinement && (
        <Provenance refinement={refinement} />
      )}

      {/* Controls */}
      <div className="di-fc-resctl">
        <div className="di-pill-group">
          {periods.map((p) => (
            <button
              key={p}
              type="button"
              className={`di-pill${p === effPeriod ? ' di-pill--selected' : ''}`}
              onClick={() => setPeriod(p)}
            >
              {p}
            </button>
          ))}
        </div>
        <div className="di-fc-chiprow">
          {numsWithResults.map((n) => (
            <button
              key={n}
              type="button"
              className={`di-fc-chip${n === effActive ? ' di-fc-chip--active' : ''}`}
              onClick={() => setActiveNum(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="di-fc-resgrid">
        {/* Future TMC table */}
        <div className="di-fc-tmc">
          <table>
            <thead>
              <tr>
                <th>Move</th>
                <th>Existing</th>
                <th>Future</th>
                <th>Δ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const d = r.fu - r.ex
                return (
                  <tr key={r.mv}>
                    <td className="di-fc-tmc__mv">{r.mv}</td>
                    <td>{r.ex}</td>
                    <td className="di-fc-tmc__fut">{r.fu}</td>
                    <td className="di-fc-tmc__d">{d > 0 ? `+${d}` : d}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Comparison diagrams */}
        <div className="di-fc-diagrams">
          <DiagramFig label={`${fc.baseYear || 'Base'} existing`} entry={existImg} />
          <DiagramFig label={`${fc.horizonYear || 'Horizon'} forecast`} entry={futImg} />
        </div>
      </div>

      <div className="di-actions">
        <button
          type="button"
          className="di-btn-amber"
          onClick={() => navigate('/export')}
          title="Export the workbook + diagrams (existing + future)"
        >
          Continue to export →
        </button>
      </div>
    </div>
  )
}

function DiagramFig({ label, entry }) {
  return (
    <figure className="di-fc-fig">
      <figcaption>{label}</figcaption>
      {!entry || entry.status === 'loading' ? (
        <div className="di-fc-fig__ph"><Loader2 size={18} className="di-spin" /></div>
      ) : entry.status === 'error' ? (
        <div className="di-fc-fig__ph di-fc-fig__ph--err">{entry.error}</div>
      ) : (
        <img src={`data:image/png;base64,${entry.png}`} alt={label} />
      )}
    </figure>
  )
}

function Provenance({ refinement }) {
  const fmt = (sub) => {
    if (!sub) return null
    if (sub.status === 'held-flat') {
      return `held flat at ${num(sub.count_base)} (model base 0)`
    }
    const g = sub.growth_factor != null ? sub.growth_factor.toFixed(2) : '—'
    return `count ${num(sub.count_base)} × (Mf ${num(sub.model_future)} / Mb ${num(sub.model_base)}) = ${num(sub.refined)}  [${sub.method}, ×${g}]`
  }
  return (
    <div className="di-fc-prov">
      <div className="di-fc-summary" style={{ marginBottom: 6 }}>
        Provenance — Int {refinement.intersection_num} ({refinement.period})
      </div>
      {DIRS.map((d) => {
        const leg = refinement.approaches?.[d]
        if (!leg || leg.status === 'absent') return null
        if (leg.status === 'pending') {
          return <div key={d} className="di-fc-prov__leg"><strong>{d}</strong> — pending ({leg.reason})</div>
        }
        const flags = [...(leg.inbound?.flags ?? []), ...(leg.outbound?.flags ?? [])]
        return (
          <div key={d} className="di-fc-prov__leg">
            <strong>{d}</strong>
            <div>in: {fmt(leg.inbound)}</div>
            <div>out: {fmt(leg.outbound)}</div>
            {flags.map((f, i) => (
              <div key={i} className="di-fc-prov__flag">⚠ {f.message}</div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
