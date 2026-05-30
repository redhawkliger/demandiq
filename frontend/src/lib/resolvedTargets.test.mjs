// buildResolvedRows tests — pure ESM, no runner:
//   node frontend/src/lib/resolvedTargets.test.mjs
//
// Locks down the F7 row math: smoothed flag fires at the right delta,
// reconPeak picks the max across AM and PM, suspicious flag only fires on
// Full-mode links with tiny resolved volumes.

import {
  buildResolvedRows,
  SUSPICIOUS_VOLUME_VEH,
  RECON_DELTA_NOTABLE_VEH,
} from './resolvedTargets.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

const allFull = () => 'Full'

// ── F7: smoothed fires when peak recon ≥ 20 veh ───────────────────────────
{
  const rows = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 690,
           raw_upstream: 402, raw_downstream: 690, reconciliation_delta: 288 }],
    pm: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 720,
           raw_upstream: 410, raw_downstream: 720, reconciliation_delta: 310 }],
    getMode: allFull,
  })
  ok(rows.length === 1, `merged to one row; got ${rows.length}`)
  ok(rows[0].amRecon === 288, `amRecon = 288; got ${rows[0].amRecon}`)
  ok(rows[0].pmRecon === 310, `pmRecon = 310; got ${rows[0].pmRecon}`)
  ok(rows[0].reconPeak === 310, `reconPeak = max(288, 310) = 310; got ${rows[0].reconPeak}`)
  ok(rows[0].smoothed === true, `smoothed = true when reconPeak ≥ 20`)
}

// ── F7: smoothed does NOT fire when both deltas are small ─────────────────
{
  const rows = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 700,
           raw_upstream: 700, raw_downstream: 695, reconciliation_delta: 5 }],
    pm: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 720,
           raw_upstream: 720, raw_downstream: 712, reconciliation_delta: 8 }],
    getMode: allFull,
  })
  ok(rows[0].reconPeak === 8, `reconPeak = 8 (max of 5, 8); got ${rows[0].reconPeak}`)
  ok(rows[0].smoothed === false, `smoothed = false when both deltas < 20`)
}

// ── F7 threshold boundary: exactly 20 fires; 19 does not ──────────────────
{
  const at = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 100, reconciliation_delta: 20 }],
    pm: [],
    getMode: allFull,
  })
  ok(at[0].smoothed === true, `delta exactly == ${RECON_DELTA_NOTABLE_VEH} → smoothed`)

  const under = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 100, reconciliation_delta: 19 }],
    pm: [],
    getMode: allFull,
  })
  ok(under[0].smoothed === false, `delta below threshold → not smoothed`)
}

// ── Suspicious flag: Full-mode + volume < SUSPICIOUS_VOLUME_VEH ───────────
{
  const rows = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 5,
           raw_upstream: 5, raw_downstream: 5, reconciliation_delta: 0 }],
    pm: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 6,
           raw_upstream: 6, raw_downstream: 6, reconciliation_delta: 0 }],
    getMode: allFull,
  })
  ok(rows[0].suspicious === true,
     `Full link with both periods < ${SUSPICIOUS_VOLUME_VEH} → suspicious`)
}

// ── Suspicious flag: Land Use mode is NEVER suspicious (even at tiny vol) ─
{
  const rows = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 5,
           raw_upstream: 5, raw_downstream: 5, reconciliation_delta: 0 }],
    pm: [],
    getMode: () => 'Land Use',
  })
  ok(rows[0].suspicious === false,
     `non-Full mode must not be flagged suspicious; got ${rows[0].suspicious}`)
}

// ── AM-only link (no PM match) handles missing-PM gracefully ──────────────
{
  const rows = buildResolvedRows({
    am: [{ fromNum: 1, toNum: 2, direction: 'NB', volume: 500,
           raw_upstream: 480, raw_downstream: 500, reconciliation_delta: 20 }],
    pm: [],     // no PM data
    getMode: allFull,
  })
  ok(rows[0].p === null, `p (PM match) is null when no PM entry exists`)
  ok(rows[0].pmRecon === 0, `pmRecon defaults to 0 when no PM match`)
  ok(rows[0].reconPeak === 20, `reconPeak = 20 (AM only)`)
  ok(rows[0].smoothed === true, `smoothed fires from AM alone when ≥ threshold`)
}

// ── Empty inputs return empty array ──────────────────────────────────────
{
  ok(buildResolvedRows({ am: [], pm: [], getMode: allFull }).length === 0, 'empty AM → no rows')
  ok(buildResolvedRows({ am: null, pm: null, getMode: allFull }).length === 0, 'null inputs tolerated')
}

console.log(`\n  ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
