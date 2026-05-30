// Phase 5 — stop-controlled approaches: headless S2 Inspector click-through.
//
//   node frontend/tests/e2e/stop_control.mjs
// Prereqs: Vite dev server :3000, playwright-core in /tmp, system Chrome.
//
// Verifies the wiring (logic is unit-tested in stopControl/diagramPayload tests):
//   - stop row appears for stop controls, hides for Signalized
//   - smart default → cross street (EB/WB on an NB/SB corridor)
//   - All-way stop → all checked + disabled
//   - Signalized clears every flag
//   - a manual toggle persists to projectStore (localStorage)
//   - the diagram endpoint renders stops at the checked legs

import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const PW = '/tmp/node_modules/playwright-core'
if (!existsSync(PW)) {
  const r = spawnSync('npm', ['i', 'playwright-core', '--no-save'], { cwd: '/tmp', stdio: 'inherit' })
  if (r.status !== 0) { console.error('playwright-core install failed'); process.exit(2) }
}
const { default: pkg } = await import('/tmp/node_modules/playwright-core/index.js')
const { chromium } = pkg

const BASE = 'http://localhost:3000'
const AUTH = { username: 'demo', password: 'demo' }
const KEY = 'demandiq:project'

// One signalized 4-leg intersection on an NB/SB corridor (cross street = EB/WB).
const seed = {
  version: 1,
  project: { id: 'p5', name: 'Stop Control', analysisPeriods: ['AM', 'PM'] },
  balancing: { corridorDir: 'NB/SB' },
  analysis: { corridorDir: 'NS', lastRun: null },
  links: [],
  intersections: [
    {
      id: 'i1', num: 1, name: 'Main & Cross', control: 'Signalized',
      legs: '4-leg', mainDir: 'NB/SB', crossDir: 'EB/WB',
      lat: 32.85, lng: -116.85,
      approaches: {
        EB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        WB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        NB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        SB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      },
    },
    // A second, Signalized intersection so Continue isn't gated on count (>=2);
    // the gate under test is the stop-control one.
    {
      id: 'i2', num: 2, name: 'Main & 2nd', control: 'Signalized',
      legs: '4-leg', mainDir: 'NB/SB', crossDir: 'EB/WB',
      lat: 32.86, lng: -116.85,
      approaches: {
        EB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        WB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        NB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
        SB: { exists: true, lanes: [{ movement: 'T' }], stopControlled: false },
      },
    },
  ],
}

const checks = []
const expect = (label, cond) => checks.push([label, !!cond])

const b = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await b.newContext({ httpCredentials: AUTH, viewport: { width: 1280, height: 900 } })
const page = await ctx.newPage()

const readApproaches = () => page.evaluate((k) => {
  const p = JSON.parse(localStorage.getItem(k))
  return p.intersections[0].approaches
}, KEY)
const stoppedDirs = (ap) => ['EB', 'WB', 'NB', 'SB'].filter((d) => ap[d]?.stopControlled).sort()
const clickControl = async (label) => {
  await page.locator('.di-seg__opt', { hasText: new RegExp(`^${label}$`) }).click()
  await page.waitForTimeout(150)
}

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.evaluate(({ k, s }) => { localStorage.clear(); localStorage.setItem(k, JSON.stringify(s)) }, { k: KEY, s: seed })
await page.goto(`${BASE}/map`, { waitUntil: 'networkidle' })

// Select the intersection → Inspector shows.
await page.locator('.di-int__body').first().click()
await page.waitForSelector('.di-seg', { timeout: 4000 })
expect('Signalized: no stop row', await page.locator('.di-stopleg-grid').count() === 0)

// ── Two-way stop → row appears, smart default to cross street EB/WB ──────────
await clickControl('Two-way stop')
expect('Two-way: stop row appears', await page.locator('.di-stopleg-grid').count() === 1)
expect('Two-way: 4 checkboxes', await page.locator('.di-stopleg input').count() === 4)
{
  const ap = await readApproaches()
  expect('Two-way: smart default → EB,WB stopped (NB/SB corridor)', stoppedDirs(ap).join() === 'EB,WB')
}

// ── All-way stop → all checked + disabled ───────────────────────────────────
await clickControl('All-way stop')
{
  const states = await page.locator('.di-stopleg input').evaluateAll((els) => els.map((e) => ({ c: e.checked, d: e.disabled })))
  expect('All-way: all 4 checked', states.length === 4 && states.every((s) => s.c))
  expect('All-way: all disabled (read-only)', states.every((s) => s.d))
  const ap = await readApproaches()
  expect('All-way: all flags true in store', stoppedDirs(ap).join() === 'EB,NB,SB,WB')
}

// ── Signalized → row hidden, all flags cleared ──────────────────────────────
await clickControl('Signalized')
expect('Signalized: stop row hidden again', await page.locator('.di-stopleg-grid').count() === 0)
{
  const ap = await readApproaches()
  expect('Signalized: all flags cleared to false', stoppedDirs(ap).length === 0)
}

// ── Manual toggle persists ──────────────────────────────────────────────────
await clickControl('Two-way stop')                 // back to EB,WB default
await page.locator('.di-stopleg', { hasText: /^NB$/ }).click()   // add NB
await page.waitForTimeout(150)
{
  const ap = await readApproaches()
  expect('Toggle: NB added → EB,NB,WB persisted', stoppedDirs(ap).join() === 'EB,NB,WB')
  expect('Two-way hint shows when count != 2', await page.locator('.di-stopleg__hint').count() === 1)
}

// ── One-way stop starts empty → silent-empty hint appears ───────────────────
await clickControl('One-way stop')
{
  const ap = await readApproaches()
  expect('One-way stop: starts with 0 selected', stoppedDirs(ap).length === 0)
  const hint = await page.locator('.di-stopleg__hint').textContent().catch(() => '')
  expect('One-way stop: zero-selected hint warns no stop signs render',
    await page.locator('.di-stopleg__hint').count() === 1 && /no stop signs/i.test(hint || ''))
}

// ── Diagram renders stops at the checked legs ───────────────────────────────
// Set a clean two-leg stop state (EB,WB) and render via the endpoint.
await clickControl('Signalized'); await clickControl('Two-way stop')   // EB,WB
{
  const ap = await readApproaches()
  const stopped = stoppedDirs(ap)
  const png = await page.evaluate(async ({ stopped }) => {
    const r = await fetch('/api/intersection-diagram', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        intersection: {
          num: 1, name: 'Main & Cross', active_legs: ['EB', 'WB', 'NB', 'SB'],
          control: 'Two-way stop', streets: { NS: 'Cross', EW: 'Main' },
          stopped_approaches: stopped,
        },
        u_vols: { EBT: 300, WBT: 280, NBT: 130, SBT: 120 },
        b_vols: { EBT: 305, WBT: 285, NBT: 135, SBT: 125 },
        view_mode: 'combined',
      }),
    })
    return { ok: r.ok, len: r.ok ? (await r.blob()).size : 0 }
  }, { stopped })
  expect('Diagram endpoint renders a PNG with the checked legs', png.ok && png.len > 1000)
}

// ── Hard gate: a zero-selected stop control blocks Continue ──────────────────
// State here: Int 1 = Two-way (EB,WB = 2 stops), Int 2 = Signalized → satisfied.
const continueBtn = page.locator('.di-side__footer .di-btn-primary--block')
expect('Gate: Continue enabled when every stop control is satisfied',
  (await continueBtn.isDisabled()) === false)
await clickControl('One-way stop')                       // Int 1 → 0 selected
expect('Gate: Continue disabled when a stop control has 0 selected',
  (await continueBtn.isDisabled()) === true)
expect('Gate: blocker hint names the offending intersection (Int 1)',
  ((await page.locator('.di-side__hint--block').textContent()) || '').includes('Int 1'))
expect('Gate: blocker hint link is clickable',
  (await page.locator('.di-side__hint-link').count()) >= 1)
await page.screenshot({ path: '/tmp/stop_control_gate_blocked.png' })
await page.locator('.di-stopleg', { hasText: /^NB$/ }).click()   // resolve it
await page.waitForTimeout(150)
expect('Gate: Continue re-enabled once an approach is selected',
  (await continueBtn.isDisabled()) === false)

await page.screenshot({ path: '/tmp/stop_control_inspector.png' })
await b.close()

let failed = 0
console.log('\nPhase 5 — stop-controlled approaches:')
for (const [label, pass] of checks) { console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${label}`); if (!pass) failed++ }
console.log(`\n${checks.length - failed}/${checks.length} checks passed`)
if (failed > 0) process.exit(1)
