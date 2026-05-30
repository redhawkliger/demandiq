// Pure formatter for the S8 export summary's Convergence line. Lives in
// lib/ so it can be unit-tested without spinning up React.

// F8: convergenceThreshold is in veh (S5 stores 0.5; backend consumes 0.5 veh).
// A prior version multiplied by 100 and appended '%' — leftover from a model
// where the threshold was a fractional residual. The label is in veh, always.
export function convergenceLabel({ intCount, amConverged, pmConverged, convergenceThreshold }) {
  const tol = (Number.isFinite(convergenceThreshold) ? convergenceThreshold : 0.5).toFixed(2)
  return `AM ${amConverged}/${intCount} · PM ${pmConverged}/${intCount} (${tol} veh threshold)`
}
