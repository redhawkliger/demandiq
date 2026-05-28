import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  setOverride,
  clearOverride,
  clearAllOverrides,
  clampOverrideToRaw,
} from '../store/projectStore'

import '../styles/forms.css'
import '../styles/map.css'         // .di-banner, .di-btn-primary, .di-btn-secondary
import '../styles/balancing.css'   // .di-segmented (still used for intersection chips, etc.)
import '../styles/analysis.css'    // .di-s6-lc* (LinkConservationTable styles)
import '../styles/review.css'

// Direction spec for client-side link conservation recompute (matches backend).
const DIR_OUTFLOW = {
  EB: ['EBT', 'SBL', 'NBR'], WB: ['WBT', 'NBL', 'SBR'],
  NB: ['NBT', 'EBL', 'WBR'], SB: ['SBT', 'WBL', 'EBR'],
}
const DIR_OUTFLOW_U = { EB: 'WBU', WB: 'EBU', NB: 'SBU', SB: 'NBU' }
const DIR_APPROACH = {
  EB: ['EBL', 'EBT', 'EBR'], WB: ['WBL', 'WBT', 'WBR'],
  NB: ['NBL', 'NBT', 'NBR'], SB: ['SBL', 'SBT', 'SBR'],
}
const PERIODS = ['AM', 'PM']

// Standard 12-movement display order (L/T/R per cardinal direction).
// Used by S7 to enumerate every movement at every intersection.
const MOVEMENTS = [
  'EBL', 'EBT', 'EBR',
  'WBL', 'WBT', 'WBR',
  'NBL', 'NBT', 'NBR',
  'SBL', 'SBT', 'SBR',
]

// A movement is "present" at an intersection iff its approach leg exists.
// (3-leg intersections lacking, say, the N approach won't render NBL/NBT/NBR.)
function movementPresentAt(intersection, mv) {
  const dir = mv.slice(0, 2)   // "EB", "WB", "NB", "SB"
  return intersection?.approaches?.[dir]?.exists !== false
}

function finalVolumeFor(period, intNum, mv, balanced, overrides) {
  const o = overrides?.[period]?.[String(intNum)]?.[mv]
  if (o != null) return o
  return balanced?.[period]?.[intNum]?.[mv] ?? 0
}

function computeLinkConservationFinal(period, links, balanced, overrides) {
  const out = []
  const sortedKeys = [...links].sort((a, b) => {
    if (a.fromNum !== b.fromNum) return a.fromNum - b.fromNum
    if (a.toNum !== b.toNum) return a.toNum - b.toNum
    return String(a.direction).localeCompare(String(b.direction))
  })
  for (const link of sortedKeys) {
    const { fromNum: u, toNum: d, direction, mode } = link
    const outflow = DIR_OUTFLOW[direction].reduce(
      (acc, k) => acc + finalVolumeFor(period, u, k, balanced, overrides), 0
    ) + finalVolumeFor(period, u, DIR_OUTFLOW_U[direction], balanced, overrides)
    const inflow = DIR_APPROACH[direction].reduce(
      (acc, k) => acc + finalVolumeFor(period, d, k, balanced, overrides), 0
    )
    out.push({
      fromNum: u, toNum: d, direction, mode,
      upstream_outflow: outflow,
      downstream_inflow: inflow,
      delta: inflow - outflow,
    })
  }
  return out
}

// Build unified rows: iterate EVERY intersection × the 12 standard movements
// (skipping movements at missing legs), emit AM + PM data for each. The
// movementsReview list from the backend is no longer used to gate inclusion
// — it's purely informational (used to count drops in the meta line).
function buildMergedRows(intersections, overrides) {
  const rows = []
  for (const it of intersections) {
    for (const movement of MOVEMENTS) {
      if (!movementPresentAt(it, movement)) continue
      const pair = {}
      for (const period of PERIODS) {
        const raw = it.volumes?.[period]?.[movement]
        const rawVal = typeof raw === 'object' && raw !== null
          ? Number(raw.value ?? 0)
          : Number(raw ?? 0)
        const balVal = Number(it.balanced?.[period]?.[movement] ?? 0)
        const override = overrides?.[period]?.[String(it.num)]?.[movement] ?? null
        pair[period] = {
          raw: rawVal,
          balanced: balVal,
          delta: balVal - rawVal,
          override,
        }
      }
      rows.push({ intNum: it.num, movement, ...pair })
    }
  }
  return rows
}

const isDropRow = (r) => r.AM.delta < 0 || r.PM.delta < 0

export default function S7_ReviewDrops() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const lastRun = snap.analysis?.lastRun ?? null
  const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }

  const needsRun = !lastRun || !lastRun.method
  useEffect(() => {
    if (!needsRun) return
    const t = setTimeout(() => navigate('/analysis'), 1000)
    return () => clearTimeout(t)
  }, [needsRun, navigate])

  const balancedByPeriod = useMemo(() => {
    const out = { AM: {}, PM: {} }
    for (const it of intersections) {
      out.AM[it.num] = it.balanced?.AM ?? {}
      out.PM[it.num] = it.balanced?.PM ?? {}
    }
    return out
  }, [intersections])

  // Intersection filter (chip multi-select)
  const [selectedInts, setSelectedInts] = useState(() => new Set(intersections.map((it) => it.num)))
  useEffect(() => {
    setSelectedInts(new Set(intersections.map((it) => it.num)))
  }, [intersections])

  // Sort state — default "delta" sorts by max(|am.delta|, |pm.delta|) ascending
  const [sortKey, setSortKey] = useState('delta')
  const [sortDir, setSortDir] = useState('asc')

  // Show-drops-only toggle (default off — show every movement).
  const [showDropsOnly, setShowDropsOnly] = useState(false)

  const allRows = useMemo(
    () => buildMergedRows(intersections, overrides),
    [intersections, overrides],
  )

  // Total drops (informational — does not gate row inclusion).
  const dropCount = useMemo(() => allRows.filter(isDropRow).length, [allRows])

  const visibleRows = useMemo(() => {
    const filtered = allRows
      .filter((r) => selectedInts.has(r.intNum))
      .filter((r) => (showDropsOnly ? isDropRow(r) : true))
    const cmpVal = (r, key) => {
      if (key === 'int') return r.intNum
      if (key === 'movement') return r.movement
      if (key === 'raw') return r.AM.raw
      if (key === 'balanced') return r.AM.balanced
      if (key === 'delta') return -Math.max(Math.abs(r.AM.delta), Math.abs(r.PM.delta))
      return 0
    }
    const sorted = [...filtered].sort((a, b) => {
      const ka = cmpVal(a, sortKey)
      const kb = cmpVal(b, sortKey)
      let cmp
      if (typeof ka === 'string') cmp = ka.localeCompare(kb)
      else cmp = ka - kb
      if (cmp !== 0) return sortDir === 'asc' ? cmp : -cmp
      // Tiebreak: PM column for raw/balanced; then intNum, then movement
      if (sortKey === 'raw') {
        const t = a.AM.raw - b.AM.raw
        if (t !== 0) return sortDir === 'asc' ? t : -t
      }
      if (sortKey === 'balanced') {
        const t = a.AM.balanced - b.AM.balanced
        if (t !== 0) return sortDir === 'asc' ? t : -t
      }
      if (a.intNum !== b.intNum) return a.intNum - b.intNum
      return a.movement.localeCompare(b.movement)
    })
    return sorted
  }, [allRows, selectedInts, sortKey, sortDir, showDropsOnly])

  // Live link conservation per period (recomputed from final values)
  const linkConservation = useMemo(() => {
    const result = { AM: [], PM: [] }
    for (const period of PERIODS) {
      const base = lastRun?.linkConservation?.[period] ?? []
      if (base.length === 0) continue
      result[period] = computeLinkConservationFinal(period, base, balancedByPeriod, overrides)
    }
    return result
  }, [lastRun, balancedByPeriod, overrides])

  const onClickHeader = (key) => {
    if (key === 'override') return     // not sortable
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const clampAllVisible = () => {
    if (visibleRows.length === 0) return
    for (const r of visibleRows) {
      for (const period of PERIODS) {
        if (r[period].delta < 0) {
          clampOverrideToRaw(period, r.intNum, r.movement, r[period].raw)
        }
      }
    }
  }

  const resetAllOverrides = () => {
    const totalOverrides =
      Object.values(overrides.AM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0) +
      Object.values(overrides.PM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0)
    if (totalOverrides === 0) return
    const ok = window.confirm(
      `Clear all ${totalOverrides} engineer override${totalOverrides === 1 ? '' : 's'} ` +
      `(AM + PM)? This cannot be undone.`
    )
    if (ok) clearAllOverrides()
  }

  if (needsRun) {
    return (
      <div className="di-s7r di-s7r--center">
        <div className="di-s7r-empty">
          <div className="di-banner">Run analysis first.</div>
          <p style={{ fontSize: 13, color: 'var(--text-tertiary)', margin: 0 }}>Redirecting…</p>
        </div>
      </div>
    )
  }

  const totalOverrides =
    Object.values(overrides.AM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0) +
    Object.values(overrides.PM || {}).reduce((acc, m) => acc + Object.keys(m).length, 0)

  return (
    <div className="di-s7r">
      <header className="di-s7r__head">
        <div>
          <h2 className="di-s7r__title">Review movements</h2>
          <p className="di-s7r__sub">
            Every turning movement at every intersection. Values shown as{' '}
            <code>AM (PM)</code>. Drops (balanced &lt; raw) appear with a red delta;
            toggle <em>Show drops only</em> to filter. Override AM and PM
            independently; link conservation deltas update live below.
          </p>
        </div>
      </header>

      <div className="di-s7r__toolbar">
        <div className="di-s7r__tools-left">
          <span className="di-s7r__label">Intersections</span>
          <div className="di-s7r__chips">
            {intersections.map((it) => {
              const selected = selectedInts.has(it.num)
              return (
                <button
                  key={it.id}
                  type="button"
                  aria-pressed={selected}
                  className={`di-s7r__chip${selected ? ' di-s7r__chip--on' : ''}`}
                  onClick={() => {
                    const next = new Set(selectedInts)
                    if (selected) next.delete(it.num)
                    else next.add(it.num)
                    setSelectedInts(next)
                  }}
                >{String(it.num).padStart(2, '0')}</button>
              )
            })}
          </div>
        </div>
        <div className="di-s7r__tools-right">
          <label className="di-s7r__toggle">
            <input
              type="checkbox"
              checked={showDropsOnly}
              onChange={(e) => setShowDropsOnly(e.target.checked)}
            />
            <span>Show drops only</span>
            {dropCount > 0 && (
              <span className="di-s7r__toggle-count">{dropCount}</span>
            )}
          </label>
          <button
            type="button"
            className="di-btn-secondary"
            onClick={clampAllVisible}
            disabled={visibleRows.length === 0}
            title="Clamp every visible row's dropping period(s) to raw"
          >
            Clamp all visible to raw
          </button>
          <button
            type="button"
            className="di-btn-secondary"
            onClick={resetAllOverrides}
          >
            Reset all overrides
          </button>
        </div>
      </div>

      <div className="di-s7r__panel">
        <div className="di-s7r__panel-meta">
          {showDropsOnly && visibleRows.length === 0 ? (
            <span className="di-s7r__empty">
              No drops below raw — balanced volumes match or exceed raw at every
              movement in both periods. Toggle off <em>Show drops only</em> to
              review all movements.
            </span>
          ) : (
            <>
              <span>{visibleRows.length} of {allRows.length} movements shown</span>
              <span className="di-s7r__meta-aux">
                {dropCount} drop{dropCount === 1 ? '' : 's'} across both periods
              </span>
              {totalOverrides > 0 && (
                <span className="di-s7r__override-badge">
                  {totalOverrides} override{totalOverrides === 1 ? '' : 's'} active
                </span>
              )}
            </>
          )}
        </div>

        {visibleRows.length > 0 && (
          <table className="di-s7r__table">
            <thead>
              <tr>
                <SortHeader col="int" label="Int" sortKey={sortKey} sortDir={sortDir} onClick={onClickHeader} />
                <SortHeader col="movement" label="Movement" sortKey={sortKey} sortDir={sortDir} onClick={onClickHeader} />
                <SortHeader col="raw" label="Raw  AM (PM)" sortKey={sortKey} sortDir={sortDir} onClick={onClickHeader} align="right" />
                <SortHeader col="balanced" label="Balanced  AM (PM)" sortKey={sortKey} sortDir={sortDir} onClick={onClickHeader} align="right" />
                <SortHeader col="delta" label="Delta  AM (PM)" sortKey={sortKey} sortDir={sortDir} onClick={onClickHeader} align="right" />
                <th className="di-s7r__th" style={{ textAlign: 'right' }}>Override  AM (PM)</th>
                <th className="di-s7r__th-action"></th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => (
                <DropRow key={`${r.intNum}-${r.movement}`} row={r} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {(linkConservation.AM.length > 0 || linkConservation.PM.length > 0) && (
        <div className="di-s7r__panel">
          <h3 className="di-s7r__panel-title">Link conservation (with overrides)</h3>
          <p className="di-s7r__panel-hint">
            Recomputed from final values. Non-zero deltas on Full-mode links are
            direct consequences of your overrides above.
          </p>
          <div className="di-s7r__lc-grid">
            {PERIODS.map((period) => (
              <LinkConservationPanel
                key={period}
                period={period}
                rows={linkConservation[period]}
              />
            ))}
          </div>
        </div>
      )}

      <footer className="di-s7r__footer">
        <button
          type="button"
          className="di-btn-primary"
          onClick={() => navigate('/results')}
        >
          Continue to results →
        </button>
      </footer>
    </div>
  )
}

function SortHeader({ col, label, sortKey, sortDir, onClick, align }) {
  const active = sortKey === col
  const arrow = active ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''
  return (
    <th
      className="di-s7r__th"
      style={{ textAlign: align || 'left', cursor: 'pointer' }}
      onClick={() => onClick(col)}
    >
      {label}{arrow}
    </th>
  )
}

function DropRow({ row }) {
  const isOverridden = row.AM.override != null || row.PM.override != null

  const resetBoth = () => {
    if (row.AM.override != null) clearOverride('AM', row.intNum, row.movement)
    if (row.PM.override != null) clearOverride('PM', row.intNum, row.movement)
  }

  // Render "value (value)" with each value's color independent (red if delta<0)
  const renderPair = (amText, amClass, pmText, pmClass) => (
    <span className="di-s7r__pair">
      <span className={amClass || 'di-s7r__num'}>{amText}</span>
      <span className="di-s7r__paren"> (</span>
      <span className={pmClass || 'di-s7r__num'}>{pmText}</span>
      <span className="di-s7r__paren">)</span>
    </span>
  )

  const amDeltaClass = row.AM.delta < 0 ? 'di-s7r__num di-s7r__delta-neg' : 'di-s7r__num'
  const pmDeltaClass = row.PM.delta < 0 ? 'di-s7r__num di-s7r__delta-neg' : 'di-s7r__num'

  return (
    <tr className={isOverridden ? 'di-s7r__row di-s7r__row--overridden' : 'di-s7r__row'}>
      <td>{String(row.intNum).padStart(2, '0')}</td>
      <td className="di-s7r__movement">{row.movement}</td>
      <td style={{ textAlign: 'right' }}>
        {renderPair(row.AM.raw, null, row.PM.raw, null)}
      </td>
      <td style={{ textAlign: 'right' }}>
        {renderPair(row.AM.balanced, null, row.PM.balanced, null)}
      </td>
      <td style={{ textAlign: 'right' }}>
        {renderPair(row.AM.delta, amDeltaClass, row.PM.delta, pmDeltaClass)}
      </td>
      <td style={{ textAlign: 'right' }}>
        <span className="di-s7r__override-pair">
          <OverrideInput
            period="AM"
            intNum={row.intNum}
            movement={row.movement}
            balanced={row.AM.balanced}
            currentOverride={row.AM.override}
          />
          <span className="di-s7r__paren"> (</span>
          <OverrideInput
            period="PM"
            intNum={row.intNum}
            movement={row.movement}
            balanced={row.PM.balanced}
            currentOverride={row.PM.override}
          />
          <span className="di-s7r__paren">)</span>
        </span>
      </td>
      <td className="di-s7r__td-action">
        <button
          type="button"
          className="di-s7r__reset"
          onClick={resetBoth}
          disabled={!isOverridden}
          aria-label={isOverridden ? 'Reset overrides (both periods)' : 'No override to reset'}
          title={isOverridden ? 'Reset both AM and PM' : 'No override'}
        >
          <RotateCcw size={12} />
        </button>
      </td>
    </tr>
  )
}

function OverrideInput({ period, intNum, movement, balanced, currentOverride }) {
  const initial = currentOverride != null ? currentOverride : balanced
  const [draft, setDraft] = useState(String(initial))

  // Re-sync from store when external changes happen (Clamp all, Reset all, etc.)
  useEffect(() => {
    setDraft(String(currentOverride != null ? currentOverride : balanced))
  }, [currentOverride, balanced])

  const commit = () => {
    const n = Number(draft)
    if (!Number.isFinite(n) || n < 0) {
      setDraft(String(currentOverride != null ? currentOverride : balanced))
      return
    }
    if (n === balanced) {
      if (currentOverride != null) clearOverride(period, intNum, movement)
    } else {
      setOverride(period, intNum, movement, n)
    }
  }

  return (
    <input
      type="number"
      step={5}
      min={0}
      className="di-s7r__override-input"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
      aria-label={`${period} override for ${movement} at intersection ${intNum}`}
    />
  )
}

function LinkConservationPanel({ period, rows }) {
  return (
    <div className="di-s7r__lc">
      <h4 className="di-s7r__lc-title">{period}</h4>
      <table className="di-s6-lc__table">
        <thead>
          <tr>
            <th>Link</th>
            <th>Dir</th>
            <th>Mode</th>
            <th style={{ textAlign: 'right' }}>Up</th>
            <th style={{ textAlign: 'right' }}>Down</th>
            <th style={{ textAlign: 'right' }}>Delta</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const ok = Math.abs(r.delta) <= 0.5
            return (
              <tr key={i} className={ok ? '' : 'di-s6-lc__row--warn'}>
                <td>{r.fromNum} → {r.toNum}</td>
                <td>{r.direction}</td>
                <td>{r.mode}</td>
                <td style={{ textAlign: 'right' }}>{r.upstream_outflow.toFixed(0)}</td>
                <td style={{ textAlign: 'right' }}>{r.downstream_inflow.toFixed(0)}</td>
                <td
                  style={{ textAlign: 'right' }}
                  className={ok ? 'di-s6-lc__delta--ok' : 'di-s6-lc__delta--warn'}
                >
                  {r.delta > 0 ? '+' : ''}{r.delta.toFixed(0)}
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
