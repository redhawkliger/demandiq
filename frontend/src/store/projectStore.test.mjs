// projectStore state-integrity tests. Pure ESM, no test runner required:
//   node src/store/projectStore.test.mjs
//
// Covers the corruption-resilience fix:
//   - reconcileDependents() prunes orphan links / balance modes / overrides
//     and clears stale lastRun (pure-function unit tests)
//   - self-heal on store hydrate strips a corrupted ("Willow") snapshot from
//     localStorage, warns, and leaves the project usable (integration test)
//
// The store reads localStorage lazily (only on first getSnapshot), so importing
// it here is side-effect-free. The integration test installs a fake localStorage
// BEFORE the first getSnapshot() call so init reads the seeded fixture.

import {
  reconcileDependents,
  summarizeReconcile,
  getSnapshot,
  setIntersections,
} from './projectStore.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// ── reconcileDependents: orphan links ────────────────────────────────────
{
  const { state, summary, changed } = reconcileDependents({
    intersections: [{ id: 'a', num: 1 }],
    links: [
      { id: 'l1', fromId: 'a', toId: 'ghost' },   // dead toId
      { id: 'l2', fromId: 'gone', toId: 'a' },     // dead fromId
    ],
  })
  ok(changed, 'orphan links → changed')
  ok(state.links.length === 0, `both orphan links dropped, got ${state.links.length}`)
  ok(summary.removedLinks === 2, `removedLinks=2, got ${summary.removedLinks}`)
}

// ── reconcileDependents: linkBalanceModes — both keying schemes ──────────
{
  const { state, summary } = reconcileDependents({
    intersections: [{ id: 'a', num: 1 }, { id: 'b', num: 2 }],
    links: [{ id: 'lnk_1', fromId: 'a', toId: 'b' }],
    balancing: {
      linkBalanceModes: {
        lnk_1: { mode: 'Full', threshold: 0 },       // live link id → keep
        lnk_dead: { mode: 'Full', threshold: 0 },     // dead link id → drop
        a__b: { mode: 'Full', threshold: 0 },         // live composite pair → keep
        a__ghost: { mode: 'Full', threshold: 0 },     // dead composite half → drop
      },
    },
  })
  const kept = Object.keys(state.balancing.linkBalanceModes).sort()
  ok(kept.length === 2 && kept[0] === 'a__b' && kept[1] === 'lnk_1',
    `kept live modes only, got ${kept.join(',')}`)
  ok(summary.removedLinkModes === 2, `removedLinkModes=2, got ${summary.removedLinkModes}`)
}

// ── reconcileDependents: overrides keyed on dead int nums (AM + PM) ──────
{
  const { state, summary } = reconcileDependents({
    intersections: [{ id: 'a', num: 1 }],
    balancing: {
      overrides: {
        AM: { 1: { EBT: 10 }, 5: { EBT: 20 } },   // 5 is dead
        PM: { 7: { WBT: 5 } },                      // 7 is dead
      },
    },
  })
  ok('1' in state.balancing.overrides.AM && !('5' in state.balancing.overrides.AM),
    'AM keeps live num 1, drops dead num 5')
  ok(Object.keys(state.balancing.overrides.PM).length === 0, 'PM dead override dropped')
  ok(summary.removedOverrides === 2, `removedOverrides=2, got ${summary.removedOverrides}`)
}

// ── reconcileDependents: clears lastRun when a referenced int is removed ─
{
  const { state, summary } = reconcileDependents({
    intersections: [{ id: 'a', num: 1 }, { id: 'b', num: 2 }],
    links: [{ id: 'l1', fromId: 'a', toId: 'b' }],   // still valid → not the trigger
    analysis: {
      lastRun: {
        resolvedLinks: {
          AM: [{ fromNum: 1, toNum: 2, direction: 'EB', volume: 100 },
               { fromNum: 2, toNum: 3, direction: 'EB', volume: 80 }],   // num 3 gone
          PM: [],
        },
      },
    },
  })
  ok(state.analysis.lastRun === null, 'lastRun cleared when it references a removed int')
  ok(summary.clearedLastRun === true, 'clearedLastRun flag set')
}

// ── reconcileDependents: no-op on a fully consistent snapshot ────────────
{
  const clean = {
    intersections: [{ id: 'a', num: 1 }, { id: 'b', num: 2 }],
    links: [{ id: 'l1', fromId: 'a', toId: 'b' }],
    balancing: {
      linkBalanceModes: { l1: { mode: 'Full', threshold: 0 } },
      overrides: { AM: { 1: { EBT: 10 } }, PM: {} },
    },
    analysis: {
      lastRun: { resolvedLinks: { AM: [{ fromNum: 1, toNum: 2, direction: 'EB', volume: 100 }], PM: [] } },
    },
  }
  const { state, changed } = reconcileDependents(clean)
  ok(changed === false, 'consistent snapshot → changed=false')
  ok(state === clean, 'consistent snapshot returned by reference (no copy)')
}

// ── summarizeReconcile: human-readable, pluralized, omits zero buckets ───
{
  const s = summarizeReconcile({ removedLinks: 8, removedLinkModes: 8, removedOverrides: 1, clearedLastRun: true })
  ok(s === 'removed 8 orphan links, removed 8 stale link balance modes, removed 1 orphan override, cleared lastRun',
    `unexpected summary: "${s}"`)
  const s1 = summarizeReconcile({ removedLinks: 1, removedLinkModes: 0, removedOverrides: 0, clearedLastRun: false })
  ok(s1 === 'removed 1 orphan link', `singular form wrong: "${s1}"`)
}

// ── Self-heal on hydrate: the "Willow" corrupted fixture ─────────────────
// Reconstructed to match the diagnostics dump: 0 intersections, 8 links on dead
// UUIDs, fully-populated lastRun, linkBalanceModes keyed on the dead links.
const WILLOW = {
  project: {
    name: 'Willow', client: 'City', analyst: 'AB',
    date: '2026-05-01', scenario: 'Existing', projectType: 'Corridor',
    analysisPeriods: ['AM', 'PM'],
  },
  intersections: [],
  links: Array.from({ length: 8 }, (_, i) => ({
    id: `lnk_dead-${i + 1}`,
    fromId: `int-dead-${i + 1}`,
    toId: `int-dead-${i + 2}`,
    direction: 'EB/WB', mode: 'Full', landUseThreshold: null,
  })),
  balancing: {
    enabled: true, linkResolution: 'larger', corridorDir: 'EB/WB',
    linkBalanceModes: Object.fromEntries(
      Array.from({ length: 8 }, (_, i) => [`lnk_dead-${i + 1}`, { mode: 'Full', threshold: 0 }]),
    ),
    overrides: { AM: { 3: { EBT: 1234 } }, PM: {} },   // dead int num
  },
  analysis: {
    corridorDir: 'EW',
    lastRun: {
      method: 'NCHRP', timestamp: '2026-05-01T12:00:00Z',
      resolvedLinks: {
        AM: Array.from({ length: 8 }, (_, i) => ({ fromNum: i + 1, toNum: i + 2, direction: 'EB', volume: 1000 - i })),
        PM: Array.from({ length: 8 }, (_, i) => ({ fromNum: i + 1, toNum: i + 2, direction: 'EB', volume: 900 - i })),
      },
      convergence: { AM: { converged: true }, PM: { converged: true } },
      qcFlags: [],
    },
  },
}

const STORAGE_KEY = 'demandiq:project'

// Map-backed fake localStorage (overrides any Node-provided Web Storage global).
function makeLocalStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
    clear: () => m.clear(),
  }
}

// crypto.randomUUID isn't stubbed: Node provides it, and the Willow path never
// generates link ids (0 intersections → no migration) and supplies its own
// intersection id below.
globalThis.localStorage = makeLocalStorage()
globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify(WILLOW))

// Capture the self-heal warning emitted during the first getSnapshot() (init).
const warnings = []
const origWarn = console.warn
console.warn = (...args) => { warnings.push(args.join(' ')) }

const snap = getSnapshot()   // first call → _initSnapshot → self-heal

console.warn = origWarn

ok(snap.links.length === 0, `Willow: all 8 orphan links stripped, got ${snap.links.length}`)
ok(Object.keys(snap.balancing.linkBalanceModes).length === 0,
  `Willow: all stale linkBalanceModes stripped, got ${Object.keys(snap.balancing.linkBalanceModes).length}`)
ok(Object.keys(snap.balancing.overrides.AM).length === 0, 'Willow: dead AM override stripped')
ok(snap.analysis.lastRun === null, 'Willow: stale lastRun cleared')
ok(warnings.length === 1, `Willow: exactly one self-heal warning, got ${warnings.length}`)
ok(warnings[0].includes('self-healed') && warnings[0].includes('8 orphan links') && warnings[0].includes('cleared lastRun'),
  `Willow: warning text unexpected: "${warnings[0]}"`)

// Healed state is persisted back to localStorage (not just in memory).
const persisted = JSON.parse(globalThis.localStorage.getItem(STORAGE_KEY))
ok(persisted.links.length === 0, 'Willow: healed state persisted to localStorage')

// Project is usable again: adding an intersection succeeds (no silent failure).
setIntersections([{ id: 'i1', num: 1, name: 'New & Main', control: 'Signalized', legs: '4-leg', mainDir: 'EB/WB', crossDir: 'NB/SB' }])
const after = getSnapshot()
ok(after.intersections.length === 1 && after.intersections[0].id === 'i1',
  `Willow: add-intersection works after heal, got ${after.intersections.length}`)

console.log(`\n${'='.repeat(46)}\n  ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
