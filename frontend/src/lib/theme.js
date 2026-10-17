// Global appearance theme — Night Traffic (dark, default) / Sunshine (light).
//
// This is ONE preference for the whole app, not per-project, so it lives in its
// own localStorage key (separate from 'demandiq:project') and is applied as the
// data-theme attribute on the documentElement. themes.css gates the palette on
// that attribute; MapView's MutationObserver swaps basemap tiles to match
// (see lib/themeTiles.js).

export const THEME_STORAGE_KEY = 'demandiq:theme'
export const DEFAULT_THEME = 'night-traffic'

export const THEMES = [
  {
    id: 'night-traffic',
    label: 'Night Traffic',
    blurb: 'Dark — easy on the eyes for late corridor work and projectors.',
    // Preview swatch (mirrors themes.css; can't use var() — those resolve to the
    // ACTIVE theme, but each card must show its OWN palette).
    swatch: { bg: '#0B0E12', surface: '#161A22', accent: '#60A5FA' },
  },
  {
    id: 'sunshine',
    label: 'Sunshine',
    blurb: 'Light — crisp for daytime desk work and report screenshots.',
    swatch: { bg: '#FAFAF9', surface: '#FFFFFF', accent: '#2563EB' },
  },
  {
    id: 'signal-flow',
    label: 'Signal Flow',
    blurb: 'Dark asphalt and Overpass type — the house theme shared with CrashIQ.',
    swatch: { bg: '#0D1013', surface: '#151A1F', accent: '#5AA2FF' },
  },
  {
    id: 'signal-flow-day',
    label: 'Signal Flow Day',
    blurb: 'The same house theme on fresh concrete, for daylight and printing.',
    swatch: { bg: '#ECEEF0', surface: '#FFFFFF', accent: '#1F5FAD' },
  },
]

const VALID = new Set(THEMES.map((t) => t.id))

// Pure: coerce any stored/raw value to a known theme id. null, undefined, '' or
// a stale id from an older build all fall back to the default — never undefined.
export function normalizeTheme(raw) {
  return VALID.has(raw) ? raw : DEFAULT_THEME
}

// The persisted preference (default if unset/corrupt). Safe before React mounts.
export function getStoredTheme() {
  try {
    return normalizeTheme(localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    return DEFAULT_THEME
  }
}

// Apply a theme to the live document AND persist it. setAttribute drives
// themes.css + the map-tile observer; returns the normalized id actually applied.
export function applyTheme(id) {
  const theme = normalizeTheme(id)
  document.documentElement.setAttribute('data-theme', theme)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    /* private mode / quota — attribute still applied for this session */
  }
  return theme
}

// Boot: reflect the stored preference onto the document WITHOUT re-persisting a
// default the user never chose. Call once before the first render.
export function initTheme() {
  const theme = getStoredTheme()
  document.documentElement.setAttribute('data-theme', theme)
  return theme
}
