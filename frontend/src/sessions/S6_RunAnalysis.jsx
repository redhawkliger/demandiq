import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Check } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  getLinks,
  applyBalancedRun,
  setLastRun,
  clearAllOverrides,
} from '../store/projectStore'

import '../styles/forms.css'
import '../styles/map.css'         // .di-banner, .di-btn-primary
import '../styles/balancing.css'   // segmented/toggle styles aren't used, but harmless
import '../styles/analysis.css'

function hasAnyVolumes(intersections) {
  for (const it of intersections) {
    for (const period of ['AM', 'PM']) {
      const v = it.volumes?.[period]
      if (v && Object.keys(v).length > 0) return true
    }
  }
  return false
}

// Build the /balance-nchrp payload (Stage 4 — NCHRP 255/765 rewrite).
// Links are pulled from the Stage 1 store via getLinks() and mapped from
// intersection.id → intersection.num for the backend, which keys volumes by num.
// lat/lng is passed through so the backend can determine geographic ordering
// (which leg of each intersection a link sits on).
function buildPayload(intersections, balancing, links) {
  const numByPin = new Map(intersections.map((it) => [it.id, it.num]))

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

  // Convert store links (id-based) → endpoint links (num-based)
  const networkLinks = []
  for (const L of links) {
    const fromNum = numByPin.get(L.fromId)
    const toNum = numByPin.get(L.toId)
    if (fromNum == null || toNum == null) continue
    networkLinks.push({
      fromNum,
      toNum,
      direction: L.direction,
      mode: L.mode ?? 'Full',
    })
  }

  return {
    intersections: intersections.map((it) => ({
      num: it.num,
      name: it.name,
      lat: it.lat,                                // Stage 4: needed for geographic
      lng: it.lng,                                // leg ordering in balance_nchrp
    })),
    unbalanced_volumes: { AM: stripVols('AM'), PM: stripVols('PM') },
    links: networkLinks,
    link_resolution_method: balancing.linkResolution ?? 'larger',  // S5 setting
    max_iterations: balancing.maxIterations ?? 100,
    tolerance: 0.5,                                                // veh, per spec
  }
}

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

  // ── Run state ─────────────────────────────────────────────────────────
  // 'idle' | 'fetching' | 'done' | 'error'
  // Stage 4 NCHRP balances per-intersection so there's no global "iterate
  // animation" anymore — just show the final stats once /api/balance-nchrp
  // returns. The TICK_MS / amIter / pmIter machinery is gone.
  const [status, setStatus] = useState(lastRun ? 'done' : 'idle')
  const [error, setError]   = useState(null)
  // Stage 5: confirmation modal before re-running when engineer overrides exist
  const [pendingRunReason, setPendingRunReason] = useState(null)
  const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }
  const overrideCount =
    Object.values(overrides.AM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0) +
    Object.values(overrides.PM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0)

  const onClickRunButton = () => {
    // Stage 5: if overrides exist, prompt before re-running. They survive by
    // default — engineer can opt to discard.
    if (overrideCount > 0) {
      setPendingRunReason('rerun')
      return
    }
    handleRun()
  }

  const handleRun = async () => {
    setStatus('fetching')
    setError(null)
    try {
      const links = getLinks()
      const payload = buildPayload(intersections, balancing, links)
      const res = await fetch('/api/balance-nchrp', {
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
        method: data.method,                            // 'larger' | 'average'
        resolvedLinks: data.resolved_links ?? { AM: [], PM: [] },
        iterations: data.iterations ?? { AM: {}, PM: {} },
        intConverged: data.converged ?? { AM: {}, PM: {} },
        // Stage 4c.1: link conservation is the engineer-facing correctness check.
        linkConservation: data.link_conservation ?? { AM: [], PM: [] },
        // Stage 5: below-raw movements (no threshold) for the Review drops UI
        movementsReview: data.movements_review ?? { AM: [], PM: [] },
        qcFlags: data.qc_flags ?? [],
        // Stage 4 has no chains[] (algorithm is per-intersection, not chain-based)
        chains: [],
      })
      setStatus('done')
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
  const isRunning  = status === 'fetching'

  // Per-intersection stats from the new endpoint
  const amIters = lastRun?.iterations?.AM ?? {}
  const pmIters = lastRun?.iterations?.PM ?? {}
  const amConv  = lastRun?.intConverged?.AM ?? {}
  const pmConv  = lastRun?.intConverged?.PM ?? {}
  const amLinkConservation = lastRun?.linkConservation?.AM ?? []
  const pmLinkConservation = lastRun?.linkConservation?.PM ?? []
  const maxIter = balancing.maxIterations ?? 500

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
              <CfgRow k="Method"         v="NCHRP 255/765" />
              <CfgRow k="Link resolution" v={(balancing.linkResolution ?? 'larger') === 'larger' ? 'Larger value' : 'Average'} />
              <CfgRow k="Direction"      v={balancing.corridorDir ?? '—'} />
              <CfgRow k="Peak mode"      v={balancing.peakMode === 'Independent' ? 'Independent' : 'Corridor (shared)'} />
              <CfgRow k="AM window"      v={`${balancing.amWindow?.start ?? '—'} – ${balancing.amWindow?.end ?? '—'}`} />
              <CfgRow k="PM window"      v={`${balancing.pmWindow?.start ?? '—'} – ${balancing.pmWindow?.end ?? '—'}`} />
              <CfgRow k="Tolerance"      v="0.5 veh" />
              <CfgRow k="Max iterations" v={String(maxIter)} />
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
              onClick={onClickRunButton}
            >
              {status === 'fetching' && <Loader2 size={18} className="di-spin" />}
              {status === 'fetching' ? 'Running…' : hasResults ? 'Re-run analysis' : 'Run analysis'}
            </button>
            {!hasResults && status === 'idle' && (
              <span className="di-s6-run__hint">
                Calls /api/balance-nchrp — pure NCHRP 255/765 turning-movement
                refinement (per-intersection Fratar factoring against
                link-resolved targets). Under <em>Larger</em>, Furness scales
                mostly upward; under <em>Average</em>, individual movements
                can drop below raw counts (expected NCHRP behavior).
              </span>
            )}
          </div>

          {/* Per-intersection convergence summary */}
          {hasResults && (
            <IntersectionConvergenceList
              intersections={intersections}
              amIters={amIters}
              pmIters={pmIters}
              amConv={amConv}
              pmConv={pmConv}
              tol={balancing.convergenceThreshold ?? 0.01}
            />
          )}

          {/* Link conservation — the real engineering correctness signal */}
          {hasResults && (amLinkConservation.length > 0 || pmLinkConservation.length > 0) && (
            <LinkConservationTable
              am={amLinkConservation}
              pm={pmLinkConservation}
            />
          )}
        </div>

        {/* ───── RIGHT (after run) ───── */}
        {hasResults && <ResultsPanel lastRun={lastRun} intersections={intersections} />}
      </div>

      <footer className="di-s6__footer">
        <button
          type="button"
          className="di-btn-secondary"
          disabled={!hasResults || isRunning}
          onClick={() => navigate('/results')}
        >
          Skip to results →
        </button>
        <button
          type="button"
          className="di-btn-primary"
          disabled={!hasResults || isRunning}
          onClick={() => navigate('/review-drops')}
        >
          Continue to review drops →
        </button>
      </footer>

      {pendingRunReason && (
        <RerunOverridesModal
          count={overrideCount}
          onCancel={() => setPendingRunReason(null)}
          onKeep={() => { setPendingRunReason(null); handleRun() }}
          onDiscard={() => { setPendingRunReason(null); clearAllOverrides(); handleRun() }}
        />
      )}
    </div>
  )
}

// Stage 5: confirmation modal shown before a re-run when overrides exist.
function RerunOverridesModal({ count, onCancel, onKeep, onDiscard }) {
  return (
    <div className="di-modal-backdrop" onMouseDown={onCancel}>
      <div
        className="di-modal di-modal--info"
        role="dialog"
        aria-modal="true"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="di-modal__header">
          <h2 className="di-modal__title">Re-run with engineer overrides?</h2>
        </div>
        <div className="di-modal__body">
          <p>
            You have <strong>{count}</strong> active engineer override{count === 1 ? '' : 's'} across
            AM and PM. Re-running the balance will produce new balanced values; your
            existing overrides will be kept by default (and take precedence in
            downstream views).
          </p>
          <p style={{ marginTop: 8 }}>
            <strong>Keep:</strong> overrides remain — they'll override whatever the new
            run produces.<br />
            <strong>Discard:</strong> overrides are cleared first, then re-run.
          </p>
        </div>
        <div className="di-modal__footer">
          <button type="button" className="di-btn-secondary" onClick={onCancel}>Cancel</button>
          <button type="button" className="di-btn-secondary" onClick={onDiscard}>Discard overrides + re-run</button>
          <button type="button" className="di-btn-primary" onClick={onKeep}>Keep overrides + re-run</button>
        </div>
      </div>
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

// ── Per-intersection convergence list (Stage 4c.1 NCHRP IPF) ────────────
// Just shows iter count + converged status. Internal IPF residual is no
// longer surfaced — the real correctness signal is link conservation,
// shown in LinkConservationTable below.
function IntersectionConvergenceList({
  intersections,
  amIters, pmIters,
  amConv, pmConv,
  tol,
}) {
  const sorted = [...intersections].sort((a, b) => a.num - b.num)
  const total = sorted.length
  const amOk = sorted.filter((it) => amConv[String(it.num)]).length
  const pmOk = sorted.filter((it) => pmConv[String(it.num)]).length

  // Iterations shown as AM (PM); status collapsed to one line per intersection.
  const statusText = (am, pm) => {
    if (am && pm) return `both converged${tol != null ? ` at ${tol} veh tol` : ''}`
    if (!am && !pm) return 'neither converged (max iter)'
    return `${am ? 'PM' : 'AM'} did not converge (max iter)`
  }

  return (
    <div className="di-s6-conv">
      <div className="di-s6-conv__head">
        <h3 className="di-s6-conv__title">Per-intersection convergence</h3>
        <span className="di-s6-conv__summary">AM {amOk}/{total} · PM {pmOk}/{total} converged</span>
      </div>
      <div className="di-s6-conv__list">
        {sorted.map((it) => {
          const n = String(it.num)
          const am = !!amConv[n]
          const pm = !!pmConv[n]
          const ok = am && pm
          return (
            <div key={it.id} className="di-s6-conv__row di-s6-conv__row--inline">
              <div className="di-s6-conv__name">
                <span className="di-s6-conv__num">{String(it.num).padStart(2, '0')}</span>
                <span className="di-s6-conv__label">{it.name}</span>
              </div>
              <div className="di-s6-conv__cell">
                <span className={`di-s6-conv__dot di-s6-conv__dot--${ok ? 'ok' : 'fail'}`} />
                <span className="di-s6-conv__detail">
                  {amIters[n] ?? 0} ({pmIters[n] ?? 0}) iter · {statusText(am, pm)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Link conservation table (Stage 4c.1) ───────────────────────────────
// For every directed link, show upstream outflow vs downstream inflow on
// the balanced matrix. Delta should be near zero. Engineering correctness
// signal — non-zero deltas indicate the algorithm couldn't fully reconcile
// adjacent counts.
function LinkConservationTable({ am, pm }) {
  // No period toggle — both periods are shown inline as AM (PM) per column.
  const pmByKey = new Map(pm.map((r) => [`${r.fromNum}|${r.toNum}|${r.direction}`, r]))
  const rows = am.map((a) => ({ a, p: pmByKey.get(`${a.fromNum}|${a.toNum}|${a.direction}`) ?? null }))
  const total = rows.length
  const violations = rows.filter(({ a, p }) => Math.abs(a.delta) > 0.5 || (p && Math.abs(p.delta) > 0.5)).length

  const n0 = (v) => (v == null ? '—' : v.toFixed(0))
  const nDelta = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}`)

  return (
    <div className="di-s6-lc">
      <div className="di-s6-lc__head">
        <h3 className="di-s6-lc__title">Link conservation</h3>
        <span className="di-s6-lc__summary">
          {violations === 0
            ? `${total} links · all balanced ✓`
            : `${total - violations}/${total} balanced · ${violations} with delta > 0.5 veh`}
          {' · values AM (PM)'}
        </span>
      </div>
      <table className="di-s6-lc__table">
        <thead>
          <tr>
            <th>Link</th>
            <th>Dir</th>
            <th style={{ textAlign: 'right' }}>Upstream outflow</th>
            <th style={{ textAlign: 'right' }}>Downstream inflow</th>
            <th style={{ textAlign: 'right' }}>Delta</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ a, p }, i) => {
            const ok = Math.abs(a.delta) <= 0.5 && (!p || Math.abs(p.delta) <= 0.5)
            return (
              <tr key={i} className={ok ? '' : 'di-s6-lc__row--warn'}>
                <td>{a.fromNum} → {a.toNum}</td>
                <td>{a.direction}</td>
                <td style={{ textAlign: 'right' }}>{n0(a.upstream_outflow)} ({n0(p?.upstream_outflow)})</td>
                <td style={{ textAlign: 'right' }}>{n0(a.downstream_inflow)} ({n0(p?.downstream_inflow)})</td>
                <td
                  style={{ textAlign: 'right' }}
                  className={ok ? 'di-s6-lc__delta--ok' : 'di-s6-lc__delta--warn'}
                >
                  {nDelta(a.delta)} ({nDelta(p?.delta)})
                  {ok ? ' ✓' : ''}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ResultsPanel({ lastRun, intersections }) {
  const qcFlags = lastRun.qcFlags ?? []
  const amConv = lastRun.intConverged?.AM ?? {}
  const pmConv = lastRun.intConverged?.PM ?? {}
  const total = intersections.length
  const amOk = intersections.filter((it) => amConv[String(it.num)]).length
  const pmOk = intersections.filter((it) => pmConv[String(it.num)]).length

  const linkDeltaFlags = qcFlags.filter((f) => f.check === 'NCHRP-LINK-DELTA')

  return (
    <div className="di-s6__right">
      {/* Hero strip — convergence as a single AM · PM line, plus QC */}
      <div className="di-s6-hero">
        <div className="di-s6-hero__card di-s6-hero__card--wide">
          <div className="di-s6-hero__num di-s6-hero__num--inline">
            AM {amOk}/{total} · PM {pmOk}/{total}
          </div>
          <div className="di-s6-hero__label">intersections converged</div>
          <span className={`di-s6-hero__pill${amOk === total && pmOk === total ? '' : ' di-s6-hero__pill--warn'}`}>
            {amOk === total && pmOk === total
              ? 'All converged ✓'
              : `${(total - amOk) + (total - pmOk)} did not converge ⚠`}
          </span>
        </div>
        <HeroCard
          num={qcFlags.length}
          label="QC flags"
          ok={qcFlags.length === 0}
          okText="Clean"
          warnText={`${qcFlags.length} issue${qcFlags.length === 1 ? '' : 's'} found`}
        />
      </div>

      {/* QC flags panel (collapsible) — NCHRP-IMBAL + NCHRP-CONV only,
          NCHRP-FLOOR is gone (the floor was removed) */}
      <Collapsible title="QC flags" count={qcFlags.length}>
        {qcFlags.length === 0 ? (
          <div className="di-s6-qc__empty">
            <Check size={14} /> All QC checks passed
          </div>
        ) : (
          <ul className="di-s6-qc__list">
            {qcFlags.map((f, i) => {
              const isFractional = f.check === 'FRACTIONAL-VOLUME'
              return (
                <li
                  key={i}
                  className={`di-s6-qc__item${isFractional ? ' di-s6-qc__item--fractional' : ''}`}
                >
                  <span
                    className={`di-s6-qc__chip${isFractional ? ' di-s6-qc__chip--fractional' : ''}`}
                  >
                    {f.check}{f.period ? ` · ${f.period}` : ''}
                  </span>
                  <span className="di-s6-qc__msg">{f.message}</span>
                </li>
              )
            })}
          </ul>
        )}
      </Collapsible>

      {linkDeltaFlags.length > 0 && (
        <div className="di-s6-qc__note">
          {linkDeltaFlags.length} link{linkDeltaFlags.length === 1 ? '' : 's'} ended balancing
          with non-zero conservation delta (upstream outflow ≠ downstream inflow). See the
          Link conservation table for the per-link breakdown; flagged rows show the gap that
          IPF could not fully reconcile. This should be near-zero in a healthy run.
        </div>
      )}
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
