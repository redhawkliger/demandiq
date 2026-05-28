import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Workflow, Check, Trash2, Download, AlertTriangle } from 'lucide-react'
import 'leaflet/dist/leaflet.css'
import '../styles/forms.css'
import '../styles/map.css'

import MapView from '../components/MapView'
import IntersectionModal from '../components/IntersectionModal'
import IntersectionList from '../components/IntersectionList'
import {
  subscribe,
  getSnapshot,
  getIntersections,
  setIntersections as persistIntersections,
  reorderIntersections,
  setCorridorDir,
  addLink,
  removeLink,
  updateLink,
} from '../store/projectStore'
import { reverseGeocode } from '../lib/photon'
import {
  bearing,
  deviationFromCardinal,
  detectCorridorDir,
  sortAlongCorridor,
  suggestDirection,
} from '../lib/geo'
import {
  buildLinkFlows,
  lastRunStaleness,
} from '../lib/flowMap'
import { exportFlowMapPNG } from '../lib/flowMapExport'

const PERPENDICULAR = {
  'EB/WB': 'NB/SB', 'NB/SB': 'EB/WB',
  'NE/SW': 'NW/SE', 'NW/SE': 'NE/SW',
}

const newId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

export default function S2_MapIntersection() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [intersections, setIntersections] = useState(() => getIntersections())

  // Modal state shape:
  //   null when closed, otherwise:
  //   { mode: 'add' | 'edit', num, initial, pendingPin?, geocodeName?,
  //     geocodeFailed, skewDeg?, editIndex? }
  const [modal, setModal] = useState(null)

  // ── Stage 2: link drawing mode ─────────────────────────────────────
  // mapMode: 'intersections' (default — current behavior) | 'links'
  const [mapMode, setMapMode] = useState('intersections')
  const [armedId, setArmedId] = useState(null)          // 1st clicked pin in 'links' mode
  const [linkPopup, setLinkPopup] = useState(null)      // { id, x, y } screen pos for edit popup
  // Per-session one-time onboarding hint for the link mode. Renders the first
  // time the user enters 'links' mode; once dismissed, stays dismissed until
  // the page is refreshed (intentional — localStorage isn't used here).
  const [hintDismissed, setHintDismissed] = useState(false)

  // Links + lastRun + overrides come from the store via useSyncExternalStore
  // so the flow map reacts to any S6 re-run or S7 override edit.
  const storeSnap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const links = storeSnap.links || []
  const lastRun = storeSnap.analysis?.lastRun ?? null
  const overrides = storeSnap.balancing?.overrides ?? { AM: {}, PM: {} }

  // ── Stage 6: flow map view mode ────────────────────────────────────
  // 'edit'  → existing editing/intersections UX, direction-coded link colors
  // 'pre'   → pre-balance flow map (raw outflow/inflow)
  // 'post'  → post-balance flow map (override-or-balanced + resolved)
  // Default: 'post' if a lastRun exists, else 'pre'.
  // The S7 "View flow map" button passes ?view=post on navigation.
  const initialViewMode = () => {
    const q = searchParams.get('view')
    if (q === 'pre' || q === 'post' || q === 'edit') return q
    return lastRun ? 'post' : 'pre'
  }
  const [viewMode, setViewMode] = useState(initialViewMode)
  const [showDirLabels, setShowDirLabels] = useState(false)
  const [flowPopup, setFlowPopup] = useState(null)    // { id, x, y }
  const [exporting, setExporting] = useState(false)
  const tileLayerRef = useRef(null)
  const mapWrapperRef = useRef(null)

  // Detect stale lastRun vs current store (Stage 6 spec §open-question-2)
  const staleness = useMemo(
    () => lastRunStaleness(lastRun, links, intersections),
    [lastRun, links, intersections],
  )

  // Persist on every change after the initial mount
  const skipFirstSaveRef = useRef(true)
  useEffect(() => {
    if (skipFirstSaveRef.current) {
      skipFirstSaveRef.current = false
      return
    }
    persistIntersections(intersections)
  }, [intersections])

  const openAdd = (latlng) => {
    const num = intersections.length + 1
    let skewDeg = null
    if (intersections.length > 0) {
      const last = intersections[intersections.length - 1]
      const b = bearing(
        { lat: last.lat, lng: last.lng },
        { lat: latlng.lat, lng: latlng.lng }
      )
      skewDeg = deviationFromCardinal(b)
    }
    setModal({
      mode: 'add',
      num,
      initial: {
        name: '',
        control: 'Signalized',
        legs: '4-leg',
        mainDir: 'EB/WB',
        crossDir: PERPENDICULAR['EB/WB'],
      },
      pendingPin: { lat: latlng.lat, lng: latlng.lng },
      geocodeName: null,
      geocodeFailed: false,
      skewDeg,
      editIndex: null,
    })

    // Reverse geocode in background; only apply if this same pin is still open.
    reverseGeocode(latlng.lat, latlng.lng)
      .then((name) => {
        setModal((prev) => {
          if (
            !prev ||
            !prev.pendingPin ||
            prev.pendingPin.lat !== latlng.lat ||
            prev.pendingPin.lng !== latlng.lng
          ) return prev
          return { ...prev, geocodeName: name || null, geocodeFailed: !name }
        })
      })
      .catch(() => {
        setModal((prev) => {
          if (
            !prev ||
            !prev.pendingPin ||
            prev.pendingPin.lat !== latlng.lat ||
            prev.pendingPin.lng !== latlng.lng
          ) return prev
          return { ...prev, geocodeFailed: true }
        })
      })
  }

  const openEdit = (idx) => {
    const it = intersections[idx]
    setModal({
      mode: 'edit',
      num: it.num,
      initial: {
        name: it.name,
        control: it.control,
        legs: it.legs,
        mainDir: it.mainDir,
        crossDir: it.crossDir,
      },
      pendingPin: null,
      geocodeName: null,
      geocodeFailed: false,
      skewDeg: null,
      editIndex: idx,
    })
  }

  const handleConfirm = (form) => {
    if (modal.mode === 'add') {
      setIntersections([
        ...intersections,
        {
          id: newId(),
          num: modal.num,
          lat: modal.pendingPin.lat,
          lng: modal.pendingPin.lng,
          ...form,
        },
      ])
    } else {
      const next = [...intersections]
      next[modal.editIndex] = { ...next[modal.editIndex], ...form }
      setIntersections(next)
    }
    setModal(null)
  }

  const handleCancel = () => setModal(null)

  const handleRemove = (idx) => {
    const next = intersections
      .filter((_, i) => i !== idx)
      .map((it, i) => ({ ...it, num: i + 1 }))
    setIntersections(next)
  }

  // Atomic: build the reordered list with renumbered `num` in a single setState,
  // mirroring the store-side reorderIntersections (which the persist effect calls).
  const handleReorder = (orderedIds) => {
    const byId = new Map(intersections.map((it) => [it.id, it]))
    const next = orderedIds
      .map((id, i) => {
        const it = byId.get(id)
        return it ? { ...it, num: i + 1 } : null
      })
      .filter(Boolean)
    if (next.length !== intersections.length) return
    setIntersections(next)
    // Belt-and-braces store-side reorder so the new order is canonical even if
    // a parallel render swallowed the effect (e.g. unmount mid-drag).
    reorderIntersections(orderedIds)
  }

  const handleContinue = () => {
    const dir = detectCorridorDir(intersections)
    const sorted = sortAlongCorridor(intersections, dir).map((it, i) => ({
      ...it,
      num: i + 1,
    }))
    setIntersections(sorted)
    setCorridorDir(dir)
    navigate('/approaches')
  }

  // ── Link-mode handlers ─────────────────────────────────────────────
  const handleMapClick = (latlng) => {
    // Stage 6: in flow view modes, the map is read-only. Empty-area clicks
    // close any open flow popup but never add a new intersection.
    if (viewMode === 'pre' || viewMode === 'post') {
      if (flowPopup) setFlowPopup(null)
      return
    }
    if (mapMode === 'intersections') {
      openAdd(latlng)
      return
    }
    // In link mode an empty map click cancels any pending arm or open popup
    if (armedId) setArmedId(null)
    if (linkPopup) setLinkPopup(null)
  }

  const handleIntersectionClick = (intId) => {
    if (mapMode !== 'links') return
    if (linkPopup) setLinkPopup(null)
    if (!armedId) {
      setArmedId(intId)
      return
    }
    if (armedId === intId) {
      setArmedId(null)  // de-arm: clicked the same pin twice
      return
    }
    const a = intersections.find((it) => it.id === armedId)
    const b = intersections.find((it) => it.id === intId)
    setArmedId(null)
    if (!a || !b) return
    addLink({
      fromId: a.id,
      toId: b.id,
      direction: suggestDirection(a, b),
      mode: 'Full',
    })
    // addLink returns the existing id silently on dedupe — no toast for Stage 2
  }

  const handleSelectLink = (linkId, pos) => {
    if (!linkId || !pos) {
      setLinkPopup(null)
      setFlowPopup(null)
      return
    }
    setArmedId(null)
    // Edit mode → editing popup; flow modes → flow popup
    if (mapMode === 'links') {
      setLinkPopup({ id: linkId, x: pos.x, y: pos.y })
    } else if (viewMode === 'pre' || viewMode === 'post') {
      setFlowPopup({ id: linkId, x: pos.x, y: pos.y })
    }
  }

  const switchMode = (next) => {
    if (next === mapMode) return
    setMapMode(next)
    setArmedId(null)
    setLinkPopup(null)
    setFlowPopup(null)
    // Entering link-edit mode forces viewMode to 'edit' so colors match
    // the editing UX. Leaving link-edit mode restores the preferred flow
    // view (post if available, else pre).
    if (next === 'links') {
      setViewMode('edit')
    } else if (viewMode === 'edit') {
      setViewMode(lastRun ? 'post' : 'pre')
    }
  }

  const switchViewMode = (next) => {
    if (next === viewMode) return
    setFlowPopup(null)
    setLinkPopup(null)
    setViewMode(next)
  }

  const handleExportPNG = async () => {
    if (!tileLayerRef.current || !mapWrapperRef.current) return
    setExporting(true)
    try {
      const container = mapWrapperRef.current.querySelector('.leaflet-container')
      await exportFlowMapPNG({
        tileLayer: tileLayerRef.current,
        container,
        meta: {
          projectName: storeSnap.project?.name || 'project',
          viewType: viewMode === 'post' ? 'Post' : 'Pre',
          method: lastRun?.method,
          date: lastRun?.timestamp,
        },
      })
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('PNG export failed:', err)
      alert(`PNG export failed: ${err.message}`)
    } finally {
      setExporting(false)
    }
  }

  const flowMode = viewMode === 'pre' || viewMode === 'post'
  const canExport = flowMode && intersections.length > 0
  const showStaleBanner = flowMode && staleness.stale && viewMode === 'post'

  return (
    <div className="di-s2">
      <div className="di-s2__map" ref={mapWrapperRef}>
        <div className="di-s2-mode">
          <button
            type="button"
            aria-pressed={mapMode === 'links'}
            className={`di-s2-mode__toggle${mapMode === 'links' ? ' di-s2-mode__toggle--on' : ''}`}
            onClick={() => switchMode(mapMode === 'links' ? 'intersections' : 'links')}
          >
            {mapMode === 'links' ? (
              <><Check size={14} /> Done</>
            ) : (
              <><Workflow size={14} /> Modify links</>
            )}
          </button>
          {mapMode === 'links' && (
            <span className="di-s2-mode__hint">
              {armedId
                ? 'Click a second intersection to link, or the same one to cancel'
                : 'Click an intersection to start a link'}
            </span>
          )}
        </div>

        {mapMode !== 'links' && (
          <div className="di-s2-flow-toolbar">
            <div className="di-s2-flow-toolbar__row">
              <div className="di-s2-flow-toolbar__seg" role="tablist" aria-label="Flow map view">
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === 'pre'}
                  className={`di-s2-flow-toolbar__opt${viewMode === 'pre' ? ' di-s2-flow-toolbar__opt--on' : ''}`}
                  onClick={() => switchViewMode('pre')}
                >Pre-balance</button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={viewMode === 'post'}
                  className={`di-s2-flow-toolbar__opt${viewMode === 'post' ? ' di-s2-flow-toolbar__opt--on' : ''}`}
                  onClick={() => switchViewMode('post')}
                  disabled={!lastRun}
                  title={lastRun ? '' : 'Run S6 analysis first'}
                >Post-balance</button>
              </div>
            </div>
            <div className="di-s2-flow-toolbar__row">
              <label className="di-s2-flow-toolbar__check">
                <input
                  type="checkbox"
                  checked={showDirLabels}
                  onChange={(e) => setShowDirLabels(e.target.checked)}
                  disabled={!flowMode}
                />
                <span>Show direction labels</span>
              </label>
              <button
                type="button"
                className="di-s2-flow-toolbar__export"
                onClick={handleExportPNG}
                disabled={!canExport || exporting}
                title={canExport ? 'Export this view as PNG' : 'Switch to Pre or Post first'}
              >
                <Download size={14} /> {exporting ? 'Exporting…' : 'Export PNG'}
              </button>
            </div>
          </div>
        )}

        {showStaleBanner && (
          <div className="di-s2-flow-stale" role="status">
            <AlertTriangle size={14} />
            Post-balance data may be stale — {staleness.reason}. Re-run S6 to refresh.
          </div>
        )}

        <MapView
          intersections={intersections}
          pendingPin={modal?.pendingPin ?? null}
          onMapClick={handleMapClick}
          mode={mapMode}
          armedId={armedId}
          links={links}
          selectedLinkId={(linkPopup?.id ?? flowPopup?.id) ?? null}
          onIntersectionClick={handleIntersectionClick}
          onSelectLink={handleSelectLink}
          viewMode={mapMode === 'links' ? 'edit' : viewMode}
          showDirLabels={showDirLabels}
          lastRun={lastRun}
          overrides={overrides}
          onTileLayerReady={(tl) => { tileLayerRef.current = tl }}
        />

        {mapMode === 'links' && !hintDismissed && (
          <div className="di-link-hint" role="dialog" aria-label="Modify links help">
            <div className="di-link-hint__title">Modifying links</div>
            <div className="di-link-hint__body">
              Click one intersection, then another, to connect them for balancing.
              The direction (EB/WB or NB/SB) is auto-detected — click any link to
              change it or delete it.
            </div>
            <button
              type="button"
              className="di-link-hint__dismiss"
              onClick={() => setHintDismissed(true)}
            >
              Got it
            </button>
          </div>
        )}

        {linkPopup && (
          <LinkEditPopup
            link={links.find((l) => l.id === linkPopup.id)}
            intersections={intersections}
            pos={{ x: linkPopup.x, y: linkPopup.y }}
            onUpdate={(partial) => updateLink(linkPopup.id, partial)}
            onRemove={() => { removeLink(linkPopup.id); setLinkPopup(null) }}
            onClose={() => setLinkPopup(null)}
          />
        )}

        {flowPopup && (
          <LinkFlowPopup
            link={links.find((l) => l.id === flowPopup.id)}
            intersections={intersections}
            viewMode={viewMode}
            lastRun={lastRun}
            overrides={overrides}
            pos={{ x: flowPopup.x, y: flowPopup.y }}
            onClose={() => setFlowPopup(null)}
          />
        )}
      </div>

      <IntersectionList
        intersections={intersections}
        onEdit={openEdit}
        onRemove={handleRemove}
        onReorder={handleReorder}
        onContinue={handleContinue}
        canContinue={intersections.length >= 2}
      />

      <IntersectionModal
        open={modal !== null}
        mode={modal?.mode}
        num={modal?.num}
        initial={modal?.initial}
        geocodeName={modal?.geocodeName}
        geocodeFailed={modal?.geocodeFailed ?? false}
        skewDeg={modal?.skewDeg}
        onCancel={handleCancel}
        onConfirm={handleConfirm}
      />
    </div>
  )
}

// ── Floating popup that edits a single link (direction / mode / delete) ──
// Positioned absolutely over the map at the click point. Closes on outside
// click; map pan/zoom also closes it from MapView's LinkLayers component.
function LinkEditPopup({ link, intersections, pos, onUpdate, onRemove, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onClose])

  if (!link) return null

  const fromInt = intersections.find((it) => it.id === link.fromId)
  const toInt = intersections.find((it) => it.id === link.toId)
  const fromLabel = fromInt ? `${fromInt.num}` : '?'
  const toLabel = toInt ? `${toInt.num}` : '?'

  return (
    <div
      ref={ref}
      className="di-link-popup"
      style={{ left: pos.x, top: pos.y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="di-link-popup__head">
        Link <span className="di-link-popup__num">{fromLabel}</span>
        {' → '}
        <span className="di-link-popup__num">{toLabel}</span>
      </div>
      <div className="di-link-popup__row">
        <label>Direction</label>
        <button
          type="button"
          className="di-link-popup__dir"
          onClick={() => onUpdate({
            direction: link.direction === 'EB/WB' ? 'NB/SB' : 'EB/WB',
          })}
        >
          {link.direction}
        </button>
      </div>
      <div className="di-link-popup__row">
        <label>Mode</label>
        <select
          className="di-link-popup__select"
          value={link.mode}
          onChange={(e) => onUpdate({ mode: e.target.value })}
        >
          <option value="Full">Full</option>
          <option value="Land Use">Land Use</option>
          <option value="None">None</option>
        </select>
      </div>
      <button
        type="button"
        className="di-link-popup__delete"
        onClick={onRemove}
      >
        <Trash2 size={12} /> Delete link
      </button>
    </div>
  )
}

// ── Stage 6: flow-mode popup (read-only) ──────────────────────────────
// Shows BOTH directed entries for the clicked physical link, each with
// raw upstream/downstream, resolved link vol, post-balance value, and
// residual — for AM and PM. No editing controls.
function LinkFlowPopup({ link, intersections, viewMode, lastRun, overrides, pos, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onClose])

  // Always derive flows in POST mode internally so the popup can render
  // resolved + post-balance + residual even when the engineer is looking
  // at the Pre-balance map (otherwise those fields would be missing in
  // pre view, defeating the purpose of the popup). We also derive PRE
  // values from raw counts independently for the "Raw" rows.
  const flowsPost = useMemo(() => {
    if (!link) return []
    return buildLinkFlows([link], intersections, 'post', { lastRun, overrides })
  }, [link, intersections, lastRun, overrides])
  const flowsPre = useMemo(() => {
    if (!link) return []
    return buildLinkFlows([link], intersections, 'pre', { lastRun, overrides })
  }, [link, intersections, lastRun, overrides])

  if (!link) return null
  const post = flowsPost[0]
  const pre  = flowsPre[0]
  if (!post || !pre) return null

  return (
    <div
      ref={ref}
      className="di-link-popup di-flow-popup"
      style={{ left: pos.x, top: pos.y }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="di-link-popup__head">
        Link <span className="di-link-popup__num">{post.from.num}</span>
        {' ↔ '}
        <span className="di-link-popup__num">{post.to.num}</span>
        <span className="di-flow-popup__mode">{link.mode}</span>
      </div>
      {post.directeds.map((pd, idx) => {
        const preMatch = pre.directeds.find(
          (p) => p.directed.direction === pd.directed.direction
        )
        return (
          <FlowDirectionSection
            key={idx}
            directed={pd.directed}
            preFlow={preMatch?.flows}
            postFlow={pd.flows}
            showPostFields={viewMode === 'post' && lastRun != null}
          />
        )
      })}
    </div>
  )
}

function FlowDirectionSection({ directed, preFlow, postFlow, showPostFields }) {
  if (!preFlow || !postFlow) return null
  const fmt = (n) =>
    (n == null || !Number.isFinite(n)) ? '—' : Math.round(n).toLocaleString()
  const pair = (am, pm) => `${fmt(am)} (${fmt(pm)})`
  const residualSign = (n) =>
    n == null ? '' : (n > 0 ? '+' : '')
  return (
    <div className="di-flow-popup__section">
      <div className="di-flow-popup__sec-head">
        <span className="di-flow-popup__sec-dir">{directed.direction}</span>
        {' '}
        <span className="di-flow-popup__sec-route">
          {directed.from.num} → {directed.to.num}
        </span>
      </div>
      <div className="di-flow-popup__row">
        <span>Raw upstream out</span>
        <span className="di-flow-popup__val">{pair(preFlow.AM.upOut, preFlow.PM.upOut)}</span>
      </div>
      <div className="di-flow-popup__row">
        <span>Raw downstream in</span>
        <span className="di-flow-popup__val">{pair(preFlow.AM.downIn, preFlow.PM.downIn)}</span>
      </div>
      {showPostFields && (
        <>
          <div className="di-flow-popup__row">
            <span>Resolved link vol</span>
            <span className="di-flow-popup__val">{pair(postFlow.AM.resolved, postFlow.PM.resolved)}</span>
          </div>
          <div className="di-flow-popup__row">
            <span>Post-balance value</span>
            <span className="di-flow-popup__val">{pair(postFlow.AM.postValue, postFlow.PM.postValue)}</span>
          </div>
          <div className="di-flow-popup__row">
            <span>Residual</span>
            <span className="di-flow-popup__val">
              {residualSign(postFlow.AM.residual)}{fmt(postFlow.AM.residual)}
              {' / '}
              {residualSign(postFlow.PM.residual)}{fmt(postFlow.PM.residual)}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
