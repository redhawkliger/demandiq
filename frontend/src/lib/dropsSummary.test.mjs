// dropsSummary tests — pure ESM, no test runner required:
//   node frontend/src/sessions/dropsSummary.test.mjs
//
// Anchored by the bug class that shipped to main in commit f971f14 and was
// caught only by manual eyeball: dropsSummary's `largest` comparator read
// `.delta` on an object whose property was actually `.value`, so the first
// negative-delta entry encountered always won and the rendered hero
// claimed "largest -5 veh" when reality was "-95 veh".

import { dropsSummary, MAJOR_DROP_THRESHOLD_VEH } from '../lib/dropsSummary.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// ── Bug-class guard: largest = most-negative delta, regardless of order ────
{
  // Mixed positive and negative; smallest negative listed first to expose the
  // .delta-vs-.value mistake (first-negative-wins would pick -5).
  const review = {
    AM: [
      { int_num: 1, movement: 'NBT', raw: 480, balanced: 475, delta: -5 },
      { int_num: 4, movement: 'EBT', raw: 180, balanced: 140, delta: -40 },
      { int_num: 6, movement: 'EBT', raw: 130, balanced: 35,  delta: -95 },
      { int_num: 2, movement: 'WBT', raw: 280, balanced: 285, delta: +5  },
    ],
    PM: [],
  }
  const r = dropsSummary(review)
  ok(r.AM.largest && r.AM.largest.value === -95,
     `AM.largest.value = -95 (most negative); got ${r.AM.largest?.value}`)
  ok(r.AM.largest && r.AM.largest.intNum === 6,
     `AM.largest.intNum = 6; got ${r.AM.largest?.intNum}`)
  ok(r.AM.largest && r.AM.largest.mv === 'EBT',
     `AM.largest.mv = 'EBT'; got ${r.AM.largest?.mv}`)
}

// ── count = number of negative-delta entries ───────────────────────────────
{
  const review = {
    AM: [
      { int_num: 1, movement: 'NBT', raw: 1, balanced: 0,  delta: -1 },
      { int_num: 2, movement: 'NBT', raw: 1, balanced: 0,  delta: -1 },
      { int_num: 3, movement: 'NBT', raw: 1, balanced: 5,  delta: +4 },   // not a drop
      { int_num: 4, movement: 'NBT', raw: 1, balanced: 1,  delta:  0 },   // not a drop
    ],
    PM: [],
  }
  const r = dropsSummary(review)
  ok(r.AM.count === 2, `AM.count = 2; got ${r.AM.count}`)
  ok(r.PM.count === 0, `PM.count = 0; got ${r.PM.count}`)
}

// ── major/minor split at MAJOR_DROP_THRESHOLD_VEH (= 40) ──────────────────
{
  const review = {
    AM: [
      { int_num: 1, movement: 'EBT', raw: 100, balanced: 65,  delta: -35 },  // minor (35 < 40)
      { int_num: 2, movement: 'EBT', raw: 100, balanced: 60,  delta: -40 },  // major (≥ 40)
      { int_num: 3, movement: 'EBT', raw: 100, balanced: 50,  delta: -50 },  // major
    ],
    PM: [],
  }
  const r = dropsSummary(review)
  ok(MAJOR_DROP_THRESHOLD_VEH === 40, `threshold is 40; got ${MAJOR_DROP_THRESHOLD_VEH}`)
  ok(r.AM.major === 2, `AM.major = 2 (deltas at -40 and -50); got ${r.AM.major}`)
  ok(r.AM.minor === 1, `AM.minor = 1 (delta at -35); got ${r.AM.minor}`)
}

// ── majorInts collects distinct ints with a major drop, sorted ascending ──
{
  const review = {
    AM: [
      { int_num: 6, movement: 'EBT', raw: 1, balanced: 0,  delta: -95 },   // major @ Int 6
      { int_num: 4, movement: 'EBT', raw: 1, balanced: 0,  delta: -40 },   // major @ Int 4
      { int_num: 4, movement: 'WBT', raw: 1, balanced: 0,  delta: -50 },   // major @ Int 4 (dupe)
      { int_num: 5, movement: 'EBT', raw: 1, balanced: 0,  delta: -45 },   // major @ Int 5
      { int_num: 1, movement: 'NBT', raw: 1, balanced: 0,  delta: -5 },    // minor — excluded
    ],
    PM: [],
  }
  const r = dropsSummary(review)
  ok(JSON.stringify(r.AM.majorInts) === '[4,5,6]',
     `AM.majorInts = [4,5,6] (sorted, deduped); got ${JSON.stringify(r.AM.majorInts)}`)
}

// ── Empty / null review tolerated ─────────────────────────────────────────
{
  const r = dropsSummary({ AM: [], PM: [] })
  ok(r.AM.count === 0 && r.AM.major === 0 && r.AM.minor === 0 && r.AM.largest === null,
     `empty review: AM fields all zero / largest null; got ${JSON.stringify(r.AM)}`)

  const r2 = dropsSummary(null)
  ok(r2.AM.count === 0 && r2.AM.largest === null,
     `null review: AM safe defaults; got ${JSON.stringify(r2.AM)}`)
}

console.log(`\n  ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
