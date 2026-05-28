import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Search, X, Loader2 } from 'lucide-react'
import { searchPhoton } from '../lib/photon'
import { buildLinkFlows, fmtPair } from '../lib/flowMap'

const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

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

const numberedIcon = (num, { armed = false, linkable = false } = {}) =>
  L.divIcon({
    className: `di-pin${armed ? ' di-pin--armed' : ''}${linkable ? ' di-pin--linkable' : ''}`,
    html: `<div class="di-pin__num">${num}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  })

// Link polyline colors — direction-coded. EB/WB blue (matches the accent
// token already used elsewhere), NB/SB amber (matches the warning/needs-volumes
// token so the two existing UI colors do double duty).
const LINK_COLORS = { 'EB/WB': '#0A84FF', 'NB/SB': '#FFB627' }

const pendingIcon = L.divIcon({
  className: 'di-pin',
  html: '<div class="di-pin__pending"></div>',
  iconSize: [32, 32],
  iconAnchor: [16, 16],
})

// ── Map click → orchestrator ──────────────────────────────────────────
function ClickHandler({ onClick }) {
  useMapEvents({ click: (e) => onClick(e.latlng) })
  return null
}

// ── Imperative layer manager ──────────────────────────────────────────
// `mode` controls interactivity:
//   'intersections' → existing behavior (non-interactive pins, dashed corridor)
//   'links'         → pins are clickable to arm/connect; dashed corridor hidden
//                     to avoid visual confusion with explicit link polylines
function MapLayers({ intersections, pendingPin, mode, viewMode, armedId, onIntersectionClick }) {
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
      const armed = armedId === it.id
      const m = L.marker([it.lat, it.lng], {
        icon: numberedIcon(it.num, { armed, linkable }),
        interactive: linkable,                 // only clickable in link mode
        keyboard: false,
      }).addTo(map)
      if (linkable && onIntersectionClick) {
        m.on('click', (e) => {
          L.DomEvent.stopPropagation(e)        // don't bubble to map (no new pin)
          onIntersectionClick(it.id)
        })
      }
      markersRef.current.push(m)
    })
    const isFlow = viewMode === 'pre' || viewMode === 'post'
    if (mode !== 'links' && !isFlow && intersections.length >= 2) {
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
  }, [intersections, mode, viewMode, armedId, onIntersectionClick, map])

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
  intersections, links, mode, viewMode,
  selectedLinkId, onSelectLink,
  lastRun, overrides,
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
      if (!from || !to) continue  // orphaned link (e.g. intersection deleted) — skip

      let color
      if (isFlow) {
        color = flowsByLinkId.get(link.id)?.polyColor || '#6B7280'
      } else {
        color = LINK_COLORS[link.direction] || '#0A84FF'
      }
      const selected = link.id === selectedLinkId
      const interactive = mode === 'links' || isFlow
      const polyline = L.polyline(
        [[from.lat, from.lng], [to.lat, to.lng]],
        {
          color,
          weight: selected ? 5 : 3.5,
          opacity: selected ? 1 : 0.9,
          interactive,
          pane: 'overlayPane',     // below markerPane → pins stay clickable
        }
      ).addTo(map)
      if (interactive && onSelectLink) {
        polyline.on('click', (e) => {
          L.DomEvent.stopPropagation(e)
          const pt = map.latLngToContainerPoint(e.latlng)
          onSelectLink(link.id, { x: pt.x, y: pt.y })
        })
      }
      linesRef.current.push(polyline)
    }
  }, [intersections, links, mode, viewMode, isFlow, selectedLinkId, onSelectLink, lastRun, overrides, map])

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
  // Stage 6 — flow-map props (optional)
  viewMode = 'edit',                 // 'edit' | 'pre' | 'post'
  showDirLabels = false,
  lastRun = null,
  overrides = { AM: {}, PM: {} },
  onTileLayerReady,                  // (L.TileLayer) => void
}) {
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
        url={TILE_URL}
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
      />
      <SearchBar />
    </MapContainer>
  )
}
