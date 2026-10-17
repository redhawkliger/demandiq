// Theme-aware CARTO basemap tiles.
//
// The corridor map's basemap follows the active palette (data-theme on the
// documentElement, set by the S1 picker):
//   night-traffic    (dark, default) → Voyager  (warm, muted dark labels)
//   sunshine         (light)         → Positron (clean light)
//   signal-flow      (dark)          → Voyager
//   signal-flow-day  (light)         → Positron
//
// Shared by two consumers so they never disagree:
//   - MapView.jsx        — the live map; swaps tiles on theme change.
//   - lib/flowMapExport  — restores the live map to THESE tiles after the
//                          PNG capture's temporary light-tile swap.
// Both share one attribution string (CARTO requires OSM + CARTO credit).

export const TILE_ATTR =
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, and the GIS user community'

// Esri's Gray Canvas pair, which needs no API key. CARTO's raster CDN stopped
// serving real tiles without one: the old basemaps.cartocdn.com URLs still
// answer 200, but with a 2 KB "API KEY REQUIRED" watermark, so the map looked
// broken rather than failing loudly.
//
// Two gotchas baked into these URLs:
//  - Esri orders the path {z}/{y}/{x}, NOT the usual {z}/{x}/{y}. Swapping them
//    yields a map that renders fine and shows the wrong part of the world.
//  - There are no {s} subdomains and no {r} retina variant, so both placeholders
//    are gone and callers must not pass a `subdomains` prop.
const ESRI = 'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas'
const DARK_URL  = `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`
const LIGHT_URL = `${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`

// Gray Canvas has imagery through z16 and returns a 2.5 KB "Map data not yet
// available" placeholder above it — verified at a real project location, both
// styles. Pass this as the TileLayer's maxNativeZoom so Leaflet upscales z16
// past that point (slightly soft) instead of requesting tiles that don't exist
// and painting that placeholder across an intersection view.
export const TILE_MAX_NATIVE_ZOOM = 16

// The active theme name from the documentElement. Defaults to 'night-traffic'
// to mirror themes.css's bare :root block, which renders the dark palette when
// no data-theme attribute is present (app boot before the picker runs).
export function currentTheme() {
  if (typeof document === 'undefined') return 'night-traffic'
  return document.documentElement.getAttribute('data-theme') || 'night-traffic'
}

// Light palettes get Positron; everything else (including the no-attribute
// default) gets Voyager. Listed explicitly rather than tested against a single
// id so adding a light theme is one entry here — the previous `=== 'sunshine'`
// test silently handed dark tiles to any new light palette.
// Takes an explicit theme so it stays pure and testable; defaults to reading
// the live attribute for call-site convenience.
const LIGHT_THEMES = new Set(['sunshine', 'signal-flow-day'])

export function tileUrlForTheme(theme = currentTheme()) {
  return LIGHT_THEMES.has(theme) ? LIGHT_URL : DARK_URL
}
