// frontend/src/lib/reviewMovements.js
//
// Pure derivations for the S6 Review Movements detail view.
// Every export is a pure function of (lastRun, intNum, period). Components
// render these outputs and hold NO logic — see docs/adr/0001-*.
//
// The reconciliation verdict is a READ-ONLY function of the solver's own
// intConverged + finalResidual. It NEVER re-derives in/out movement sums
// (that would be a tautology AND could disagree with the solver — ADR 0001 §0).

// ADR 0001 pin #2 — exact caption. The intersection total always reconciles,
// so the gap is the worst leg vs its TARGET, never "unaccounted".
// Precondition: gap > 0 (callers handle gap === 0 via the "balanced" branch).
export function gapCaption(gap) {
  return `worst leg off its target by ${gap} veh`
}

export function reconciliationVerdict(lastRun, intNum, period) {
  const converged = lastRun?.intConverged?.[period]?.[intNum] === true
  const gap = Math.round(lastRun?.finalResidual?.[period]?.[intNum] ?? 0)
  if (!converged) return { state: 'did-not-converge', status: 'red', gap, label: 'did not converge' }
  if (gap === 0)  return { state: 'balanced', status: 'green', gap: 0, label: 'balanced' }
  return { state: 'gap', status: 'amber', gap, label: gapCaption(gap) }
}

export function changelog(lastRun, intNum, period) {
  const rows = (lastRun?.movementsReview?.[period] ?? []).filter(m => m.int_num === intNum)
  const changed = rows.filter(m => m.delta !== 0)
    .slice().sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
  const unchanged = rows.filter(m => m.delta === 0)
  const adjustedCount = changed.length
  const totalCount = rows.length
  const headline = adjustedCount === 0
    ? 'No movements changed — raw counts already balanced'
    : `${adjustedCount} of ${totalCount} adjusted`
  return { changed, unchanged, adjustedCount, totalCount, headline }
}

const METHOD_COPY = {
  larger:  { label: 'Larger',  meaning: 'each shared link takes the larger of its two raw counts' },
  average: { label: 'Average', meaning: 'each shared link takes the mean of its two raw counts' },
}
export function methodLabel(lastRun) {
  const key = (lastRun?.method ?? lastRun?.config?.linkResolution ?? 'larger')
  return METHOD_COPY[key] ?? METHOD_COPY.larger
}

// ADR 0001 pin #1 — the tolerance that actually governs intConverged is the
// per-intersection IPF Level-2 tol, hardcoded in backend/balancer.py:1161.
// It is NOT config.convergenceThreshold (a different Level-1 value). The
// Details modal is a defend-the-work surface, so it must show the real number.
export const IPF_TOLERANCE_VEH = 0.01

export function detailsModalData(lastRun, intNum, period) {
  const flags = (lastRun?.qcFlags ?? []).filter(
    f => f.int === intNum && (f.period == null || f.period === period),
  )
  const resolvedLinks = (lastRun?.resolvedLinks?.[period] ?? []).filter(
    l => l.fromNum === intNum || l.toNum === intNum,
  )
  return {
    iterations: lastRun?.iterations?.[period]?.[intNum],
    finalResidual: lastRun?.finalResidual?.[period]?.[intNum],
    converged: lastRun?.intConverged?.[period]?.[intNum] === true,
    toleranceVeh: IPF_TOLERANCE_VEH,
    maxIterations: lastRun?.config?.maxIterations,
    flags,
    resolvedLinks,
  }
}

// Corridor navigation. `count` is the length of the intersections array in its
// GIVEN order (= corridor order). NEVER sort by int number — see memory
// corridor-order-invariant. Callers pass the array index, not the int num.
export function stepIndex(count, currentIndex, dir) {
  return Math.max(0, Math.min(count - 1, currentIndex + dir))
}

// Two distinct color systems, enforced as disjoint class namespaces:
//  - STATUS  → traffic-light signal palette (good/attention/bad)
//  - DELTA   → direction (a number went up vs down); NOT good vs bad
export function statusClass(status) { return `di-rm-status--${status}` }
export function deltaClass(delta)  { return `di-rm-delta--${delta >= 0 ? 'up' : 'down'}` }
