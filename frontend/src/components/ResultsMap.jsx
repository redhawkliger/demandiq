import { useEffect, useRef } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const TILE_URL =
  'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

const numberedIcon = (num, selected = false) =>
  L.divIcon({
    className: 'di-pin',
    html: `<div class="di-pin__num${selected ? ' di-pin__num--selected' : ''}">${num}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  })

// Build popup HTML for one intersection in the current period + view mode.
function buildPopupHTML(it, period, viewMode) {
  const u = it.volumes?.[period] ?? {}
  const b = it.balanced?.[period] ?? {}
  const dirs = ['EB', 'WB', 'NB', 'SB'].filter(
    (d) => it.approaches?.[d]?.exists !== false
  )
  const rows = []
  for (const d of dirs) {
    for (const m of ['L', 'T', 'R']) {
      const key = `${d}${m}`
      const uCell = u[key]
      const bVal = b[key]
      const uVal = uCell?.value
      if (uVal == null && bVal == null) continue

      let cell
      if (viewMode === 'combined') {
        cell = `${uVal ?? 0} <span style="color:#9ea1aa">(${bVal ?? 0})</span>`
      } else if (viewMode === 'balanced') {
        cell = `${bVal ?? 0}`
      } else if (viewMode === 'unbalanced') {
        cell = `${uVal ?? 0}`
      } else {
        const d_ = (bVal ?? 0) - (uVal ?? 0)
        const color = d_ > 0 ? '#34D399' : d_ < 0 ? '#FF8B8B' : '#9ea1aa'
        const sign = d_ > 0 ? '+' : ''
        cell = `<span style="color:${color}">${sign}${d_}</span>`
      }
      rows.push(
        `<tr><td class="di-pop__mv">${key}</td><td class="di-pop__v">${cell}</td></tr>`
      )
    }
  }
  const safeName = String(it.name ?? '').replace(/[<>&"]/g, (c) =>
    ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c])
  )
  return `
    <div class="di-pop">
      <div class="di-pop__title">
        <span class="di-pop__num">${it.num}</span>${safeName}
      </div>
      ${rows.length === 0
        ? '<div class="di-pop__empty">No volumes for this period.</div>'
        : `<table class="di-pop__tbl"><tbody>${rows.join('')}</tbody></table>`}
    </div>
  `
}

// ── Imperative layer manager — three small effects to avoid the
// click→select→rebuild→popup-close race.
function ResultsLayers({ intersections, selectedId, onSelect, period, viewMode }) {
  const map = useMap()
  const markersById = useRef(new Map())
  const polylineRef = useRef(null)
  const initialFitRef = useRef(false)

  // Effect 1: build/rebuild markers + polyline when the intersection list changes.
  useEffect(() => {
    markersById.current.forEach((m) => m.remove())
    markersById.current = new Map()
    if (polylineRef.current) {
      polylineRef.current.remove()
      polylineRef.current = null
    }

    intersections.forEach((it) => {
      const m = L.marker([it.lat, it.lng], {
        icon: numberedIcon(it.num, it.id === selectedId),
      }).addTo(map)
      m.bindPopup(buildPopupHTML(it, period, viewMode), {
        className: 'di-pop-wrap',
        closeButton: false,
        offset: [0, -6],
      })
      m.on('click', () => onSelect(it.id))
      markersById.current.set(it.id, m)
    })

    if (intersections.length >= 2) {
      polylineRef.current = L.polyline(
        intersections.map((it) => [it.lat, it.lng]),
        { color: '#0A84FF', weight: 2.5, opacity: 0.85, dashArray: '6, 6', interactive: false }
      ).addTo(map)
    }
    // We intentionally omit selectedId / period / viewMode here — those are
    // handled by the next two effects without rebuilding markers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intersections, map])

  // Effect 2: when selectedId changes, swap each marker's icon. No rebuild =
  // open popups don't close, and the just-clicked pin keeps its popup open.
  useEffect(() => {
    markersById.current.forEach((m, id) => {
      const it = intersections.find((x) => x.id === id)
      if (!it) return
      m.setIcon(numberedIcon(it.num, id === selectedId))
    })
  }, [selectedId, intersections])

  // Effect 3: when period or viewMode changes, refresh popup content in place.
  useEffect(() => {
    markersById.current.forEach((m, id) => {
      const it = intersections.find((x) => x.id === id)
      if (!it) return
      m.setPopupContent(buildPopupHTML(it, period, viewMode))
    })
  }, [period, viewMode, intersections])

  // Initial fit-bounds (once)
  useEffect(() => {
    if (initialFitRef.current) return
    initialFitRef.current = true
    if (intersections.length > 0) {
      const bounds = L.latLngBounds(intersections.map((it) => [it.lat, it.lng]))
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16 })
    }
  }, [map, intersections])

  // Fly to selected (every time selection changes)
  useEffect(() => {
    if (!selectedId) return
    const it = intersections.find((x) => x.id === selectedId)
    if (it) map.flyTo([it.lat, it.lng], Math.max(map.getZoom(), 16), { duration: 0.5 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId])

  // Cleanup
  useEffect(() => {
    return () => {
      markersById.current.forEach((m) => m.remove())
      if (polylineRef.current) polylineRef.current.remove()
    }
  }, [])

  return null
}

function NorthArrow() {
  const containerRef = useRef(null)
  useEffect(() => {
    if (!containerRef.current) return
    L.DomEvent.disableClickPropagation(containerRef.current)
    L.DomEvent.disableScrollPropagation(containerRef.current)
  }, [])
  return (
    <div ref={containerRef} className="di-s7-north" aria-hidden="true">
      <svg viewBox="0 0 32 40" width="32" height="40">
        <polygon points="16,4 24,28 16,22 8,28" fill="#FFFFFF" stroke="#07080D" strokeWidth="1.4" strokeLinejoin="round" />
        <text x="16" y="38" textAnchor="middle" fontSize="10" fill="#FFFFFF" fontWeight="700">N</text>
      </svg>
    </div>
  )
}

export default function ResultsMap({
  intersections,
  selectedId,
  onSelect,
  period,
  viewMode,
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
      <TileLayer url={TILE_URL} attribution={TILE_ATTR} subdomains={['a', 'b', 'c', 'd']} />
      <ZoomControl position="bottomright" />
      <ResultsLayers
        intersections={intersections}
        selectedId={selectedId}
        onSelect={onSelect}
        period={period}
        viewMode={viewMode}
      />
      <NorthArrow />
    </MapContainer>
  )
}
