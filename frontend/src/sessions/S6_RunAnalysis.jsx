import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Check, AlertTriangle, ArrowUp, ArrowDown } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  applyBalancedRun,
  setLastRun,
} from '../store/projectStore'
import ConvergenceChart from '../components/ConvergenceChart'

import '../styles/forms.css'
import '../styles/map.css'         // .di-banner, .di-btn-primary
import '../styles/balancing.css'   // segmented/toggle styles aren't used, but harmless
import '../styles/analysis.css'

const TICK_MS = 40

function hasAnyVolumes(intersections) {
  for (const it of intersections) {
    for (const period of ['AM', 'PM']) {
      const v = it.volumes?.[period]
      if (v && Object.keys(v).length > 0) return true
    }
  }
  return false
}

// Build the /balance payload from the current store state.
function buildPayload(intersections, balancing) {
  const numByPin = new Map(intersections.map((it) => [it.id, it.num]))

  const balance_config = {}
  for (const [linkId, cfg] of Object.entries(balancing.linkBalanceModes ?? {})) {
    const [aId, bId] = linkId.split('__')
    const aNum = numByPin.get(aId)
    const bNum = numByPin.get(bId)
    if (aNum != null && bNum != null) {
      balance_config[`${aNum}-${bNum}`] = cfg
    }
  }

  const stripVols = (period) => {
    const out = {}
    for (const it of intersections) {
      const cells = it.volumes?.[period] ?? {}
      const stripped = {}
      for (const [mv, cell] of Object.entries(cells)) {
        if (cell?.value !== null && cell?.value !== undefined && cell?.value !== '') {
          stripped[mv] = cell.value
        }
      }
      if (Object.keys(stripped).length > 0) {
        out[String(it.num)] = stripped
      }
    }
    return out
  }

  const extracted_meta = {}
  for (const it of intersections) {
    if (it.phf || it.hvPct) {
      extracted_meta[String(it.num)] = {
        AM: { phf: it.phf?.AM, hv_pct: it.hvPct?.AM },
        PM: { phf: it.phf?.PM, hv_pct: it.hvPct?.PM },
      }
    }
  }

  return {
    intersections: intersections.map((it) => ({ num: it.num, name: it.name })),
    unbalanced_volumes: { AM: stripVols('AM'), PM: stripVols('PM') },
    extracted_meta,
    corridor_dir: balancing.corridorDir ?? 'EB/WB',
    convergence_threshold: balancing.convergenceThreshold ?? 0.01,
    max_iterations: balancing.maxIterations ?? 200,
    balance_config,
  }
}

const fmtPct = (v) => `${(v * 100).toFixed(2)}%`

export default function S6_RunAnalysis() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const balancing = snap.balancing || {}
  const lastRun = snap.analysis?.lastRun ?? null

  const needsConfig = intersections.length === 0 || !balancing.corridorDir || !hasAnyVolumes(intersections)

  // ── Empty / unconfigured guard ──────────────────────────────────────
  useEffect(() => {
    if (!needsConfig) return
    const t = setTimeout(() => navigate('/balancing'), 1000)
    return () => clearTimeout(t)
  }, [needsConfig, navigate])

  // ── Run / animation state ───────────────────────────────────────────
  // 'idle' | 'fetching' | 'animating' | 'done' | 'error'
  const [status, setStatus]   = useState(lastRun ? 'done' : 'idle')
  const [error, setError]     = useState(null)
  const [amIter, setAmIter]   = useState(lastRun ? lastRun.convergence?.AM?.log?.length ?? 0 : 0)
  const [pmIter, setPmIter]   = useState(lastRun ? lastRun.convergence?.PM?.log?.length ?? 0 : 0)

  // Animation: tick both periods in parallel until both reach their final iter
  useEffect(() => {
    if (status !== 'animating') return
    const amLen = lastRun?.convergence?.AM?.log?.length ?? 0
    const pmLen = lastRun?.convergence?.PM?.log?.length ?? 0
    const total = Math.max(amLen, pmLen)
    if (total === 0) {
      setStatus('done')
      return
    }
    let i = 0
    const id = setInterval(() => {
      i += 1
      setAmIter(Math.min(i, amLen))
      setPmIter(Math.min(i, pmLen))
      if (i >= total) {
        clearInterval(id)
        setStatus('done')
      }
    }, TICK_MS)
    return () => clearInterval(id)
  }, [status, lastRun])

  const handleRun = async () => {
    setStatus('fetching')
    setError(null)
    setAmIter(0)
    setPmIter(0)
    try {
      const payload = buildPayload(intersections, balancing)
      const res = await fetch('/api/balance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch {}
        throw new Error(detail)
      }
      const data = await res.json()

      // Persist immediately — animation is purely visual over store data.
      applyBalancedRun(data.balanced)
      setLastRun({
        timestamp: new Date().toISOString(),
        convergence: data.convergence,
        qcFlags: data.qc_flags ?? [],
        adjustments: data.adjustments ?? { AM: [], PM: [] },
      })
      setStatus('animating')
    } catch (err) {
      setError(`${err.message}. If the backend is down, restart: cd backend && python3.12 app.py`)
      setStatus('error')
    }
  }

  if (needsConfig) {
    return (
      <div className="di-s6 di-s6--center">
        <div className="di-s6-empty">
          <div className="di-banner">Configure balancing first.</div>
          <p style={{ fontSize: 13, color: 'var(--text-tertiary)', margin: 0 }}>Redirecting…</p>
        </div>
      </div>
    )
  }

  const hasResults = lastRun !== null
  const isRunning  = status === 'fetching' || status === 'animating'

  // ── Pulled out for readability ──────────────────────────────────────
  const threshold = balancing.convergenceThreshold ?? 0.01
  const amLog = lastRun?.convergence?.AM?.log ?? []
  const pmLog = lastRun?.convergence?.PM?.log ?? []

  // Mode breakdown for the config card
  const linkModes = balancing.linkBalanceModes ?? {}
  const linkCount = Object.keys(linkModes).length
  const modeCounts = Object.values(linkModes).reduce(
    (acc, m) => ({ ...acc, [m.mode]: (acc[m.mode] ?? 0) + 1 }),
    { Full: 0, 'Land Use': 0, None: 0 }
  )

  return (
    <div className="di-s6">
      <div className="di-s6__body">

        {/* ───── LEFT ───── */}
        <div className="di-s6__left">

          {/* Config summary */}
          <div className="di-s6-cfg">
            <h3 className="di-s6-cfg__title">Configuration</h3>
            <div className="di-s6-cfg__grid">
              <CfgRow k="Direction"      v={balancing.corridorDir ?? '—'} />
              <CfgRow k="Peak mode"      v={balancing.peakMode === 'Independent' ? 'Independent' : 'Corridor (shared)'} />
              <CfgRow k="AM window"      v={`${balancing.amWindow?.start ?? '—'} – ${balancing.amWindow?.end ?? '—'}`} />
              <CfgRow k="PM window"      v={`${balancing.pmWindow?.start ?? '—'} – ${balancing.pmWindow?.end ?? '—'}`} />
              <CfgRow k="Convergence"    v={`${(threshold * 100).toFixed(1)}%`} />
              <CfgRow k="Max iterations" v={String(balancing.maxIterations ?? 200)} />
              {linkCount > 0 && (
                <CfgRow
                  k="Links"
                  v={`${linkCount} (Full ${modeCounts.Full} · Land Use ${modeCounts['Land Use']} · None ${modeCounts.None})`}
                />
              )}
            </div>
          </div>

          {/* Error banner */}
          {status === 'error' && error && (
            <div className="di-s6-error">
              <span>{error}</span>
              <button type="button" className="di-s6-error__retry" onClick={handleRun}>Retry</button>
            </div>
          )}

          {/* Run button */}
          <div className="di-s6-run">
            <button
              type="button"
              className={`di-s6-run__btn${hasResults && status !== 'fetching' ? ' di-s6-run__btn--secondary' : ''}`}
              disabled={isRunning}
              onClick={handleRun}
            >
              {status === 'fetching' && <Loader2 size={18} className="di-spin" />}
              {status === 'fetching' ? 'Running…' : hasResults ? 'Re-run analysis' : 'Run analysis'}
            </button>
            {!hasResults && status === 'idle' && (
              <span className="di-s6-run__hint">
                Calls /api/balance with NCHRP 255 Furness/Fratar balancing.
                Typically converges in 5-15 iterations (~1-2 seconds).
              </span>
            )}
          </div>

          {/* Period cards (during/after run) */}
          {(isRunning || hasResults) && (
            <div className="di-s6-pcards">
              <PeriodCard period="AM" log={amLog} currentIter={amIter} threshold={threshold} done={status === 'done'} />
              <PeriodCard period="PM" log={pmLog} currentIter={pmIter} threshold={threshold} done={status === 'done'} />
            </div>
          )}

          {/* Live convergence chart */}
          {(isRunning || hasResults) && (amLog.length > 0 || pmLog.length > 0) && (
            <div className="di-s6-chart-wrap">
              <h3 className="di-s6-chart-wrap__title">Convergence</h3>
              <ConvergenceChart
                amLog={amLog}
                pmLog={pmLog}
                amIter={amIter}
                pmIter={pmIter}
                threshold={threshold}
              />
              <div className="di-s6-chart-legend">
                <span><span className="di-s6-chart-legend__sw" style={{ background: '#FFB627' }} /> AM</span>
                <span><span className="di-s6-chart-legend__sw" style={{ background: '#0A84FF' }} /> PM</span>
                <span><span className="di-s6-chart-legend__sw" style={{ background: '#34D399' }} /> threshold</span>
              </div>
            </div>
          )}
        </div>

        {/* ───── RIGHT (after run) ───── */}
        {hasResults && <ResultsPanel lastRun={lastRun} threshold={threshold} />}
      </div>

      <footer className="di-s6__footer">
        <button
          type="button"
          className="di-btn-primary"
          disabled={!hasResults || status !== 'done'}
          onClick={() => navigate('/results')}
        >
          Continue to results →
        </button>
      </footer>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────────────────

function CfgRow({ k, v }) {
  return (
    <div className="di-s6-cfg__row">
      <span className="di-s6-cfg__k">{k}</span>
      <span className="di-s6-cfg__v">{v}</span>
    </div>
  )
}

function PeriodCard({ period, log, currentIter, threshold, done }) {
  const total = log.length
  const cur = log[currentIter - 1]
  const gap = cur ? cur.max_relative_gap : 0
  const converged = total > 0 && log[total - 1].max_relative_gap <= threshold
  const isDoneShown = done && currentIter >= total

  let stateClass = ''
  if (isDoneShown && converged) stateClass = ' di-s6-pcard--converged'
  else if (isDoneShown && !converged) stateClass = ' di-s6-pcard--failed'

  const periodKey = period.toLowerCase()
  const pct = total > 0 ? (currentIter / total) * 100 : 0

  return (
    <div className={`di-s6-pcard di-s6-pcard--${periodKey}${stateClass}`}>
      <div className="di-s6-pcard__head">
        <span className="di-s6-pcard__dot" />
        <span className="di-s6-pcard__period">{period}</span>
      </div>
      <div className="di-s6-pcard__big">Iteration {currentIter} / {total || '?'}</div>
      <div className="di-s6-pcard__gap">{fmtPct(gap)}</div>
      <div className="di-s6-pcard__bar">
        <div className="di-s6-pcard__bar-fill" style={{ width: `${pct}%` }} />
      </div>
      {isDoneShown && (
        <div className="di-s6-pcard__status">
          {converged
            ? `Converged in ${total} iteration${total === 1 ? '' : 's'}`
            : `Did NOT converge — final gap ${fmtPct(gap)}`}
        </div>
      )}
    </div>
  )
}

function ResultsPanel({ lastRun, threshold }) {
  const amConv = lastRun.convergence?.AM ?? {}
  const pmConv = lastRun.convergence?.PM ?? {}
  const qcFlags = lastRun.qcFlags ?? []
  const adjustments = lastRun.adjustments ?? { AM: [], PM: [] }

  const amLog = amConv.log ?? []
  const pmLog = pmConv.log ?? []
  const tblRows = Math.min(15, Math.max(amLog.length, pmLog.length))

  const allAdj = [
    ...(adjustments.AM ?? []).map((a) => ({ ...a, period: 'AM' })),
    ...(adjustments.PM ?? []).map((a) => ({ ...a, period: 'PM' })),
  ]
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 20)

  return (
    <div className="di-s6__right">
      {/* Hero cards */}
      <div className="di-s6-hero">
        <HeroCard
          num={amConv.iterations_used ?? 0}
          label="AM iterations"
          ok={amConv.converged}
          okText="Converged ✓"
          warnText="Did not converge ⚠"
        />
        <HeroCard
          num={pmConv.iterations_used ?? 0}
          label="PM iterations"
          ok={pmConv.converged}
          okText="Converged ✓"
          warnText="Did not converge ⚠"
        />
        <HeroCard
          num={qcFlags.length}
          label="QC flags"
          ok={qcFlags.length === 0}
          okText="Clean"
          warnText={`${qcFlags.length} issue${qcFlags.length === 1 ? '' : 's'} found`}
        />
      </div>

      {/* QC flags panel (collapsible) */}
      <Collapsible title="QC flags" count={qcFlags.length}>
        {qcFlags.length === 0 ? (
          <div className="di-s6-qc__empty">
            <Check size={14} /> All QC checks passed
          </div>
        ) : (
          <ul className="di-s6-qc__list">
            {qcFlags.map((f, i) => (
              <li key={i} className="di-s6-qc__item">
                <span className="di-s6-qc__chip">{f.check}</span>
                <span className="di-s6-qc__msg">{f.message}</span>
              </li>
            ))}
          </ul>
        )}
      </Collapsible>

      {/* Convergence log */}
      <Collapsible title="Convergence log" count={`${amLog.length} / ${pmLog.length}`}>
        <table className="di-s6-tbl">
          <thead>
            <tr>
              <th>Iter</th>
              <th>AM gap</th>
              <th>PM gap</th>
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: tblRows }).map((_, i) => {
              const a = amLog[i]
              const p = pmLog[i]
              return (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td className={a && a.max_relative_gap <= threshold ? 'di-s6-tbl__ok' : ''}>
                    {a ? fmtPct(a.max_relative_gap) : '—'}
                  </td>
                  <td className={p && p.max_relative_gap <= threshold ? 'di-s6-tbl__ok' : ''}>
                    {p ? fmtPct(p.max_relative_gap) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Collapsible>

      {/* Adjustment log */}
      <Collapsible title="Top adjustments" count={allAdj.length}>
        {allAdj.length === 0 ? (
          <div className="di-s6-qc__empty">No adjustments — already balanced.</div>
        ) : (
          <table className="di-s6-tbl">
            <thead>
              <tr>
                <th>Int</th>
                <th>Period</th>
                <th>Movement</th>
                <th style={{ textAlign: 'right' }}>Delta</th>
              </tr>
            </thead>
            <tbody>
              {allAdj.map((a, i) => {
                const up = a.delta > 0
                return (
                  <tr key={i}>
                    <td>{String(a.intersection_num).padStart(2, '0')}</td>
                    <td>{a.period}</td>
                    <td>{a.movement}</td>
                    <td
                      style={{ textAlign: 'right' }}
                      className={up ? 'di-s6-tbl__cell--up' : 'di-s6-tbl__cell--down'}
                    >
                      {up ? <ArrowUp size={10} /> : <ArrowDown size={10} />}{' '}
                      {up ? '+' : ''}{a.delta.toFixed(1)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Collapsible>
    </div>
  )
}

function HeroCard({ num, label, ok, okText, warnText }) {
  return (
    <div className="di-s6-hero__card">
      <div className="di-s6-hero__num">{num}</div>
      <div className="di-s6-hero__label">{label}</div>
      <span className={`di-s6-hero__pill${ok ? '' : ' di-s6-hero__pill--warn'}`}>
        {ok ? okText : warnText}
      </span>
    </div>
  )
}

function Collapsible({ title, count, children }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="di-s6-section">
      <div className="di-s6-section__head" onClick={() => setOpen((o) => !o)}>
        <span className="di-s6-section__title">{title}</span>
        <span className="di-s6-section__count">{count}{open ? ' ⌃' : ' ⌄'}</span>
      </div>
      {open && children}
    </div>
  )
}
