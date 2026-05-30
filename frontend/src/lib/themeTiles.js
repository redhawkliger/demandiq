// Theme-aware CARTO basemap tiles.
//
// The corridor map's basemap follows the active palette (data-theme on the
// documentElement, set by the S1 picker):
//   night-traffic (dark, default) → Voyager  (warm, muted dark labels)
//   sunshine      (light)         → Positron (clean light)
//
// Shared by two consumers so they never disagree:
//   - MapView.jsx        — the live map; swaps tiles on theme change.
//   - lib/flowMapExport  — restores the live map to THESE tiles after the
//                          PNG capture's temporary light-tile swap.
// Both share one attribution string (CARTO requires OSM + CARTO credit).

export const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

const VOYAGER_URL  = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png'
const POSITRON_URL = 'https://{s}.basemaps.cartocdn.com/rastertiles/positron/{z}/{x}/{y}{r}.png'

// The active theme name from the documentElement. Defaults to 'night-traffic'
// to mirror themes.css's bare :root block, which renders the dark palette when
// no data-theme attribute is present (app boot before the picker runs).
export function currentTheme() {
  if (typeof document === 'undefined') return 'night-traffic'
  return document.documentElement.getAttribute('data-theme') || 'night-traffic'
}

// Sunshine is the only light palette → Positron. Everything else (including the
// no-attribute default) → Voyager. Takes an explicit theme so it stays pure and
// testable; defaults to reading the live attribute for call-site convenience.
export function tileUrlForTheme(theme = currentTheme()) {
  return theme === 'sunshine' ? POSITRON_URL : VOYAGER_URL
}
