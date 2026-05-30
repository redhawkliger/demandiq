// computeHeroState tests — pure ESM, no runner:
//   node frontend/src/lib/heroState.test.mjs
//
// Anchored by the F1 bug class — the hero used to paint 'ok' green on a
// corridor where the backend silently dropped every link, because the
// happy-path branch was checked before the link-resolution-skipped guard.

import { computeHeroState } from './heroState.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// ── F1 bug class: silent link-resolution-skipped MUST NOT show green ──────
{
  // All other signals say "perfect": converged + conserved + no drops.
  // Without the F1 guard this would be 'ok'. With the guard it's 'fail'.
  const state = computeHeroState({
    hasResults: true,
    linkResolutionSkipped: true,
    allConverged: true,
    allConserved: true,
    hasDrops: false,
  })
  ok(state === 'fail',
     `linkResolutionSkipped=true must override happy signals → 'fail'; got '${state}'`)
}

// ── No run yet → 'idle' ──────────────────────────────────────────────────
{
  const state = computeHeroState({
    hasResults: false,
    linkResolutionSkipped: false,
    allConverged: false,    // garbage post-run signals — ignored when no run
    allConserved: false,
    hasDrops: true,
  })
  ok(state === 'idle', `no results → 'idle'; got '${state}'`)
}

// ── Some intersection IPF hit max_iter → 'fail' ──────────────────────────
{
  const state = computeHeroState({
    hasResults: true,
    linkResolutionSkipped: false,
    allConverged: false,
    allConserved: true,
    hasDrops: false,
  })
  ok(state === 'fail', `!allConverged → 'fail'; got '${state}'`)
}

// ── Link conservation off → 'warn' ───────────────────────────────────────
{
  const state = computeHeroState({
    hasResults: true,
    linkResolutionSkipped: false,
    allConverged: true,
    allConserved: false,
    hasDrops: false,
  })
  ok(state === 'warn', `!allConserved → 'warn'; got '${state}'`)
}

// ── Drops present → 'warn' (even when conservation is clean) ──────────────
{
  const state = computeHeroState({
    hasResults: true,
    linkResolutionSkipped: false,
    allConverged: true,
    allConserved: true,
    hasDrops: true,
  })
  ok(state === 'warn', `hasDrops → 'warn'; got '${state}'`)
}

// ── Everything clean → 'ok' (the happy path) ──────────────────────────────
{
  const state = computeHeroState({
    hasResults: true,
    linkResolutionSkipped: false,
    allConverged: true,
    allConserved: true,
    hasDrops: false,
  })
  ok(state === 'ok', `all clean → 'ok'; got '${state}'`)
}

console.log(`\n  ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
