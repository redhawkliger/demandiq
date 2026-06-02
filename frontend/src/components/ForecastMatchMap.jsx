import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import L from 'leaflet'
import { TILE_ATTR, currentTheme, tileUrlForTheme } from '../lib/themeTiles'

// Match-review map: project intersection pins + the matched SANDAG network links,
// colored by leg status. Reuses the app's leaflet/tile/pin infrastructure but
// stays separate from MapView (which only draws intersection-to-intersection
// corridor lines, not network-link geometry).
//
// Status colors mirror the Signal palette (themes.css) — inline hex because a
// canvas/SVG stroke can't resolve a CSS var. Green matched / amber ambiguous /
// red unmatched / grey absent — literally traffic signals.
const STATUS_COLOR = {
  matched: '#22C55E',
  ambiguous: '#F4B400',
  unmatched: '#EF4444',
  absent: '#6B7280',
}
const DIRS = ['NB', 'SB', 'EB', 'WB']

function MatchLayers({ intersections, matches, layer, activeNum, onPickIntersection }) {
  const map = useMap()
  const ref = useRef([])
  const fitRef = useRef(false)

  useEffect(() => {
    ref.current.forEach((l) => l.remove())
    ref.current = []

    const linksById = new Map((layer?.links ?? []).map((l) => [l.link_id, l]))
    // geometry is [[lng,lat],...] (project CRS); leaflet wants [lat,lng].
    const toLatLngs = (nl) => nl.geometry.map(([lng, lat]) => [lat, lng])

    for (const m of matches ?? []) {
      const isActive = m.intersection_num === activeNum
      // Bound links, colored by leg status.
      for (const d of DIRS) {
        const leg = m.legs?.[d]
        if (!leg?.link_id) continue
        const nl = linksById.get(leg.link_id)
        if (!nl) continue
        const poly = L.polyline(toLatLngs(nl), {
          color: STATUS_COLOR[leg.status] ?? '#6B7280',
          weight: isActive ? 5 : 3,
          opacity: isActive ? 1 : 0.7,
          interactive: false,
          pane: 'overlayPane',
        }).addTo(map)
        ref.current.push(poly)
      }
      // Unbound links (ramps/frontage) — faint dashed grey, informational.
      for (const u of m.unbound_links ?? []) {
        const nl = linksById.get(u.link_id)
        if (!nl) continue
        const poly = L.polyline(toLatLngs(nl), {
          color: '#6B7280',
          weight: 1.5,
          opacity: isActive ? 0.5 : 0.25,
          dashArray: '4, 5',
          interactive: false,
          pane: 'overlayPane',
        }).addTo(map)
        ref.current.push(poly)
      }
    }

    for (const it of intersections) {
      const isActive = it.num === activeNum
      const icon = L.divIcon({
        className: `di-pin${isActive ? ' di-pin--selected' : ''}`,
        html: `<div class="di-pin__num">${it.num}</div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      })
      const mk = L.marker([it.lat, it.lng], { icon, keyboard: false }).addTo(map)
      mk.on('click', () => onPickIntersection?.(it.num))
      ref.current.push(mk)
    }
  }, [intersections, matches, layer, activeNum, onPickIntersection, map])

  useEffect(() => {
    if (fitRef.current || intersections.length === 0) return
    fitRef.current = true
    map.fitBounds(L.latLngBounds(intersections.map((it) => [it.lat, it.lng])), {
      padding: [70, 70],
      maxZoom: 17,
    })
  }, [map, intersections])

  useEffect(() => () => { ref.current.forEach((l) => l.remove()) }, [])
  return null
}

export default function ForecastMatchMap({ intersections, matches, layer, activeNum, onPickIntersection }) {
  const [theme, setTheme] = useState(currentTheme)
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(currentTheme()))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])

  return (
    <MapContainer
      center={[32.72, -117.1]}
      zoom={12}
      zoomControl={false}
      style={{ width: '100%', height: '100%' }}
    >
      <TileLayer
        url={tileUrlForTheme(theme)}
        attribution={TILE_ATTR}
        subdomains={['a', 'b', 'c', 'd']}
        crossOrigin="anonymous"
      />
      <ZoomControl position="bottomright" />
      <MatchLayers
        intersections={intersections}
        matches={matches}
        layer={layer}
        activeNum={activeNum}
        onPickIntersection={onPickIntersection}
      />
    </MapContainer>
  )
}
