import { useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Search, X, Loader2 } from 'lucide-react'
import { searchPhoton } from '../lib/photon'

const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'

const numberedIcon = (num) =>
  L.divIcon({
    className: 'di-pin',
    html: `<div class="di-pin__num">${num}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  })

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
function MapLayers({ intersections, pendingPin }) {
  const map = useMap()
  const markersRef = useRef([])
  const polylineRef = useRef(null)
  const pendingRef = useRef(null)
  const initialFitRef = useRef(false)

  // Confirmed numbered markers + dashed corridor polyline
  useEffect(() => {
    markersRef.current.forEach((m) => m.remove())
    markersRef.current = []
    if (polylineRef.current) {
      polylineRef.current.remove()
      polylineRef.current = null
    }
    intersections.forEach((it) => {
      const m = L.marker([it.lat, it.lng], {
        icon: numberedIcon(it.num),
        interactive: false,
        keyboard: false,
      }).addTo(map)
      markersRef.current.push(m)
    })
    if (intersections.length >= 2) {
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
  }, [intersections, map])

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
export default function MapView({ intersections, pendingPin, onMapClick }) {
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
      <ClickHandler onClick={onMapClick} />
      <MapLayers intersections={intersections} pendingPin={pendingPin} />
      <SearchBar />
    </MapContainer>
  )
}
