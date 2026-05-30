// Pure helpers for the S6 drops banner. Lives in lib/ (not in
// S6_RunAnalysis.jsx) so it can be imported by Node-based tests without a
// JSX loader. No React, no DOM.

// F5 — Drops banner severity bucketing. A "drop" is `balanced - raw < 0`.
// Under Larger method most drops are routine sub-5-veh wobble from
// post-IPF rounding; a handful are the real engineering concern. Splitting
// counts at MAJOR_DROP_THRESHOLD_VEH gives the engineer the right summary
// at a glance instead of a single count that hides the severity.
export const MAJOR_DROP_THRESHOLD_VEH = 40

// Summarize drops per-period from movementsReview.
// Returns { AM:{count, major, minor, largest:{value,intNum,mv}, majorInts}, PM:{...} }.
export function dropsSummary(review) {
  const out = { AM: null, PM: null }
  for (const period of ['AM', 'PM']) {
    const arr = review?.[period] ?? []
    let count = 0
    let major = 0
    let minor = 0
    let largest = null
    const majorIntsSet = new Set()
    for (const r of arr) {
      if (r.delta < 0) {
        count++
        if (Math.abs(r.delta) >= MAJOR_DROP_THRESHOLD_VEH) {
          major++
          majorIntsSet.add(r.int_num)
        } else {
          minor++
        }
        if (!largest || r.delta < largest.value) {
          largest = { value: r.delta, intNum: r.int_num, mv: r.movement }
        }
      }
    }
    const sortedInts = Array.from(majorIntsSet).sort((a, b) => a - b)
    out[period] = { count, major, minor, largest, majorInts: sortedInts }
  }
  return out
}

// Render an int number array as a human range, compressing consecutive runs:
// [4,5,6] → 'Int 4–6'; [4,6,9] → 'Int 4, 6, 9'; [] → ''; [7] → 'Int 7'.
export function formatIntRange(nums) {
  if (nums.length === 0) return ''
  if (nums.length === 1) return `Int ${nums[0]}`
  const runs = []
  let runStart = nums[0]
  let prev = nums[0]
  for (let i = 1; i < nums.length; i++) {
    if (nums[i] === prev + 1) { prev = nums[i]; continue }
    runs.push(runStart === prev ? `${runStart}` : `${runStart}–${prev}`)
    runStart = nums[i]; prev = nums[i]
  }
  runs.push(runStart === prev ? `${runStart}` : `${runStart}–${prev}`)
  return `Int ${runs.join(', ')}`
}
