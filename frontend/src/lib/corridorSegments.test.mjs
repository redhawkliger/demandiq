// Regression for the S2/S7 corridor-topology divergence: the corridor must come
// from the explicit `links` graph, not array/numeric order.
//
// Run: node --test frontend/src/lib/corridorSegments.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildCorridorSegments } from './corridorSegments.js'

// Non-monotonic numbering: the corridor link is 4→2, with num-3 sitting
// NUMERICALLY between them (a spur, off the main line). Store/array order is
// num order (2,3,4) — the OLD S7 code drew 4→3 from that. The explicit link
// says 4→2. The helper must follow the link.
const intersections = [
  { id: 'a', num: 2, lat: 32.70, lng: -117.20 },
  { id: 'b', num: 3, lat: 32.71, lng: -117.05 }, // spur, numerically between
  { id: 'c', num: 4, lat: 32.70, lng: -117.10 },
]
const links = [
  { id: 'lnk1', fromId: 'c', toId: 'a', direction: 'EB/WB' }, // num 4 → num 2
]

test('corridor segment follows the explicit link (4→2), not numeric order (4→3)', () => {
  const segs = buildCorridorSegments(intersections, links)
  assert.equal(segs.length, 1)
  // 4→2: endpoints are intersection c (num 4) and a (num 2), NOT b (num 3).
  assert.deepEqual(segs[0].from, [32.70, -117.10]) // num 4 (c)
  assert.deepEqual(segs[0].to, [32.70, -117.20])   // num 2 (a)
  // num-3's coordinate must never appear — that would be the 4→3 bug.
  const flat = [...segs[0].from, ...segs[0].to]
  assert.ok(!flat.includes(-117.05), 'num-3 (the spur) must not be an endpoint')
})

test('orphan links (endpoint id missing) are skipped', () => {
  const segs = buildCorridorSegments(intersections, [
    { id: 'x', fromId: 'c', toId: 'ZZZ', direction: 'EB/WB' },
  ])
  assert.equal(segs.length, 0)
})
