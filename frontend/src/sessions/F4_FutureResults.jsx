import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Info } from 'lucide-react'

import { subscribe, getSnapshot, isExistingAnalysisDone, setForecasting } from '../store/projectStore'
import { buildPayload } from '../lib/diagramPayload'
import { runForecast } from '../lib/forecastRun'

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

  // Scenario demand-reduction factor (entered as a percent). The tool applies it
  // — it never supplies one. Persisted so it survives navigation.
  const [scenPct, setScenPct] = useState(() => fc.settings?.scenarioReductionPct ?? '')
  const [scenStatus, setScenStatus] = useState('idle')   // idle | loading | error
  const [scenError, setScenError] = useState(null)

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

  const scenario = results?.[effPeriod]?.vmt?.scenario ?? null

  // Re-run /forecast/run with (or without) the scenario factor. The factor scales
  // the forecast volumes server-side and corridor_vmt recomputes — same engine.
  const reRun = async (scenarioFactor) => {
    setScenStatus('loading')
    setScenError(null)
    try {
      const data = await runForecast({ snap, settings: fc.settings ?? {}, scenarioFactor })
      setForecasting({
        results: data,
        settings: { ...(fc.settings ?? {}), scenarioReductionPct: scenarioFactor == null ? '' : scenPct },
      })
      setScenStatus('idle')
    } catch (e) {
      setScenError(e.message)
      setScenStatus('error')
    }
  }
  const applyScenario = () => {
    const pct = Number(scenPct)
    if (!(scenPct !== '' && pct > 0 && pct < 100)) {
      setScenError('Enter a reduction strictly between 0 and 100%.')
      setScenStatus('error')
      return
    }
    reRun(pct / 100)
  }
  const clearScenario = () => { setScenPct(''); reRun(null) }
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

      {/* Corridor VMT — green existing / amber future, unit + basis on its face. */}
      <VmtPanel vmt={results[effPeriod]?.vmt} />

      {/* Scenario — engineer demand-reduction factor (applied, never generated). */}
      <ScenarioControl
        pct={scenPct}
        onPct={setScenPct}
        status={scenStatus}
        error={scenError}
        active={!!scenario}
        onApply={applyScenario}
        onClear={clearScenario}
      />
      {scenario && <ScenarioPanel scenario={scenario} />}

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

function VmtPanel({ vmt }) {
  const c = vmt?.corridor
  if (!c) return null
  const fmt = (n) => (n == null ? '—' : Math.round(n).toLocaleString())
  const sign = (n) => (n >= 0 ? '+' : '')
  const pct = c.existing_vmt > 0 ? Math.round((100 * c.delta) / c.existing_vmt) : null
  const hasDaily = c.daily_existing_vmt != null
  const star = c.daily_estimated ? ' *' : ''
  return (
    <div className="di-fc-vmt">
      <div className="di-fc-vmt__head">
        Corridor VMT <span className="di-fc-vmt__basis">peak hr</span>
      </div>
      <div className="di-fc-vmt__row">
        <span className="di-fc-vmt__ex">{fmt(c.existing_vmt)} <em>veh-mi</em></span>
        <span className="di-fc-vmt__arrow">→</span>
        <span className="di-fc-vmt__fu">{fmt(c.future_vmt)} <em>veh-mi · peak hr</em></span>
        <span className="di-fc-vmt__delta">
          {sign(c.delta)}{fmt(c.delta)}{pct != null ? ` · ${sign(pct)}${pct}%` : ''}
        </span>
      </div>
      {hasDaily && (
        <div className="di-fc-vmt__row di-fc-vmt__row--daily">
          <span className="di-fc-vmt__tag">daily{star}</span>
          <span className="di-fc-vmt__ex">{fmt(c.daily_existing_vmt)}</span>
          <span className="di-fc-vmt__arrow">→</span>
          <span className="di-fc-vmt__fu">{fmt(c.daily_future_vmt)} <em>veh-mi · daily{star}</em></span>
          <span className="di-fc-vmt__delta">{sign(c.daily_delta)}{fmt(c.daily_delta)}</span>
        </div>
      )}
      <div className="di-fc-vmt__chip">
        {c.corridor_length_mi} mi · {c.link_count} link{c.link_count === 1 ? '' : 's'} ·
        {' '}forecast volumes × model link length
        {c.gap_flag && <span className="di-fc-vmt__warn"> · ⚠ contains held segments</span>}
        {c.daily_estimated && (
          <span className="di-fc-vmt__warn"> · * daily estimated, expansion factor {c.expansion_factor}</span>
        )}
      </div>
    </div>
  )
}

function ScenarioControl({ pct, onPct, status, error, active, onApply, onClear }) {
  return (
    <div className="di-fc-scenctl">
      <label className="di-label" htmlFor="fc-scen">Demand-reduction scenario (optional)</label>
      <div className="di-fc-scenctl__row">
        <div className="di-fc-scenctl__inwrap">
          <input
            id="fc-scen"
            className="di-input"
            type="number"
            inputMode="decimal"
            min="0"
            max="100"
            step="0.5"
            placeholder="% reduction"
            value={pct}
            onChange={(e) => onPct(e.target.value)}
            style={{ maxWidth: 150 }}
          />
          <span className="di-fc-scenctl__unit">%</span>
        </div>
        <button
          type="button"
          className="di-fc-mini di-fc-mini--on"
          disabled={status === 'loading'}
          onClick={onApply}
        >
          {status === 'loading' ? 'Recomputing…' : active ? 'Update scenario' : 'Apply scenario'}
        </button>
        {active && (
          <button type="button" className="di-fc-mini" disabled={status === 'loading'} onClick={onClear}>
            Clear
          </button>
        )}
      </div>
      <p className="di-help" style={{ lineHeight: 1.5, marginTop: 6 }}>
        Your assumption — e.g. a CAPCOA measure or your own study. DemandIQ applies the
        factor to the forecast volumes and recomputes VMT; it never supplies or suggests
        a reduction.
      </p>
      {status === 'error' && error && (
        <div className="di-fc-banner di-fc-banner--error" role="alert" style={{ marginTop: 6 }}>
          {error}
        </div>
      )}
    </div>
  )
}

function ScenarioPanel({ scenario: s }) {
  const fmt = (n) => (n == null ? '—' : Math.round(n).toLocaleString())
  const sign = (n) => (n >= 0 ? '+' : '')
  const pct = s.pct != null ? Math.round(s.pct * 100) : null
  const star = s.daily_estimated ? ' *' : ''
  const hasDaily = s.daily_vmt != null
  const factorPct = Math.round(s.factor * 100)
  return (
    <div className="di-fc-vmt di-fc-vmt--scenario">
      <div className="di-fc-vmt__head">
        Scenario VMT — demand −{factorPct}%
        <span className="di-fc-vmt__basis">peak hr</span>
      </div>
      <div className="di-fc-vmt__row">
        <span className="di-fc-vmt__fu">{fmt(s.baseline_vmt)} <em>veh-mi · baseline</em></span>
        <span className="di-fc-vmt__arrow">→</span>
        <span className="di-fc-vmt__ex">{fmt(s.vmt)} <em>veh-mi · scenario</em></span>
        <span className="di-fc-vmt__delta">
          {sign(s.delta)}{fmt(s.delta)}{pct != null ? ` · ${sign(pct)}${pct}%` : ''}
        </span>
      </div>
      {hasDaily && (
        <div className="di-fc-vmt__row di-fc-vmt__row--daily">
          <span className="di-fc-vmt__tag">daily{star}</span>
          <span className="di-fc-vmt__fu">{fmt(s.daily_baseline_vmt)}</span>
          <span className="di-fc-vmt__arrow">→</span>
          <span className="di-fc-vmt__ex">{fmt(s.daily_vmt)} <em>veh-mi · scenario{star}</em></span>
          <span className="di-fc-vmt__delta">{sign(s.daily_delta)}{fmt(s.daily_delta)}</span>
        </div>
      )}
      <div className="di-fc-vmt__chip">
        engineer assumption — DemandIQ applies the {factorPct}% reduction, it does not generate it
        {s.daily_estimated && (
          <span className="di-fc-vmt__warn"> · * daily estimated, expansion factor {s.expansion_factor}</span>
        )}
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
