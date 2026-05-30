// tileUrlForTheme tests — pure ESM, no runner:
//   node frontend/src/lib/themeTiles.test.mjs
//
// Locks the Phase 4 contract: Sunshine → Positron, everything else (incl. the
// no-attribute / night-traffic default) → Voyager. A future tile-template edit
// or a typo'd theme name would regress the basemap silently otherwise.

import { tileUrlForTheme } from './themeTiles.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

const VOYAGER  = 'voyager'
const POSITRON = 'positron'

// ── Sunshine is the ONLY light theme → Positron ──────────────────────────
ok(tileUrlForTheme('sunshine').includes(POSITRON), 'sunshine → positron')
ok(!tileUrlForTheme('sunshine').includes(VOYAGER), 'sunshine is not voyager')

// ── Night Traffic → Voyager ──────────────────────────────────────────────
ok(tileUrlForTheme('night-traffic').includes(VOYAGER), 'night-traffic → voyager')

// ── Default / unknown / empty all fall back to Voyager (never blank map) ──
ok(tileUrlForTheme('').includes(VOYAGER), 'empty string → voyager')
ok(tileUrlForTheme('totally-unknown').includes(VOYAGER), 'unknown theme → voyager')

// ── Both templates carry the CARTO {s}/{z}/{x}/{y} placeholders ──────────
for (const t of ['sunshine', 'night-traffic']) {
  const u = tileUrlForTheme(t)
  ok(u.includes('{s}') && u.includes('{z}') && u.includes('{x}') && u.includes('{y}'),
    `${t} url keeps tile placeholders`)
}

console.log(`themeTiles: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
