// tileUrlForTheme tests — pure ESM, no runner:
//   node frontend/src/lib/themeTiles.test.mjs
//
// Locks the basemap contract: light themes get Esri's Light Gray Canvas,
// everything else (incl. the no-attribute / night-traffic default) gets Dark
// Gray Canvas. A tile-template edit or a typo'd theme name would otherwise
// regress the basemap silently — the failure mode is a map that still renders,
// just wrong, which no screenshot review reliably catches.

import { tileUrlForTheme, TILE_MAX_NATIVE_ZOOM } from './themeTiles.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

const DARK  = 'World_Dark_Gray_Base'
const LIGHT = 'World_Light_Gray_Base'

// ── Light themes → Light Gray Canvas ─────────────────────────────────────
for (const t of ['sunshine', 'signal-flow-day']) {
  ok(tileUrlForTheme(t).includes(LIGHT), `${t} → light canvas`)
  ok(!tileUrlForTheme(t).includes(DARK), `${t} is not the dark canvas`)
}

// ── Dark themes → Dark Gray Canvas ───────────────────────────────────────
for (const t of ['night-traffic', 'signal-flow']) {
  ok(tileUrlForTheme(t).includes(DARK), `${t} → dark canvas`)
  ok(!tileUrlForTheme(t).includes(LIGHT), `${t} is not the light canvas`)
}

// ── Default / unknown / empty fall back to dark (never a blank map) ──────
ok(tileUrlForTheme('').includes(DARK), 'empty string → dark canvas')
ok(tileUrlForTheme('totally-unknown').includes(DARK), 'unknown theme → dark canvas')

// ── Esri path order is {z}/{y}/{x}, NOT the usual {z}/{x}/{y} ────────────
// Swapping x and y yields a map that renders perfectly and shows the wrong
// place, so assert the order rather than mere presence.
for (const t of ['sunshine', 'night-traffic']) {
  const u = tileUrlForTheme(t)
  ok(u.endsWith('/{z}/{y}/{x}'), `${t} url uses Esri's z/y/x order`)
  // Esri serves no subdomains and no retina variant; leaving either placeholder
  // in would request a host that does not resolve.
  ok(!u.includes('{s}'), `${t} url has no {s} subdomain placeholder`)
  ok(!u.includes('{r}'), `${t} url has no {r} retina placeholder`)
}

// ── Gray Canvas has no imagery above z16 ─────────────────────────────────
// Above it Esri answers 200 with a 2.5 KB "Map data not yet available" image,
// so without this cap an intersection-level zoom paints that placeholder.
ok(TILE_MAX_NATIVE_ZOOM === 16, 'maxNativeZoom caps at Esri Gray Canvas data limit')

console.log(`themeTiles: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
