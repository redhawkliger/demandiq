// theme normalization tests — pure ESM, no runner:
//   node frontend/src/lib/theme.test.mjs
//
// Locks the Phase 5 contract: the picker and the boot path must never apply an
// invalid data-theme. A stale id left in localStorage by an older build, a
// null (never set), or a typo must all resolve to the dark default — not blank.

import { normalizeTheme, DEFAULT_THEME, THEMES } from './theme.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// ── Known ids pass through untouched ─────────────────────────────────────
ok(normalizeTheme('night-traffic') === 'night-traffic', 'night-traffic passes through')
ok(normalizeTheme('sunshine') === 'sunshine', 'sunshine passes through')

// ── Anything unknown falls back to the default (never undefined/blank) ────
ok(normalizeTheme(null) === DEFAULT_THEME, 'null → default')
ok(normalizeTheme(undefined) === DEFAULT_THEME, 'undefined → default')
ok(normalizeTheme('') === DEFAULT_THEME, 'empty string → default')
ok(normalizeTheme('midnight') === DEFAULT_THEME, 'stale/unknown id → default')

// ── The default is itself a real theme ───────────────────────────────────
ok(THEMES.some((t) => t.id === DEFAULT_THEME), 'DEFAULT_THEME is a defined theme')

// ── Exactly the two kickoff themes, each fully described + swatched ───────
ok(THEMES.length === 2, 'two themes defined')
for (const t of THEMES) {
  ok(t.id && t.label && t.blurb, `${t.id || '?'} has id/label/blurb`)
  ok(t.swatch && t.swatch.bg && t.swatch.surface && t.swatch.accent,
    `${t.id || '?'} has a full preview swatch`)
}

console.log(`theme: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
