import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, AlertTriangle, Download, ChevronDown, ChevronUp } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  getLinks,
  applyBalancedRun,
  setLastRun,
  setBalancing,
  clearAllOverrides,
  resolveLinkMode,
} from '../store/projectStore'
import { exportDiagnostics } from '../lib/diagnostics'
import { dropsSummary, formatIntRange, MAJOR_DROP_THRESHOLD_VEH } from '../lib/dropsSummary'
import { computeHeroState } from '../lib/heroState'
import { buildResolvedRows } from '../lib/resolvedTargets'

import '../styles/forms.css'
import '../styles/map.css'         // .di-banner, .di-btn-primary
import '../styles/balancing.css'   // segmented/toggle styles aren't used, but harmless
import '../styles/analysis.css'

// SUSPICIOUS_VOLUME_VEH + RECON_DELTA_NOTABLE_VEH live in lib/resolvedTargets.js
// alongside buildResolvedRows so the row-computation logic is unit-testable.

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
      lat: it.lat,
      lng: it.lng,
    })),
    unbalanced_volumes: { AM: stripVols('AM'), PM: stripVols('PM') },
    links: networkLinks,
    link_resolution_method: balancing.linkResolution ?? 'larger',
    max_iterations: balancing.maxIterations ?? 100,
    // S5 convergence threshold (veh) wired through. Previously hardcoded 0.5.
    tolerance: balancing.convergenceThreshold ?? 0.5,
  }
}

// ── Format helpers ──────────────────────────────────────────────────────
function formatAge(iso) {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  return day === 1 ? 'yesterday' : `${day}d ago`
}

function fmtWindow(w) {
  if (!w) return '—'
  return `${w.start ?? '—'}–${w.end ?? '—'}`
}

// Compare the run's snapshot config (lastRun.config) to current balancing.
// Returns array of changed field labels (empty when in sync).
function configDiff(runCfg, balancing) {
  if (!runCfg) return []
  const diffs = []
  const cur = {
    linkResolution: balancing.linkResolution ?? 'larger',
    peakMode: balancing.peakMode ?? 'Corridor',
    amWindow: balancing.amWindow ?? null,
    pmWindow: balancing.pmWindow ?? null,
    convergenceThreshold: balancing.convergenceThreshold ?? 0.5,
    maxIterations: balancing.maxIterations ?? 500,
    corridorDir: balancing.corridorDir ?? null,
  }
  if (cur.linkResolution !== runCfg.linkResolution) diffs.push('Link resolution')
  if (cur.peakMode !== runCfg.peakMode) diffs.push('Peak mode')
  if (cur.corridorDir !== runCfg.corridorDir) diffs.push('Direction')
  if (cur.maxIterations !== runCfg.maxIterations) diffs.push('Max iterations')
  if (Math.abs((cur.convergenceThreshold ?? 0) - (runCfg.convergenceThreshold ?? 0)) > 1e-9) {
    diffs.push('Tolerance')
  }
  const sameWin = (a, b) => (a?.start === b?.start && a?.end === b?.end)
  if (!sameWin(cur.amWindow, runCfg.amWindow)) diffs.push('AM window')
  if (!sameWin(cur.pmWindow, runCfg.pmWindow)) diffs.push('PM window')
  return diffs
}


// Tri-color tier for link conservation delta — green 0 / amber <5 / red ≥5.
function deltaTier(delta) {
  const a = Math.abs(delta ?? 0)
  if (a <= 0.5) return 'ok'
  if (a < 5) return 'warn'
  return 'fail'
}

export default function S6_RunAnalysis() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const balancing = snap.balancing || {}
  const lastRun = snap.analysis?.lastRun ?? null

  const needsConfig = intersections.length === 0 || !balancing.corridorDir || !hasAnyVolumes(intersections)

  // Tick once a minute so "5m ago" updates without manual refresh.
  const [, setNowTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setNowTick((n) => n + 1), 60_000)
    return () => clearInterval(id)
  }, [])

  // ── Empty / unconfigured guard ──────────────────────────────────────
  useEffect(() => {
    if (!needsConfig) return
    const t = setTimeout(() => navigate('/balancing'), 1000)
    return () => clearTimeout(t)
  }, [needsConfig, navigate])

  // ── Run state ───────────────────────────────────────────────────────
  const [status, setStatus] = useState(lastRun ? 'done' : 'idle')
  const [error, setError]   = useState(null)
  const [pendingRunReason, setPendingRunReason] = useState(null)
  // Method-swap intent: when set, the re-run swaps balancing.linkResolution
  // first. Captured here so the modal flow (if overrides exist) can carry it.
  const [pendingMethodSwap, setPendingMethodSwap] = useState(null)

  const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }
  const overrideCount =
    Object.values(overrides.AM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0) +
    Object.values(overrides.PM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0)

  const runWith = (methodSwap = null) => {
    if (overrideCount > 0) {
      setPendingMethodSwap(methodSwap)
      setPendingRunReason('rerun')
      return
    }
    handleRun(methodSwap)
  }

  const handleRun = async (methodSwap = null) => {
    setStatus('fetching')
    setError(null)
    try {
      // Apply method swap before building the payload so the snapshot is in sync.
      const effectiveBalancing = methodSwap
        ? { ...balancing, linkResolution: methodSwap }
        : balancing
      if (methodSwap) setBalancing({ linkResolution: methodSwap })

      const links = getLinks()
      const payload = buildPayload(intersections, effectiveBalancing, links)
      const res = await fetch('/api/balance-nchrp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* keep HTTP status */ }
        throw new Error(detail)
      }
      const data = await res.json()

      applyBalancedRun(data.balanced)
      setLastRun({
        timestamp: new Date().toISOString(),
        method: data.method,
        resolvedLinks: data.resolved_links ?? { AM: [], PM: [] },
        iterations: data.iterations ?? { AM: {}, PM: {} },
        intConverged: data.converged ?? { AM: {}, PM: {} },
        finalResidual: data.final_residual ?? { AM: {}, PM: {} },
        linkConservation: data.link_conservation ?? { AM: [], PM: [] },
        movementsReview: data.movements_review ?? { AM: [], PM: [] },
        qcFlags: data.qc_flags ?? [],
        config: {
          linkResolution: effectiveBalancing.linkResolution ?? 'larger',
          peakMode: effectiveBalancing.peakMode ?? 'Corridor',
          amWindow: effectiveBalancing.amWindow ?? null,
          pmWindow: effectiveBalancing.pmWindow ?? null,
          convergenceThreshold: effectiveBalancing.convergenceThreshold ?? 0.5,
          maxIterations: effectiveBalancing.maxIterations ?? 500,
          corridorDir: effectiveBalancing.corridorDir ?? null,
        },
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

  // Per-intersection stats from the run
  const amIters = lastRun?.iterations?.AM ?? {}
  const pmIters = lastRun?.iterations?.PM ?? {}
  const amConv  = lastRun?.intConverged?.AM ?? {}
  const pmConv  = lastRun?.intConverged?.PM ?? {}
  const amLinkConservation = lastRun?.linkConservation?.AM ?? []
  const pmLinkConservation = lastRun?.linkConservation?.PM ?? []
  const amResolved = lastRun?.resolvedLinks?.AM ?? []
  const pmResolved = lastRun?.resolvedLinks?.PM ?? []
  const movementsReview = lastRun?.movementsReview ?? { AM: [], PM: [] }
  const runMaxIter = lastRun?.config?.maxIterations ?? balancing.maxIterations ?? 500
  const runMethod = lastRun?.method ?? balancing.linkResolution ?? 'larger'
  const runTol = lastRun?.config?.convergenceThreshold ?? balancing.convergenceThreshold ?? 0.5
  const cfgDiffs = configDiff(lastRun?.config, balancing)
  const drops = dropsSummary(movementsReview)

  // Top-line: are all links conserving and all intersections converged?
  const total = intersections.length
  const amOk = intersections.filter((it) => amConv[String(it.num)]).length
  const pmOk = intersections.filter((it) => pmConv[String(it.num)]).length
  const lcRows = amLinkConservation.map((a) => {
    const p = pmLinkConservation.find(
      (r) => r.fromNum === a.fromNum && r.toNum === a.toNum && r.direction === a.direction,
    ) ?? null
    return { a, p }
  })
  const lcViolations = lcRows.filter(({ a, p }) =>
    Math.abs(a.delta) > 0.5 || (p && Math.abs(p.delta) > 0.5),
  ).length
  // F4: the worst single delta across AM + PM, used in the hero headline so
  // the engineer instantly sees the magnitude they're chasing.
  const lcLargestDelta = lcRows.reduce((max, { a, p }) => {
    const candidate = Math.max(Math.abs(a.delta ?? 0), Math.abs(p?.delta ?? 0))
    return candidate > max ? candidate : max
  }, 0)
  const lcTotal = lcRows.length
  const allConverged = amOk === total && pmOk === total
  const allConserved = lcViolations === 0
  const hasDrops = drops.AM.count > 0 || drops.PM.count > 0
  // F1: the project has corridor links configured but the run produced zero
  // resolved-link entries — the backend silently dropped them, almost always
  // because of an unrecognised direction value (axis 'NB/SB' is canonical;
  // anything else is rejected post-fix but legacy/imported runs may still
  // surface here). Without this gate, the hero would render
  // "0/0 links conserve ✓" in green on a corridor that never balanced.
  const linksConfigured = (snap.links || []).length
  const linkResolutionSkipped =
    hasResults && linksConfigured > 0 &&
    amResolved.length === 0 && pmResolved.length === 0
  const heroState = computeHeroState({
    hasResults, linkResolutionSkipped, allConverged, allConserved, hasDrops,
  })

  return (
    <div className="di-s6">
      <div className="di-s6__body">
        <div className="di-s6__inner">

          {/* Pre-run helper: short hint above the Run button so first-time users
              see the explainer that used to live under the run hint. */}
          {!hasResults && status === 'idle' && (
            <div className="di-s6-cfg di-s6-cfg--prerun">
              <h3 className="di-s6-cfg__title">Ready to run</h3>
              <p className="di-s6-cfg__hint">
                Calls /api/balance-nchrp — pure NCHRP 255/765 turning-movement
                refinement (per-intersection Fratar factoring against
                link-resolved targets). Under <em>Larger</em>, Furness scales
                mostly upward; under <em>Average</em>, individual movements can
                drop below raw counts (expected NCHRP behavior).
              </p>
              <button
                type="button"
                className="di-s6-run__btn"
                disabled={isRunning}
                onClick={() => runWith(null)}
              >
                {isRunning && <Loader2 size={18} className="di-spin" />}
                {isRunning ? 'Running…' : 'Run analysis'}
              </button>
            </div>
          )}

          {/* Error banner */}
          {status === 'error' && error && (
            <div className="di-s6-error">
              <span>{error}</span>
              <button type="button" className="di-s6-error__retry" onClick={() => handleRun()}>Retry</button>
            </div>
          )}

          {/* a. HERO RESULT STRIP */}
          {hasResults && (
            <HeroStrip
              state={heroState}
              isRunning={isRunning}
              allConverged={allConverged}
              allConserved={allConserved}
              amOk={amOk} pmOk={pmOk} total={total}
              lcViolations={lcViolations} lcTotal={lcTotal}
              lcLargestDelta={lcLargestDelta}
              method={runMethod}
              tolerance={runTol}
              ageLabel={formatAge(lastRun?.timestamp)}
              linkResolutionSkipped={linkResolutionSkipped}
              linksConfigured={linksConfigured}
            />
          )}

          {/* b. RUN METADATA */}
          {hasResults && (
            <RunMetadata
              lastRun={lastRun}
              balancing={balancing}
              cfgDiffs={cfgDiffs}
            />
          )}

          {/* c. DROPS SUMMARY BANNER (only if drops exist) */}
          {hasResults && hasDrops && (
            <DropsBanner drops={drops} onReview={() => navigate('/review-drops')} />
          )}

          {/* QC flags — only when there's something to see */}
          {hasResults && (lastRun?.qcFlags ?? []).length > 0 && (
            <QcFlagsSection flags={lastRun.qcFlags} />
          )}

          {/* d. RESOLVED LINK TARGETS */}
          {hasResults && (amResolved.length > 0 || pmResolved.length > 0) && (
            <ResolvedTargets
              am={amResolved}
              pm={pmResolved}
              intersections={intersections}
            />
          )}

          {/* e. LINK CONSERVATION */}
          {hasResults && (amLinkConservation.length > 0 || pmLinkConservation.length > 0) && (
            <LinkConservationTable rows={lcRows} />
          )}

          {/* f. PER-INTERSECTION CONVERGENCE */}
          {hasResults && (
            <IntersectionConvergenceList
              intersections={intersections}
              amIters={amIters}
              pmIters={pmIters}
              amConv={amConv}
              pmConv={pmConv}
              tol={runTol}
              maxIter={runMaxIter}
            />
          )}
        </div>
      </div>

      {/* g. ACTION BAR */}
      <footer className="di-s6__footer">
        {hasResults && (
          <>
            <button
              type="button"
              className="di-btn-ghost"
              disabled={isRunning}
              onClick={exportDiagnostics}
              title="Download a JSON dump of project state + last run for debugging"
            >
              <Download size={14} /> Export diagnostics
            </button>
            <button
              type="button"
              className="di-btn-secondary"
              disabled={isRunning}
              onClick={() => runWith(runMethod === 'larger' ? 'average' : 'larger')}
              title={`Re-run with ${runMethod === 'larger' ? 'Average' : 'Larger'} link resolution`}
            >
              {isRunning && <Loader2 size={14} className="di-spin" />}
              Re-run with {runMethod === 'larger' ? 'Average' : 'Larger'}
            </button>
            {cfgDiffs.length > 0 && (
              <button
                type="button"
                className="di-btn-secondary"
                disabled={isRunning}
                onClick={() => runWith(null)}
                title={`Re-run with current settings (${cfgDiffs.join(', ')} changed)`}
              >
                {isRunning && <Loader2 size={14} className="di-spin" />}
                Re-run with current settings
              </button>
            )}
            <div className="di-s6__footer-spacer" />
            <button
              type="button"
              className="di-btn-secondary"
              disabled={!hasResults || isRunning}
              onClick={() => navigate('/review-movements')}
            >
              Review movements →
            </button>
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
          </>
        )}
      </footer>

      {pendingRunReason && (
        <RerunOverridesModal
          count={overrideCount}
          onCancel={() => { setPendingRunReason(null); setPendingMethodSwap(null) }}
          onKeep={() => {
            const swap = pendingMethodSwap
            setPendingRunReason(null); setPendingMethodSwap(null)
            handleRun(swap)
          }}
          onDiscard={() => {
            const swap = pendingMethodSwap
            setPendingRunReason(null); setPendingMethodSwap(null)
            clearAllOverrides(); handleRun(swap)
          }}
        />
      )}
    </div>
  )
}

// ── HeroStrip ───────────────────────────────────────────────────────────
function HeroStrip({
  state, isRunning, allConverged, allConserved,
  amOk, pmOk, total, lcViolations, lcTotal, lcLargestDelta,
  method, tolerance, ageLabel,
  linkResolutionSkipped, linksConfigured,
}) {
  // F4: lead with link conservation (the real corridor-correctness signal).
  // Demote per-intersection IPF convergence to a quiet tertiary line below
  // the sub — it's a matrix-stability statement about each intersection
  // independently, not a "the corridor balanced" signal.
  const headline = (() => {
    if (isRunning) return 'Running balance…'
    if (linkResolutionSkipped) {
      // F1
      return `Link resolution skipped — ${linksConfigured} link${linksConfigured === 1 ? '' : 's'} configured, 0 resolved`
    }
    if (allConserved) {
      return `All ${lcTotal} links conserve ✓`
    }
    return `${lcViolations}/${lcTotal} link inconsistencies · largest ${lcLargestDelta.toFixed(1)} veh`
  })()
  const methodLabel = method === 'average' ? 'Average' : 'Larger'
  const subLine = linkResolutionSkipped
    ? 'Verify each link\'s corridor direction in S2 (axis form: EB/WB or NB/SB). The corridor balance did not engage; per-intersection IPF ran independently.'
    : `Method: ${methodLabel} · Tolerance: ${Number(tolerance).toFixed(2)} veh${ageLabel ? ` · Run ${ageLabel}` : ''}`
  const ipfMissed = (total - amOk) + (total - pmOk)
  const ipfLine = !linkResolutionSkipped && (
    allConverged
      ? `AM ${amOk}/${total} · PM ${pmOk}/${total} intersections IPF-stable`
      : `AM ${amOk}/${total} · PM ${pmOk}/${total} IPF-stable (${ipfMissed} hit max iter)`
  )
  return (
    <div className={`di-s6-hero2 di-s6-hero2--${state}`}>
      <div className="di-s6-hero2__head">{headline}</div>
      <div className="di-s6-hero2__sub">{subLine}</div>
      {ipfLine && <div className="di-s6-hero2__ipf">{ipfLine}</div>}
    </div>
  )
}

// ── RunMetadata ──────────────────────────────────────────────────────────
function RunMetadata({ lastRun, balancing, cfgDiffs }) {
  const [open, setOpen] = useState(true)
  const cfg = lastRun?.config ?? {}
  const linkModes = balancing.linkBalanceModes ?? {}
  const linkCount = Object.keys(linkModes).length
  const modeCounts = Object.values(linkModes).reduce(
    (acc, m) => ({ ...acc, [m.mode]: (acc[m.mode] ?? 0) + 1 }),
    { Full: 0, 'Land Use': 0, None: 0 },
  )
  return (
    <div className="di-s6-meta">
      <div className="di-s6-meta__head" onClick={() => setOpen((o) => !o)}>
        <span className="di-s6-meta__title">Run metadata</span>
        {cfgDiffs.length > 0 && (
          <span className="di-s6-meta__changed">
            <AlertTriangle size={11} /> Config changed since this run: {cfgDiffs.join(', ')}
          </span>
        )}
        <span className="di-s6-meta__chev">
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </div>
      {open && (
        <div className="di-s6-meta__grid">
          <CfgRow k="Method" v={cfg.linkResolution === 'average' ? 'Average' : 'Larger'} />
          <CfgRow k="Peak mode" v={cfg.peakMode === 'Independent' ? 'Independent' : 'Corridor (shared)'} />
          <CfgRow k="Direction" v={cfg.corridorDir ?? '—'} />
          <CfgRow k="AM window" v={fmtWindow(cfg.amWindow)} />
          <CfgRow k="PM window" v={fmtWindow(cfg.pmWindow)} />
          <CfgRow k="Tolerance" v={`${Number(cfg.convergenceThreshold ?? 0.5).toFixed(2)} veh`} />
          <CfgRow k="Max iterations" v={String(cfg.maxIterations ?? '—')} />
          <CfgRow k="Run at" v={lastRun?.timestamp ? new Date(lastRun.timestamp).toLocaleString() : '—'} />
          {linkCount > 0 && (
            <CfgRow
              k="Links"
              v={`${linkCount} (Full ${modeCounts.Full} · Land Use ${modeCounts['Land Use']} · None ${modeCounts.None})`}
            />
          )}
        </div>
      )}
    </div>
  )
}

// ── DropsBanner ──────────────────────────────────────────────────────────
// F5: split the per-period summary into major/minor buckets at
// MAJOR_DROP_THRESHOLD_VEH so the engineer's eye lands on severity, not a
// raw count. "5 drops > 40 veh (Int 4–6), 36 smaller. Largest -95 (Int 6 EBT)"
// reads as "five things to check" not "forty-one things to scroll through."
function DropsBanner({ drops, onReview }) {
  const line = (p) => {
    const d = drops[p]
    if (d.count === 0) return null
    const where = d.largest ? ` (Int ${d.largest.intNum} ${d.largest.mv})` : ''
    const largestVal = d.largest ? `${d.largest.value} veh${where}` : '—'
    const parts = [p + ':']
    if (d.major > 0) {
      const intRange = d.majorInts.length > 0 ? ` (${formatIntRange(d.majorInts)})` : ''
      parts.push(`${d.major} drop${d.major === 1 ? '' : 's'} ≥ ${MAJOR_DROP_THRESHOLD_VEH} veh${intRange}`)
      if (d.minor > 0) parts.push(`+ ${d.minor} smaller`)
    } else {
      parts.push(`${d.minor} drop${d.minor === 1 ? '' : 's'} below raw`)
    }
    parts.push(`· largest ${largestVal}`)
    return parts.join(' ')
  }
  return (
    <div className="di-s6-drops">
      <div className="di-s6-drops__body">
        <AlertTriangle size={14} className="di-s6-drops__icon" />
        <div className="di-s6-drops__lines">
          {drops.AM.count > 0 && <div>{line('AM')}</div>}
          {drops.PM.count > 0 && <div>{line('PM')}</div>}
        </div>
      </div>
      <button type="button" className="di-btn-primary di-btn-primary--sm" onClick={onReview}>
        Review in S7 →
      </button>
    </div>
  )
}

// ── ResolvedTargets ──────────────────────────────────────────────────────
function ResolvedTargets({ am, pm, intersections }) {
  const [open, setOpen] = useState(false)
  const idByNum = new Map(intersections.map((it) => [String(it.num), it.id]))

  // Effective mode lookup is now centralised in the store. Both directions
  // (a→b and b→a) + linkBalanceModes vs store.links fallback live there.
  const modeFor = (fromNum, toNum) => {
    const fromId = idByNum.get(String(fromNum))
    const toId = idByNum.get(String(toNum))
    if (!fromId || !toId) return '—'
    return resolveLinkMode(fromId, toId)
  }

  const rows = buildResolvedRows({ am, pm, getMode: modeFor })
  const suspiciousCount = rows.filter((r) => r.suspicious).length
  const smoothedCount = rows.filter((r) => r.smoothed).length

  return (
    <div className="di-s6-rt">
      <div className="di-s6-rt__head" onClick={() => setOpen((o) => !o)}>
        <span className="di-s6-rt__title">Resolved link targets</span>
        <span className="di-s6-rt__summary">
          {rows.length} link{rows.length === 1 ? '' : 's'}
          {suspiciousCount > 0 ? ` · ${suspiciousCount} suspicious` : ''}
          {smoothedCount > 0 ? ` · ${smoothedCount} reconciled raw counts` : ''}
          {' · values AM (PM)'}
        </span>
        <span className="di-s6-meta__chev">
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </div>
      {open && (
        <table className="di-s6-rt__table">
          <thead>
            <tr>
              <th>Link</th>
              <th>Dir</th>
              <th>Mode</th>
              <th style={{ textAlign: 'right' }}>Target volume</th>
              <th style={{ textAlign: 'right' }} title="|raw upstream − raw downstream| that the algorithm reconciled">
                Raw recon
              </th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ a, p, mode, suspicious, amRecon, pmRecon, smoothed }, i) => (
              <tr
                key={i}
                className={suspicious ? 'di-s6-rt__row--warn' : (smoothed ? 'di-s6-rt__row--smoothed' : '')}
              >
                <td>{a.fromNum} → {a.toNum}</td>
                <td>{a.direction}</td>
                <td>{mode}</td>
                <td style={{ textAlign: 'right' }}>
                  {Math.round(a.volume)} ({p ? Math.round(p.volume) : '—'}) veh
                </td>
                <td style={{ textAlign: 'right' }}>
                  {Math.round(amRecon)} ({p ? Math.round(pmRecon) : '—'}) veh
                </td>
                <td className="di-s6-rt__warn-cell">
                  {suspicious && (
                    <span title="Full-mode link with very low resolved volume — raw count likely missing or wrong">
                      ⚠ raw count?
                    </span>
                  )}
                  {!suspicious && smoothed && (
                    <span title="Raw upstream and downstream counts disagreed; algorithm picked one side (Larger) or averaged. Verify if the gap is real corridor demand or count error.">
                      ⚠ smoothed
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── QC flags section ─────────────────────────────────────────────────────
function QcFlagsSection({ flags }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="di-s6-meta">
      <div className="di-s6-meta__head" onClick={() => setOpen((o) => !o)}>
        <span className="di-s6-meta__title">QC flags</span>
        <span className="di-s6-rt__summary">
          {flags.length} flag{flags.length === 1 ? '' : 's'}
        </span>
        <span className="di-s6-meta__chev">
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </div>
      {open && (
        <ul className="di-s6-qc__list">
          {flags.map((f, i) => {
            const isFractional = f.check === 'FRACTIONAL-VOLUME'
            return (
              <li
                key={i}
                className={`di-s6-qc__item${isFractional ? ' di-s6-qc__item--fractional' : ''}`}
              >
                <span className={`di-s6-qc__chip${isFractional ? ' di-s6-qc__chip--fractional' : ''}`}>
                  {f.check}{f.period ? ` · ${f.period}` : ''}
                </span>
                <span className="di-s6-qc__msg">{f.message}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ── RerunOverridesModal ──────────────────────────────────────────────────
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
            <strong>Keep:</strong> overrides remain — they&apos;ll override whatever the new
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

function CfgRow({ k, v }) {
  return (
    <div className="di-s6-cfg__row">
      <span className="di-s6-cfg__k">{k}</span>
      <span className="di-s6-cfg__v">{v}</span>
    </div>
  )
}

// ── Per-intersection convergence list, with headroom bar ────────────────
function IntersectionConvergenceList({
  intersections,
  amIters, pmIters,
  amConv, pmConv,
  tol, maxIter,
}) {
  const sorted = [...intersections].sort((a, b) => a.num - b.num)
  const total = sorted.length
  const amOk = sorted.filter((it) => amConv[String(it.num)]).length
  const pmOk = sorted.filter((it) => pmConv[String(it.num)]).length

  const statusText = (am, pm) => {
    if (am && pm) return `both converged${tol != null ? ` at ${Number(tol).toFixed(2)} veh tol` : ''}`
    if (!am && !pm) return 'neither converged (max iter)'
    return `${am ? 'PM' : 'AM'} did not converge (max iter)`
  }

  return (
    <div className="di-s6-conv">
      <div className="di-s6-conv__head">
        <h3 className="di-s6-conv__title">Per-intersection convergence</h3>
        <span className="di-s6-conv__summary">AM {amOk}/{total} · PM {pmOk}/{total} converged · {maxIter} max iter</span>
      </div>
      <div className="di-s6-conv__list">
        {sorted.map((it) => {
          const n = String(it.num)
          const am = !!amConv[n]
          const pm = !!pmConv[n]
          const ok = am && pm
          const amI = amIters[n] ?? 0
          const pmI = pmIters[n] ?? 0
          const peakI = Math.max(amI, pmI)
          const pct = Math.min(100, Math.round((peakI / Math.max(1, maxIter)) * 100))
          return (
            <div key={it.id} className="di-s6-conv__row di-s6-conv__row--bar">
              <div className="di-s6-conv__name">
                <span className="di-s6-conv__num">{String(it.num).padStart(2, '0')}</span>
                <span className="di-s6-conv__label">{it.name}</span>
              </div>
              <div className="di-s6-conv__cell">
                <span className={`di-s6-conv__dot di-s6-conv__dot--${ok ? 'ok' : 'fail'}`} />
                <span className="di-s6-conv__detail">
                  {amI} ({pmI}) iter · {statusText(am, pm)}
                </span>
              </div>
              <div className="di-s6-conv__bar" title={`Peak ${peakI}/${maxIter} = ${pct}%`}>
                <div
                  className={`di-s6-conv__bar-fill di-s6-conv__bar-fill--${ok ? 'ok' : 'fail'}`}
                  style={{ width: `${pct}%` }}
                />
                <span className="di-s6-conv__bar-label">{pct}%</span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Link conservation table — Mode column, tri-color delta, sort by |delta| ─
function LinkConservationTable({ rows }) {
  const sorted = [...rows].sort((x, y) => {
    const xMax = Math.max(Math.abs(x.a.delta ?? 0), Math.abs(x.p?.delta ?? 0))
    const yMax = Math.max(Math.abs(y.a.delta ?? 0), Math.abs(y.p?.delta ?? 0))
    return yMax - xMax
  })
  const total = sorted.length
  const violations = sorted.filter(({ a, p }) =>
    Math.abs(a.delta) > 0.5 || (p && Math.abs(p.delta) > 0.5),
  ).length

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
            <th>Mode</th>
            <th style={{ textAlign: 'right' }}>Upstream outflow</th>
            <th style={{ textAlign: 'right' }}>Downstream inflow</th>
            <th style={{ textAlign: 'right' }}>Delta</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(({ a, p }, i) => {
            const amT = deltaTier(a.delta)
            const pmT = p ? deltaTier(p.delta) : 'ok'
            const worst = pmT === 'fail' || amT === 'fail' ? 'fail'
              : pmT === 'warn' || amT === 'warn' ? 'warn'
              : 'ok'
            return (
              <tr key={i} className={worst === 'ok' ? '' : 'di-s6-lc__row--warn'}>
                <td>{a.fromNum} → {a.toNum}</td>
                <td>{a.direction}</td>
                <td>{a.mode ?? p?.mode ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>{n0(a.upstream_outflow)} ({n0(p?.upstream_outflow)})</td>
                <td style={{ textAlign: 'right' }}>{n0(a.downstream_inflow)} ({n0(p?.downstream_inflow)})</td>
                <td
                  style={{ textAlign: 'right' }}
                  className={`di-s6-lc__delta--${worst}`}
                >
                  {nDelta(a.delta)} ({nDelta(p?.delta)})
                  {worst === 'ok' ? ' ✓' : ''}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
