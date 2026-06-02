import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, DownloadCloud, RotateCw } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  getIntersections,
  setForecasting,
  isExistingAnalysisDone,
} from '../store/projectStore'
import ForecastMatchMap from '../components/ForecastMatchMap'

import '../styles/forms.css'
import '../styles/forecasting.css'
import '../styles/map.css'   // .di-pin* for the map markers

const DIRS = ['NB', 'SB', 'EB', 'WB']

// A leg still needs the engineer's attention when it's ambiguous (no candidate
// picked yet) or unmatched without a resolution. matched/absent are settled.
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

function intNeedsReview(m) {
  return DIRS.some((d) => legNeedsReview(m.legs?.[d]))
}

export default function F2_NetworkMatch() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const gateOpen = isExistingAnalysisDone()
  const fc = snap.forecasting ?? {}
  const matches = fc.matches ?? null
  const baseLayer = fc.layers?.base ?? null
  const intersections = snap.intersections ?? []

  const [status, setStatus] = useState('idle') // idle | loading | error
  const [error, setError] = useState(null)       // { kind:'geo'|'generic', detail }
  const [activeNum, setActiveNum] = useState(() => matches?.[0]?.intersection_num ?? null)

  // Self-guard: forecasting needs existing balanced TMCs.
  useEffect(() => {
    if (gateOpen) return
    const t = setTimeout(() => navigate('/results'), 1200)
    return () => clearTimeout(t)
  }, [gateOpen, navigate])

  // activeNum is seeded from the persisted slice (useState init) and set by the
  // pull handler, so no sync effect is needed. Fall back to the first match if a
  // selection hasn't landed yet.
  const effectiveActive = activeNum ?? matches?.[0]?.intersection_num ?? null

  const linksById = useMemo(
    () => new Map((baseLayer?.links ?? []).map((l) => [l.link_id, l])),
    [baseLayer]
  )

  const networks = fc.networks ?? []
  const canPull =
    networks.length > 0 &&
    networks.some((n) => n.role === 'base') &&
    networks.every((n) => n.path && n.scenarioYear !== '' && n.scenarioYear != null)

  const pull = async () => {
    setStatus('loading')
    setError(null)
    try {
      const res = await fetch('/api/forecast/ingest-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intersections: getIntersections().map((it) => ({
            num: it.num, lat: it.lat, lng: it.lng, approaches: it.approaches,
          })),
          networks: networks.map((n) => ({
            role: n.role, scenario_year: Number(n.scenarioYear), path: n.path,
          })),
        }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* non-JSON body */ }
        if (res.status === 503) { setError({ kind: 'geo', detail }); setStatus('error'); return }
        throw new Error(detail)
      }
      const data = await res.json()
      setForecasting({ layers: data.layers, matches: data.matches })
      setActiveNum(data.matches?.[0]?.intersection_num ?? null)
      setStatus('idle')
    } catch (err) {
      setError({
        kind: 'generic',
        detail: `${err.message}. Make sure the backend is running under the combined venv (cd backend && .venv-forecasting/bin/python app.py).`,
      })
      setStatus('error')
    }
  }

  const updateLeg = (intNum, dir, partial) => {
    const next = (matches ?? []).map((m) =>
      m.intersection_num === intNum
        ? { ...m, legs: { ...m.legs, [dir]: { ...m.legs[dir], ...partial } } }
        : m
    )
    setForecasting({ matches: next })
  }

  if (!gateOpen) {
    return (
      <div className="di-page di-fc">
        <div className="di-eyebrow">Forecasting · Step 2</div>
        <h1 className="di-h1">Network match</h1>
        <p className="di-subtitle">Balance the existing volumes first. Redirecting…</p>
      </div>
    )
  }

  const unresolved = (matches ?? []).reduce(
    (n, m) => n + DIRS.filter((d) => legNeedsReview(m.legs?.[d])).length,
    0
  )
  const activeMatch = (matches ?? []).find((m) => m.intersection_num === effectiveActive) ?? null

  return (
    <div className="di-fc di-fc-match">
      <div className="di-fc-match__head">
        <div className="di-eyebrow">Forecasting · Step 2</div>
        <h1 className="di-h1" style={{ marginBottom: 4 }}>Network match</h1>
        <p className="di-subtitle" style={{ marginBottom: 12 }}>
          Pull the SANDAG network around your intersections and confirm which model
          link feeds each leg. Green is matched, amber needs a pick, red is off-network.
        </p>

        {error?.kind === 'geo' && (
          <div className="di-fc-banner di-fc-banner--warn" role="alert">
            {error.detail}
          </div>
        )}
        {error?.kind === 'generic' && (
          <div className="di-fc-banner di-fc-banner--error" role="alert">
            {error.detail}
          </div>
        )}
        {!canPull && (
          <div className="di-fc-banner di-fc-banner--warn">
            Set each network&apos;s role, model year, and file in{' '}
            <button
              type="button"
              onClick={() => navigate('/forecast/setup')}
              style={{ background: 'none', border: 'none', color: 'var(--signal-amber)', cursor: 'pointer', padding: 0, font: 'inherit', textDecoration: 'underline' }}
            >
              step 1
            </button>{' '}
            before pulling.
          </div>
        )}
      </div>

      {!matches ? (
        <div className="di-fc-pull">
          <DownloadCloud size={28} style={{ color: 'var(--signal-amber)' }} />
          <p>
            DemandIQ filters the {Number(baseLayer?.links?.length || 0) || '40,720'}-link
            SANDAG network to a few hundred feet around your {intersections.length}{' '}
            intersection{intersections.length === 1 ? '' : 's'}, then matches each leg.
          </p>
          <button
            type="button"
            className="di-btn-amber"
            disabled={!canPull || status === 'loading'}
            onClick={pull}
          >
            {status === 'loading' ? (
              <><Loader2 size={15} className="di-spin" /> Pulling network…</>
            ) : (
              <><DownloadCloud size={15} /> Pull SANDAG network</>
            )}
          </button>
        </div>
      ) : (
        <>
          <div className="di-fc-panes">
            <div className="di-fc-mapwrap">
              <ForecastMatchMap
                intersections={intersections}
                matches={matches}
                layer={baseLayer}
                activeNum={effectiveActive}
                onPickIntersection={setActiveNum}
              />
            </div>

            <div className="di-fc-review">
              <div className="di-fc-chiprow">
                {matches.map((m) => {
                  const active = m.intersection_num === effectiveActive
                  return (
                    <button
                      key={m.intersection_num}
                      type="button"
                      className={`di-fc-chip${active ? ' di-fc-chip--active' : ''}`}
                      onClick={() => setActiveNum(m.intersection_num)}
                    >
                      {m.intersection_num}
                      {intNeedsReview(m) && <span className="di-fc-chip__dot" />}
                    </button>
                  )
                })}
              </div>

              {activeMatch && (
                <>
                  <div className="di-fc-summary">
                    Int {activeMatch.intersection_num} · snapped to node{' '}
                    {activeMatch.snapped_node ?? '—'}
                    {activeMatch.snap_distance_ft != null && (
                      <> · {Math.round(activeMatch.snap_distance_ft)} ft</>
                    )}
                  </div>

                  {activeMatch.flags?.map((f, i) => (
                    <div key={i} className="di-fc-banner di-fc-banner--warn">{f.message}</div>
                  ))}

                  {DIRS.map((d) => (
                    <LegCard
                      key={d}
                      dir={d}
                      leg={activeMatch.legs?.[d]}
                      linksById={linksById}
                      onPick={(linkId) => updateLeg(activeMatch.intersection_num, d, {
                        status: 'matched', link_id: linkId, resolvedBy: 'engineer',
                      })}
                      onDecide={(decision) => updateLeg(activeMatch.intersection_num, d, { decision })}
                      onManual={(field, value) => updateLeg(activeMatch.intersection_num, d, {
                        manual: { ...(activeMatch.legs?.[d]?.manual ?? {}), [field]: value },
                      })}
                    />
                  ))}

                  {activeMatch.unbound_links?.length > 0 && (
                    <div className="di-fc-unbound">
                      {activeMatch.unbound_links.length} unbound link
                      {activeMatch.unbound_links.length === 1 ? '' : 's'} at this node (ramps /
                      frontage, no approach claims them):{' '}
                      {activeMatch.unbound_links
                        .map((u) => `${linksById.get(u.link_id)?.name || u.link_id} (${u.functional_class})`)
                        .join(', ')}.
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          <div className="di-fc-foot">
            <button type="button" className="di-fc-mini" onClick={pull} disabled={status === 'loading'}>
              <RotateCw size={13} style={{ verticalAlign: '-2px' }} /> Re-pull
            </button>
            <span className={`di-fc-gate ${unresolved === 0 ? 'di-fc-gate--ok' : 'di-fc-gate--todo'}`}>
              {unresolved === 0
                ? 'All legs resolved ✓'
                : `${unresolved} leg${unresolved === 1 ? '' : 's'} need a decision`}
            </span>
            <button
              type="button"
              className="di-btn-amber"
              style={{ marginLeft: 'auto' }}
              disabled={unresolved > 0}
              title={unresolved > 0 ? 'Resolve every flagged leg first' : 'Run the forecast'}
              onClick={() => navigate('/forecast/run')}
            >
              Continue to Run Forecast →
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function fmtInbound(inbound) {
  if (!inbound) return null
  const am = inbound.AM != null ? Math.round(inbound.AM) : '—'
  const pm = inbound.PM != null ? Math.round(inbound.PM) : '—'
  return `Base model inbound — AM ${am} · PM ${pm} (period veh)`
}

function LegCard({ dir, leg, linksById, onPick, onDecide, onManual }) {
  if (!leg) return null
  const status = leg.status
  const link = leg.link_id ? linksById.get(leg.link_id) : null

  return (
    <div className="di-fc-leg">
      <div className="di-fc-leg__head">
        <span className="di-fc-leg__dir">{dir}</span>
        <span className={`di-fc-badge di-fc-badge--${status}`}>{status}</span>
      </div>

      {status === 'matched' && (
        <div className="di-fc-leg__meta">
          <span className="di-fc-leg__name">{link?.name || leg.link_id}</span>
          {link?.functional_class ? ` · ${link.functional_class}` : ''}
          {leg.bearing_deg != null && <> · {Math.round(leg.bearing_deg)}° (dev {Math.round(leg.deviation_deg ?? 0)}°)</>}
          {leg.resolvedBy === 'engineer' && <> · confirmed</>}
          {fmtInbound(leg.inbound) && <div className="di-fc-leg__inbound">{fmtInbound(leg.inbound)}</div>}
        </div>
      )}

      {status === 'ambiguous' && (
        <div className="di-fc-leg__meta">
          Two model links point at this leg — pick the correct one:
          <div className="di-fc-cands">
            {(leg.candidates ?? []).map((id) => {
              const nl = linksById.get(id)
              return (
                <button key={id} type="button" className="di-fc-cand" onClick={() => onPick(id)}>
                  {nl?.name || id}{nl?.functional_class ? ` · ${nl.functional_class}` : ''}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {status === 'unmatched' && (
        <div className="di-fc-leg__meta">
          No network link within tolerance — off-network or cordon entry.
          <div className="di-fc-actions">
            <button
              type="button"
              className={`di-fc-mini${leg.decision === 'manual' ? ' di-fc-mini--on' : ''}`}
              onClick={() => onDecide('manual')}
            >
              Enter manually
            </button>
            <button
              type="button"
              className={`di-fc-mini${leg.decision === 'skip' ? ' di-fc-mini--on' : ''}`}
              onClick={() => onDecide('skip')}
            >
              Skip in balancing
            </button>
          </div>
          {leg.decision === 'manual' && (
            <div className="di-fc-manual">
              <label>
                Future inbound
                <input
                  className="di-input" type="number" inputMode="numeric" placeholder="veh"
                  value={leg.manual?.inbound ?? ''}
                  onChange={(e) => onManual('inbound', e.target.value)}
                />
              </label>
              <label>
                Future outbound
                <input
                  className="di-input" type="number" inputMode="numeric" placeholder="veh"
                  value={leg.manual?.outbound ?? ''}
                  onChange={(e) => onManual('outbound', e.target.value)}
                />
              </label>
            </div>
          )}
          {leg.decision === 'skip' && (
            <div className="di-fc-leg__inbound">Skipped — excluded from corridor balancing (Pass 2).</div>
          )}
        </div>
      )}

      {status === 'absent' && (
        <div className="di-fc-leg__meta">No leg here (3-leg intersection).</div>
      )}
    </div>
  )
}
