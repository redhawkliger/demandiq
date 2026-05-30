// Pure helpers for the S6 Resolved Link Targets card. Pulled out of
// S6_RunAnalysis.jsx so unit tests can import without a JSX loader.

// Sanity threshold: a Full-mode link with a resolved volume below this is
// almost certainly a missing/wrong raw count rather than a genuinely tiny link.
export const SUSPICIOUS_VOLUME_VEH = 10

// F7: reconciliation_delta = |raw_upstream - raw_downstream|. Below this the
// algorithm's smoothing is normal daily-count noise; above it, the engineer
// should know how much the algorithm hid (e.g. the audit fixture's planted
// 300-veh disagreement at Int 8↔9 used to silently resolve to delta=0).
export const RECON_DELTA_NOTABLE_VEH = 20

// Merge AM/PM resolved-link entries by (from, to, direction), compute per-row
// suspicious + smoothed flags. `getMode(fromNum, toNum)` is injected so this
// helper doesn't reach into the store.
//
// Returns rows of shape:
//   { a, p, mode, suspicious, amRecon, pmRecon, reconPeak, smoothed }
export function buildResolvedRows({ am, pm, getMode }) {
  const key = (r) => `${r.fromNum}|${r.toNum}|${r.direction}`
  const pmByKey = new Map((pm || []).map((r) => [key(r), r]))
  return (am || []).map((a) => {
    const p = pmByKey.get(key(a)) ?? null
    const mode = getMode(a.fromNum, a.toNum)
    const suspicious = mode === 'Full' && (
      (Number(a.volume) > 0 && Number(a.volume) < SUSPICIOUS_VOLUME_VEH) ||
      (p && Number(p.volume) > 0 && Number(p.volume) < SUSPICIOUS_VOLUME_VEH)
    )
    const amRecon = Number(a.reconciliation_delta ?? 0)
    const pmRecon = Number(p?.reconciliation_delta ?? 0)
    const reconPeak = Math.max(amRecon, pmRecon)
    const smoothed = reconPeak >= RECON_DELTA_NOTABLE_VEH
    return { a, p, mode, suspicious, amRecon, pmRecon, reconPeak, smoothed }
  })
}
