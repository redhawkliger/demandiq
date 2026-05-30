// Pure helpers for the S6 hero strip. Lives in lib/ so Node-based tests can
// import without a JSX loader (same pattern as lib/dropsSummary.js).

// Decide the hero color tier from the run's headline signals.
//
// Precedence (each step takes over from below):
//   1. !hasResults                  → 'idle'   (no run yet)
//   2. linkResolutionSkipped (F1)   → 'fail'   (backend silently dropped every
//                                              link OR rejected the payload —
//                                              must not paint green)
//   3. !allConverged                → 'fail'   (some intersection's IPF hit
//                                              max_iter)
//   4. !allConserved || hasDrops    → 'warn'   (run finished but link
//                                              conservation isn't clean, or
//                                              movements dropped below raw)
//   5. otherwise                    → 'ok'
//
// The whole point of F1+F4: a corridor with links configured but no resolved
// links MUST NOT show 'ok'. The order above guarantees that.
export function computeHeroState({
  hasResults,
  linkResolutionSkipped,
  allConverged,
  allConserved,
  hasDrops,
}) {
  if (!hasResults) return 'idle'
  if (linkResolutionSkipped) return 'fail'
  if (!allConverged) return 'fail'
  if (!allConserved || hasDrops) return 'warn'
  return 'ok'
}
