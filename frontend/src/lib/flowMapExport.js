// Stage 6 — PNG export for the balance flow map.
//
// Renders the live Leaflet map to a 2×-DPI PNG, with:
//   - tiles temporarily swapped to a light-themed basemap (report-ready)
//   - a title overlay (top-left) and legend overlay (bottom-right)
//
// CARTO tile servers do send CORS headers, so html2canvas captures them
// directly when the TileLayer is created with crossOrigin: 'anonymous'.
// (See MapView.jsx where the TileLayer is configured.)

import html2canvas from 'html2canvas'
import { IMBALANCE_COLORS } from './flowMap'
import { tileUrlForTheme } from './themeTiles'

const LIGHT_TILE_URL = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'

// Wait for all visible tile <img> elements in the container to fire `load`
// (or fail) — html2canvas would otherwise capture mid-swap.
function waitForTilesLoaded(container, timeoutMs = 4000) {
  return new Promise((resolve) => {
    const tiles = Array.from(container.querySelectorAll('.leaflet-tile'))
    const pending = tiles.filter((t) => !t.complete)
    if (pending.length === 0) return resolve()
    let remaining = pending.length
    const done = () => { remaining -= 1; if (remaining <= 0) finish() }
    const finish = () => {
      pending.forEach((t) => {
        t.removeEventListener('load', done)
        t.removeEventListener('error', done)
      })
      clearTimeout(t0)
      resolve()
    }
    pending.forEach((t) => {
      t.addEventListener('load', done, { once: true })
      t.addEventListener('error', done, { once: true })
    })
    const t0 = setTimeout(finish, timeoutMs)
  })
}

// Inject a temporary title + legend overlay into the map container. The
// overlay is removed after capture so it doesn't persist in the live UI.
function injectOverlays({ container, title, viewType, method, dateStr }) {
  const title_el = document.createElement('div')
  title_el.className = 'di-flow-export__title'
  title_el.style.cssText = [
    'position:absolute', 'top:14px', 'left:16px', 'z-index:9000',
    'background:rgba(255,255,255,0.92)', 'color:#1A1F2C',
    'padding:8px 14px', 'border-radius:6px',
    'font-family:ui-sans-serif,system-ui,sans-serif',
    'font-size:14px', 'font-weight:600',
    'box-shadow:0 2px 8px rgba(0,0,0,0.15)',
  ].join(';')
  title_el.textContent = `${title} — ${viewType} balance flow`
  container.appendChild(title_el)

  const legend = document.createElement('div')
  legend.className = 'di-flow-export__legend'
  legend.style.cssText = [
    'position:absolute', 'bottom:14px', 'right:14px', 'z-index:9000',
    'background:rgba(255,255,255,0.94)', 'color:#1A1F2C',
    'padding:10px 14px', 'border-radius:6px',
    'font-family:ui-sans-serif,system-ui,sans-serif',
    'font-size:11px', 'line-height:1.55',
    'box-shadow:0 2px 8px rgba(0,0,0,0.18)',
    'min-width:200px',
  ].join(';')
  const swatch = (hex, label) =>
    `<div style="display:flex;align-items:center;gap:6px;">
       <span style="display:inline-block;width:14px;height:4px;background:${hex};border-radius:2px;"></span>
       <span>${label}</span>
     </div>`
  legend.innerHTML = `
    <div style="font-weight:600;font-size:12px;margin-bottom:6px;">Legend</div>
    ${swatch(IMBALANCE_COLORS.green, 'Imbalance ≤ 5%')}
    ${swatch(IMBALANCE_COLORS.amber, '5–15%')}
    ${swatch(IMBALANCE_COLORS.red,   '&gt; 15%')}
    <div style="margin-top:6px;color:#4A5568;">Format: AM (PM)</div>
    ${method ? `<div style="color:#4A5568;">Method: ${method}</div>` : ''}
    <div style="color:#4A5568;">${dateStr}</div>
  `
  container.appendChild(legend)
  return () => {
    title_el.remove()
    legend.remove()
  }
}

// Public: swap to light tiles, wait for them to load, capture at 2×,
// restore the active theme's tiles, trigger download. The TileLayer ref is passed in
// from MapView so we don't have to reach into Leaflet internals here.
//
// Args:
//   tileLayer: the L.TileLayer instance (so we can change its URL template)
//   container: the .leaflet-container DOM element
//   meta:      { projectName, viewType ('Pre' | 'Post'), method, date }
//
// Caller is responsible for re-entering nothing during capture.
export async function exportFlowMapPNG({ tileLayer, container, meta }) {
  if (!tileLayer || !container) {
    throw new Error('exportFlowMapPNG: tileLayer and container are required')
  }
  // 1. Swap to light tiles
  tileLayer.setUrl(LIGHT_TILE_URL)
  await waitForTilesLoaded(container)
  // small extra frame so any in-progress paints settle
  await new Promise((r) => requestAnimationFrame(r))

  // 2. Inject overlays
  const dateStr = new Date(meta.date || Date.now()).toLocaleString()
  const removeOverlays = injectOverlays({
    container,
    title: meta.projectName || 'Project',
    viewType: meta.viewType || 'Post',
    method: meta.method,
    dateStr,
  })

  try {
    // 3. Capture at 2× DPI
    const canvas = await html2canvas(container, {
      useCORS: true,
      allowTaint: false,
      backgroundColor: '#FFFFFF',
      scale: 2,
      logging: false,
    })
    // 4. Trigger download
    const safe = (s) => String(s || '').replace(/[^a-z0-9]+/gi, '_').replace(/^_+|_+$/g, '')
    const stamp = new Date().toISOString().slice(0, 10)
    const filename = `${safe(meta.projectName) || 'project'}_${safe(meta.viewType) || 'flow'}_flow_map_${stamp}.png`
    await new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (!blob) return reject(new Error('canvas.toBlob returned null'))
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = filename
        document.body.appendChild(a)
        a.click()
        a.remove()
        URL.revokeObjectURL(url)
        resolve()
      }, 'image/png')
    })
  } finally {
    // 5. Always restore the live map's theme tiles + remove overlays.
    // Restore to whatever the active palette wants (Voyager / Positron), NOT a
    // hardcoded dark template — otherwise exporting on Sunshine would leave the
    // live map showing dark tiles until the next theme change.
    removeOverlays()
    tileLayer.setUrl(tileUrlForTheme())
  }
}
