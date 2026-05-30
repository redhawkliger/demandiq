import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Search, X, Loader2 } from 'lucide-react'
import { searchPhoton } from '../lib/photon'
import { buildLinkFlows, fmtPair } from '../lib/flowMap'
import { TILE_ATTR, currentTheme, tileUrlForTheme } from '../lib/themeTiles'

// Zoom thresholds for flow-label visibility (spec §6.7)
const FLOW_LABEL_FADE_ZOOM = 13
const FLOW_LABEL_HIDE_ZOOM = 11
// Flow label placement: each marker's latlng IS the polyline midpoint.
// Direction-specific CSS transforms on .di-flow-label__inner[data-dir]
// anchor the label by the EDGE facing the polyline (8px gap), so labels
// CAN'T overlap regardless of their width — center-to-center offset math
// couldn't make that promise once labels exceeded the offset value.
// Convention follows the "driver's right" rule: EB south, WB north,
// NB east, SB west.

const numberedIcon = (num, { armed = false, linkable = false, selected = false, actions = false } = {}) => {
  const actionsHtml = actions
    ? '<div class="di-pin__actions">' +
        '<button class="di-pin__connect" data-act="connect" type="button">🔗 Link</button>' +
        '<button class="di-pin__del" data-act="delete" type="button" aria-label="Delete intersection">✕</button>' +
      '</div>'
    : ''
  return L.divIcon({
    className:
      `di-pin${armed ? ' di-pin--armed' : ''}` +
      `${linkable ? ' di-pin--linkable' : ''}` +
      `${selected ? ' di-pin--selected' : ''}`,
    html: `<div class="di-pin__num">${num}</div>${actionsHtml}`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  })
}

const pendingIcon = L.divIcon({
  className: 'di-pin',
  html: '<div class="di-pin__pending"></div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
})

// ── Map click → orchestrator ──────────────────────────────────────────
// Pan-guard: a click only counts if the pointer barely moved (<5px) and the
// press was brief (<250ms). This keeps a drag-to-pan from being read as a
// click (e.g. dropping an intersection in S2's Add mode). Leaflet already
// suppresses most post-drag clicks; this makes the guarantee explicit.
function ClickHandler({ onClick }) {
  const downRef = useRef(null)
  useMapEvents({
    mousedown: (e) => { downRef.current = { pt: e.containerPoint, t: Date.now() } },
    click: (e) => {
      const d = downRef.current
      downRef.current = null
      if (d) {
        const moved = Math.hypot(e.containerPoint.x - d.pt.x, e.containerPoint.y - d.pt.y)
        if (moved >= 5 || Date.now() - d.t >= 250) return
      }
      onClick?.(e.latlng)
    },
  })
  return null
}

// ── Imperative layer manager ──────────────────────────────────────────
// `mode` controls interactivity:
//   'intersections' → existing behavior (non-interactive pins, dashed corridor)
//   'links'         → pins are clickable to arm/connect; dashed corridor hidden
//                     to avoid visual confusion with explicit link polylines
function MapLayers({
  intersections, pendingPin, mode, viewMode, armedId, onIntersectionClick,
  // S2 editing (opt-in; S7 leaves these unset → unchanged behavior)
  editablePins = false, selectedId = null, connectFromId = null,
  onConnectStart, onDeleteIntersection,
}) {
  const map = useMap()
  const markersRef = useRef([])
  const polylineRef = useRef(null)
  const pendingRef = useRef(null)
  const initialFitRef = useRef(false)

  // Confirmed numbered markers + dashed corridor polyline. Corridor is an
  // editing-mode visual aid showing intersection ORDER; it walks through
  // every intersection regardless of which links the engineer drew. In
  // flow view modes ('pre' / 'post') that's misleading — a deleted link
  // would still appear as a dashed segment — so we suppress it there.
  useEffect(() => {
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []
    if (polylineRef.current) {
      polylineRef.current.remove()
      polylineRef.current = null
    }
    intersections.forEach((it) => {
      const linkable = mode === 'links'
      const interactive = linkable || editablePins
      const armed = armedId === it.id || connectFromId === it.id
      const selected = selectedId === it.id
      const showActions = selected && editablePins
      const m = L.marker([it.lat, it.lng], {
        icon: numberedIcon(it.num, { armed, linkable: interactive, selected, actions: showActions }),
        interactive,
        keyboard: false,
      }).addTo(map)
      if (interactive && onIntersectionClick) {
        m.on('click', (e) => {
          // Clicks on the glued action buttons are handled by their own DOM
          // listeners below — don't also treat them as a "select" of the pin.
          const t = e.originalEvent?.target
          if (t && t.closest && t.closest('.di-pin__actions')) return
          L.DomEvent.stopPropagation(e)        // don't bubble to map (no new pin)
          const pt = map.latLngToContainerPoint(e.latlng)
          onIntersectionClick(it.id, { x: pt.x, y: pt.y })
        })
      }
      if (showActions) {
        const el = m.getElement()
        const cBtn = el?.querySelector('.di-pin__connect')
        const dBtn = el?.querySelector('.di-pin__del')
        if (cBtn) cBtn.addEventListener('click', (ev) => { ev.stopPropagation(); onConnectStart?.(it.id) })
        if (dBtn) dBtn.addEventListener('click', (ev) => { ev.stopPropagation(); onDeleteIntersection?.(it.id) })
      }
      markersRef.current.push(m)
    })
    // Dashed "corridor order" aid: only in legacy/flow-less non-editable views.
    // S2 edit mode (editablePins) renders NO line except real connected links,
    // so the dashed corridor is suppressed there.
    const isFlow = viewMode === 'pre' || viewMode === 'post'
    if (mode !== 'links' && !isFlow && !editablePins && intersections.length >= 2) {
      polylineRef.current = L.polyline(
        intersections.map((it) => [it.lat, it.lng]),
        {
          color: '#0A84FF',
          weight: 2.5,
          opacity: 0.85,
          dashArray: '6, 6',
          interactive: false,
        }
      ).addTo(map)
    }
  }, [intersections, mode, viewMode, armedId, onIntersectionClick, map,
      editablePins, selectedId, connectFromId, onConnectStart, onDeleteIntersection])

  // Amber pending marker
  useEffect(() => {
    if (pendingRef.current) {
      pendingRef.current.remove()
      pendingRef.current = null
    }
    if (pendingPin) {
      pendingRef.current = L.marker([pendingPin.lat, pendingPin.lng], {
        icon: pendingIcon,
        interactive: false,
        keyboard: false,
      }).addTo(map)
    }
  }, [pendingPin, map])

  // Fit bounds once, on initial mount, if the project already has pins
  useEffect(() => {
    if (initialFitRef.current) return
    initialFitRef.current = true
    if (intersections.length > 0) {
      const bounds = L.latLngBounds(intersections.map((it) => [it.lat, it.lng]))
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 })
    }
  }, [map, intersections])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      markersRef.current.forEach((m) => m.remove())
      if (polylineRef.current) polylineRef.current.remove()
      if (pendingRef.current) pendingRef.current.remove()
    }
  }, [])

  return null
}

// ── Link polylines ────────────────────────────────────────────────────
// Renders one straight-line polyline per link.
// Color rules:
//   mode === 'links'              → direction-coded (EB/WB blue, NB/SB amber)
//                                   for the editing UX
//   viewMode === 'pre' | 'post'   → imbalance-coded (green / amber / red)
//                                   using buildLinkFlows() to derive the
//                                   worst per-link % across AM and PM
//   otherwise                     → direction-coded (legacy default)
// CRITICAL: each polyline is drawn as a direct from→to segment — never routed
// through any other intersection that happens to sit between them on the map.
// Clickable in 'links' mode (edits) AND in flow modes ('pre' / 'post', opens
// the flow popup). The same onSelectLink callback fires in both cases —
// the parent decides which popup to render.
function LinkLayers({
  intersections, links, viewMode,
  selectedLinkId, onSelectLink,
  lastRun, overrides, editablePins = false,
}) {
  const map = useMap()
  const linesRef = useRef([])
  const isFlow = viewMode === 'pre' || viewMode === 'post'

  useEffect(() => {
    linesRef.current.forEach((l) => l.remove())
    linesRef.current = []
    const byId = new Map(intersections.map((it) => [it.id, it]))

    // In flow mode, precompute imbalance color per link.
    const flowsByLinkId = new Map()
    if (isFlow) {
      const flows = buildLinkFlows(links, intersections, viewMode, { lastRun, overrides })
      for (const f of flows) flowsByLinkId.set(f.link.id, f)
    }

    for (const link of links) {
      const from = byId.get(link.fromId)
      const to = byId.get(link.toId)
      if (!from || !to) continue  // orphaned link — render nothing
      const latlngs = [[from.lat, from.lng], [to.lat, to.lng]]
      const selected = link.id === selectedLinkId
      const onClick = (e) => {
        L.DomEvent.stopPropagation(e)
        const pt = map.latLngToContainerPoint(e.latlng)
        onSelectLink?.(link.id, { x: pt.x, y: pt.y })
      }

      if (isFlow) {
        // S7 flow map — imbalance-coded (unchanged; serves a different purpose)
        const color = flowsByLinkId.get(link.id)?.polyColor || '#6B7280'
        const polyline = L.polyline(latlngs, {
          color, weight: selected ? 5 : 3.5, opacity: selected ? 1 : 0.9,
          interactive: true, pane: 'overlayPane',
        }).addTo(map)
        if (onSelectLink) polyline.on('click', onClick)
        linesRef.current.push(polyline)
        continue
      }

      // S2 edit mode — one solid blue line per connected link. No direction
      // color, no dashes, no arrows. Selected adds a yellow accent halo
      // underneath; hover thickens the line by 1px.
      if (selected) {
        const halo = L.polyline(latlngs, {
          color: '#FFD60A', weight: 8, opacity: 0.9,
          interactive: false, pane: 'overlayPane',
        }).addTo(map)
        linesRef.current.push(halo)
      }
      const polyline = L.polyline(latlngs, {
        color: '#0A84FF', weight: 4, opacity: 1,
        interactive: true, pane: 'overlayPane',
      }).addTo(map)
      polyline.on('mouseover', () => polyline.setStyle({ weight: 5 }))
      polyline.on('mouseout', () => polyline.setStyle({ weight: 4 }))
      if (onSelectLink) polyline.on('click', onClick)
      linesRef.current.push(polyline)
    }
  }, [intersections, links, viewMode, isFlow, selectedLinkId, onSelectLink, lastRun, overrides, map, editablePins])

  // Close popup on map pan/zoom — popup position is computed at click time
  // and would drift otherwise
  useEffect(() => {
    if (!onSelectLink) return
    const close = () => onSelectLink(null, null)
    map.on('movestart', close)
    map.on('zoomstart', close)
    return () => {
      map.off('movestart', close)
      map.off('zoomstart', close)
    }
  }, [map, onSelectLink])

  useEffect(() => () => {
    linesRef.current.forEach((l) => l.remove())
  }, [])

  return null
}

// ── Flow-mode volume labels (Stage 6) ─────────────────────────────────
// One divIcon per directed link, positioned at the link midpoint with a
// perpendicular pixel offset so EB / WB (or NB / SB) labels don't overlap
// each other. Re-renders on zoom (for the fade-out behavior).
function FlowLabels({
  intersections, links, viewMode, showDirLabels,
  lastRun, overrides,
}) {
  const map = useMap()
  const markersRef = useRef([])
  const [zoom, setZoom] = useState(() => map.getZoom())

  useEffect(() => {
    const onZoom = () => setZoom(map.getZoom())
    map.on('zoomend', onZoom)
    return () => { map.off('zoomend', onZoom) }
  }, [map])

  useEffect(() => {
    // Wipe + rebuild markers
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []

    if (viewMode !== 'pre' && viewMode !== 'post') return
    if (zoom < FLOW_LABEL_HIDE_ZOOM) return    // hidden entirely

    const opacity = zoom < FLOW_LABEL_FADE_ZOOM ? 0.3 : 1
    const flows = buildLinkFlows(links, intersections, viewMode, { lastRun, overrides })

    for (const f of flows) {
      // Spec §fix-v2: post view + link has no lastRun match → render the
      // polyline gray (already handled in LinkLayers) and skip labels.
      if (viewMode === 'post' && !f.hasLastRunData) continue
      // Both directed labels share the same anchor latlng — the polyline
      // midpoint. The CSS transform (keyed off data-dir) places each label
      // on the correct side, by its facing edge, so they cannot overlap.
      const midLat = (f.from.lat + f.to.lat) / 2
      const midLng = (f.from.lng + f.to.lng) / 2
      const latlng = [midLat, midLng]

      for (const pd of f.directeds) {
        const dirCode = pd.directed.direction
        const am = pd.flows.AM
        const pm = pd.flows.PM
        const text = fmtPair(
          viewMode === 'post' ? am.postValue ?? am.upOut : am.upOut,
          viewMode === 'post' ? pm.postValue ?? pm.upOut : pm.upOut,
        )
        const colorAM = am.color
        const colorPM = pm.color
        const dirChip = showDirLabels
          ? `<span class="di-flow-label__dir">${dirCode}</span>`
          : ''
        const html = `
          <div class="di-flow-label__inner" data-dir="${dirCode}" style="opacity:${opacity}">
            ${dirChip}<span class="di-flow-label__num" style="--am:${colorAM};--pm:${colorPM}">${text}</span>
          </div>
        `
        const icon = L.divIcon({
          className: 'di-flow-label',
          html,
          iconSize: [0, 0],     // size-from-content
          iconAnchor: [0, 0],
        })
        const m = L.marker(latlng, {
          icon,
          interactive: false,
          keyboard: false,
          pane: 'markerPane',
        }).addTo(map)
        markersRef.current.push(m)
      }
    }
  }, [intersections, links, viewMode, showDirLabels, lastRun, overrides, zoom, map])

  useEffect(() => () => {
    markersRef.current.forEach((m) => m.remove())
  }, [])

  return null
}

// Expose the L.TileLayer instance up to the parent so the PNG export
// helper can call setUrl() to swap dark → light tiles for the capture.
function TileLayerHandle({ onReady }) {
  const map = useMap()
  useEffect(() => {
    let tileLayer = null
    map.eachLayer((layer) => {
      if (layer instanceof L.TileLayer) tileLayer = layer
    })
    if (tileLayer && onReady) onReady(tileLayer)
  }, [map, onReady])
  return null
}

// ── Floating Photon search ────────────────────────────────────────────
function SearchBar() {
  const map = useMap()
  const containerRef = useRef(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    L.DomEvent.disableClickPropagation(containerRef.current)
    L.DomEvent.disableScrollPropagation(containerRef.current)
  }, [])

  const runSearch = async () => {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    setOpen(true)
    try {
      const r = await searchPhoton(q, 5)
      setResults(r)
    } catch {
      setError('Search failed — check your connection')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const choose = (r) => {
    map.flyTo([r.lat, r.lng], 16, { duration: 0.8 })
    setOpen(false)
  }

  const clear = () => {
    setQuery('')
    setResults([])
    setError(null)
    setOpen(false)
  }

  return (
    <div ref={containerRef} className="di-search">
      <div className="di-search__bar">
        <Search size={16} className="di-search__icon" />
        <input
          className="di-search__input"
          placeholder="Search a city or address…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              runSearch()
            }
          }}
          onFocus={() => results.length && setOpen(true)}
        />
        {query && (
          <button type="button" className="di-search__clear" onClick={clear} aria-label="Clear">
            <X size={14} />
          </button>
        )}
      </div>
      {open && (loading || error || results.length > 0) && (
        <div className="di-search__results">
          {loading && (
            <div className="di-search__status">
              <Loader2 size={14} className="di-spin" /> Searching…
            </div>
          )}
          {!loading && error && (
            <div className="di-search__status di-search__status--error">{error}</div>
          )}
          {!loading && !error && results.length === 0 && (
            <div className="di-search__status">No results</div>
          )}
          {!loading && !error &&
            results.map((r, i) => (
              <button
                key={i}
                type="button"
                className="di-search__result"
                onClick={() => choose(r)}
              >
                {r.label}
              </button>
            ))}
        </div>
      )}
    </div>
  )
}

// ── Public component ──────────────────────────────────────────────────
export default function MapView({
  intersections,
  pendingPin,
  onMapClick,
  // Stage 2 link props — all optional for backward-compat with any caller
  // that still uses the intersection-only API
  mode = 'intersections',
  armedId = null,
  links = [],
  selectedLinkId = null,
  onIntersectionClick,
  onSelectLink,
  // S2 editing (opt-in; S7/flow leaves these unset)
  editablePins = false,              // pins interactive → click selects
  selectedId = null,                 // selected intersection id (halo + actions)
  connectFromId = null,              // armed connect source id
  onConnectStart,                    // (id) => void — "Connect" on selected pin
  onDeleteIntersection,              // (id) => void — delete on selected pin
  // Stage 6 — flow-map props (optional)
  viewMode = 'edit',                 // 'edit' | 'pre' | 'post'
  showDirLabels = false,
  lastRun = null,
  overrides = { AM: {}, PM: {} },
  onTileLayerReady,                  // (L.TileLayer) => void
}) {
  // Basemap follows the active palette. The S1 picker sets data-theme on the
  // documentElement; a MutationObserver mirrors that into React state so the
  // TileLayer's url prop changes — react-leaflet calls setUrl() on the SAME
  // layer instance (no remove/add, no page reload), which keeps the instance
  // reference S7 hands to the PNG exporter valid across theme switches.
  const [theme, setTheme] = useState(currentTheme)
  useEffect(() => {
    const root = document.documentElement
    const obs = new MutationObserver(() => setTheme(currentTheme()))
    obs.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  const tileUrl = tileUrlForTheme(theme)

  return (
    <MapContainer
      center={[39, -96]}
      zoom={4}
      minZoom={2}
      worldCopyJump
      zoomControl={false}
      style={{ width: '100%', height: '100%' }}
    >
      <TileLayer
        url={tileUrl}
        attribution={TILE_ATTR}
        subdomains={['a', 'b', 'c', 'd']}
        crossOrigin="anonymous"
      />
      <TileLayerHandle onReady={onTileLayerReady} />
      <ZoomControl position="bottomright" />
      <ClickHandler onClick={onMapClick} />
      <LinkLayers
        intersections={intersections}
        links={links}
        mode={mode}
        viewMode={viewMode}
        selectedLinkId={selectedLinkId}
        onSelectLink={onSelectLink}
        lastRun={lastRun}
        overrides={overrides}
        editablePins={editablePins}
      />
      <FlowLabels
        intersections={intersections}
        links={links}
        viewMode={viewMode}
        showDirLabels={showDirLabels}
        lastRun={lastRun}
        overrides={overrides}
      />
      <MapLayers
        intersections={intersections}
        pendingPin={pendingPin}
        mode={mode}
        viewMode={viewMode}
        armedId={armedId}
        onIntersectionClick={onIntersectionClick}
        editablePins={editablePins}
        selectedId={selectedId}
        connectFromId={connectFromId}
        onConnectStart={onConnectStart}
        onDeleteIntersection={onDeleteIntersection}
      />
      <SearchBar />
    </MapContainer>
  )
}
