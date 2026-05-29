import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Workflow, Check, Trash2, AlertTriangle } from 'lucide-react'
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
  clearProject,
} from '../store/projectStore'
import { reverseGeocode } from '../lib/photon'
import {
  bearing,
  deviationFromCardinal,
  detectCorridorDir,
  sortAlongCorridor,
  suggestDirection,
} from '../lib/geo'

const PERPENDICULAR = {
  'EB/WB': 'NB/SB', 'NB/SB': 'EB/WB',
  'NE/SW': 'NW/SE', 'NW/SE': 'NE/SW',
}

const newId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

// S2 is the corridor EDITOR — add/reorder/edit intersections and draw links.
// The post-balance flow map (Pre/Post toggle, AM (PM) labels, imbalance colors,
// PNG export) lives in S7 (review), where an analysis run exists to visualize.
export default function S2_MapIntersection() {
  const navigate = useNavigate()
  const [intersections, setIntersections] = useState(() => getIntersections())

  // Modal state shape:
  //   null when closed, otherwise:
  //   { mode: 'add' | 'edit', num, initial, pendingPin?, geocodeName?,
  //     geocodeFailed, skewDeg?, editIndex? }
  const [modal, setModal] = useState(null)
  // Surfaces an add-intersection failure as a visible banner instead of failing
  // silently (root-cause state corruption is fixed in the store; this is the
  // last-resort guard so a future throw can never swallow itself).
  const [addError, setAddError] = useState(null)

  // ── Stage 2: link drawing mode ─────────────────────────────────────
  // mapMode: 'intersections' (default — add/edit pins) | 'links' (draw/edit links)
  const [mapMode, setMapMode] = useState('intersections')
  const [armedId, setArmedId] = useState(null)          // 1st clicked pin in 'links' mode
  const [linkPopup, setLinkPopup] = useState(null)      // { id, x, y } screen pos for edit popup
  // Per-session one-time onboarding hint for the link mode. Renders the first
  // time the user enters 'links' mode; once dismissed, stays dismissed until
  // the page is refreshed (intentional — localStorage isn't used here).
  const [hintDismissed, setHintDismissed] = useState(false)

  // Links come from the store via useSyncExternalStore so edit-mode polylines
  // stay in sync as the user draws/removes them.
  const storeSnap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const links = storeSnap.links || []

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
    try {
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
      setAddError(null)
      setModal(null)
    } catch (err) {
      setAddError(err?.message || String(err))
    }
  }

  const handleCancel = () => { setAddError(null); setModal(null) }

  const handleResetProject = () => {
    clearProject()
    // Hard reload so every session's component-local state is cleared cleanly.
    window.location.assign('/')
  }

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

  // ── Map interaction ────────────────────────────────────────────────
  const handleMapClick = (latlng) => {
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
      return
    }
    setArmedId(null)
    if (mapMode === 'links') {
      setLinkPopup({ id: linkId, x: pos.x, y: pos.y })
    }
  }

  const switchMode = (next) => {
    if (next === mapMode) return
    setMapMode(next)
    setArmedId(null)
    setLinkPopup(null)
  }

  return (
    <div className="di-s2">
      <div className="di-s2__map">
        {addError && (
          <div
            className="di-banner"
            role="alert"
            style={{
              position: 'absolute',
              top: 12,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: 1200,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              maxWidth: 560,
              background: 'rgba(255, 107, 107, 0.1)',
              borderColor: 'rgba(255, 107, 107, 0.4)',
              color: '#FF8B8B',
            }}
          >
            <AlertTriangle size={14} style={{ flexShrink: 0 }} />
            <span style={{ flex: 1 }}>Failed to add intersection: {addError}</span>
            <button
              type="button"
              className="di-btn-secondary"
              style={{ height: 30, padding: '0 12px', fontSize: 12 }}
              onClick={handleResetProject}
            >
              Reset project
            </button>
            <button
              type="button"
              aria-label="Dismiss"
              onClick={() => setAddError(null)}
              style={{
                background: 'none',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                fontSize: 18,
                lineHeight: 1,
                padding: '0 2px',
              }}
            >
              ×
            </button>
          </div>
        )}
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

        <MapView
          intersections={intersections}
          pendingPin={modal?.pendingPin ?? null}
          onMapClick={handleMapClick}
          mode={mapMode}
          armedId={armedId}
          links={links}
          selectedLinkId={linkPopup?.id ?? null}
          onIntersectionClick={handleIntersectionClick}
          onSelectLink={handleSelectLink}
          viewMode="edit"
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
