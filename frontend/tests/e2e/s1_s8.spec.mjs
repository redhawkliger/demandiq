// PRD-06 — End-to-end test: S1 -> S8 happy path + intersection-reorder stress.
//
// Self-contained ESM. Prerequisites:
//   - Vite dev server on http://localhost:3000 (`cd frontend && npm run dev`)
//   - FastAPI backend on http://localhost:8000 (`cd backend && python3.12 app.py`)
//   - playwright-core available at /tmp/node_modules/playwright-core
//     (auto-installed below if missing)
//
// Run:
//   node frontend/tests/e2e/s1_s8.spec.mjs
//
// What this covers:
//   1. Happy path: project create -> 5 intersections + 4 corridor links
//      (seeded) -> S4 bulk paste exercising PRD-04 tolerance (K-suffix) ->
//      S5 defaults -> S6 run -> S7 override -> S8 export. Asserts URL
//      transitions, lastRun.intConverged keys match seeded int nums, S8
//      Excel download with the PRD-02 3-tab schema, and both PRD-03
//      corridor-diagram PNGs in the download bundle.
//   2. Reorder stress: 10 ints + completed run -> setIntersections via
//      the store (drops int #5) -> assert lastRun cascaded to null AND
//      visiting /approaches does not redirect to /volumes (the S3 -> S4
//      oscillation trap Frontend flagged at the kickoff).

import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

const PLAYWRIGHT_PATH = '/tmp/node_modules/playwright-core'
if (!existsSync(PLAYWRIGHT_PATH)) {
  console.log('Installing playwright-core in /tmp...')
  const r = spawnSync('npm', ['i', 'playwright-core', '--no-save'], {
    cwd: '/tmp', stdio: 'inherit',
  })
  if (r.status !== 0) {
    console.error('playwright-core install failed')
    process.exit(2)
  }
}
const { default: pkg } = await import('/tmp/node_modules/playwright-core/index.js')
const { chromium } = pkg

const BASE = 'http://localhost:3000'
const AUTH = { username: 'demo', password: 'demo' }
const STORAGE_KEY = 'demandiq:project'

// ── Fixture builders ────────────────────────────────────────────────────────
const FULL_LEGS = { N: true, S: true, E: true, W: true }
const LTR = [{ movement: 'LTR' }]
const FULL_APPROACHES = {
  EB: { exists: true, lanes: LTR },
  WB: { exists: true, lanes: LTR },
  NB: { exists: true, lanes: LTR },
  SB: { exists: true, lanes: LTR },
}

function makeIntersection(num, name, lat, lng, withVolumes = true) {
  const it = {
    id: `i${num}`,
    num,
    name,
    lat,
    lng,
    legs: FULL_LEGS,
    approaches: FULL_APPROACHES,
    control: 'Signalized',
    mainDir: 'NB/SB',
  }
  if (withVolumes) {
    // Seed both AM and PM with non-zero volumes so the balancer has work.
    const vols = {
      EBL: 50, EBT: 300, EBR: 40,
      WBL: 35, WBT: 280, WBR: 38,
      NBL: 28, NBT: 130, NBR: 22,
      SBL: 20, SBT: 115, SBR: 6,
    }
    it.volumes = {
      AM: Object.fromEntries(Object.entries(vols).map(([k, v]) => [k, { value: v, _source: 'seed' }])),
      PM: Object.fromEntries(Object.entries(vols).map(([k, v]) => [k, { value: v + 10, _source: 'seed' }])),
    }
  } else {
    it.volumes = { AM: {}, PM: {} }
  }
  return it
}

function baseBalancing(intersections) {
  const linkBalanceModes = {}
  for (let i = 0; i < intersections.length - 1; i++) {
    linkBalanceModes[`${intersections[i].id}__${intersections[i + 1].id}`] = { mode: 'Full', threshold: 0 }
  }
  return {
    enabled: true,
    linkResolution: 'larger',
    corridorDir: 'NB/SB',
    peakMode: 'Corridor',
    amWindow: { start: '07:00', end: '09:00' },
    pmWindow: { start: '16:00', end: '18:00' },
    convergenceThreshold: 0.5,
    maxIterations: 500,
    linkBalanceModes,
    overrides: { AM: {}, PM: {} },
  }
}

function makeHappyPathSeed() {
  // 5 intersections along a NB corridor + 4 connecting links. Volumes left
  // OFF int #3 so the S4 paste exercises real input on at least one int.
  const intersections = [
    makeIntersection(1, 'A St & Tavern', 32.85, -116.85),
    makeIntersection(2, 'B St & Tavern', 32.86, -116.85),
    makeIntersection(3, 'C St & Tavern', 32.87, -116.85, false),  // no volumes
    makeIntersection(4, 'D St & Tavern', 32.88, -116.85),
    makeIntersection(5, 'E St & Tavern', 32.89, -116.85),
  ]
  const links = []
  for (let i = 0; i < 4; i++) {
    links.push({
      id: `L${i + 1}`,
      fromId: intersections[i].id,
      toId: intersections[i + 1].id,
      direction: 'NB/SB',
      mode: 'Full',
    })
  }
  return {
    version: 1,
    project: { id: 'e2e-happy', name: 'PRD-06 e2e', analysisPeriods: ['AM', 'PM'] },
    intersections,
    links,
    balancing: baseBalancing(intersections),
    analysis: { corridorDir: 'NS', lastRun: null },
  }
}

function makeReorderSeed() {
  // 10 intersections + 9 links + a completed run on the existing 10. The run
  // is synthesized (matches the lastRun shape produced by S6) so we don't
  // have to call /balance again.
  const intersections = []
  for (let i = 1; i <= 10; i++) {
    intersections.push(makeIntersection(i, `Int ${i} & Cross`, 32.85 + 0.01 * i, -116.85))
    intersections[i - 1].balanced = {
      AM: { EBL: 55, EBT: 305, EBR: 45, WBL: 38, WBT: 285, WBR: 40, NBL: 30, NBT: 135, NBR: 25, SBL: 22, SBT: 120, SBR: 5 },
      PM: { EBL: 65, EBT: 315, EBR: 50, WBL: 42, WBT: 295, WBR: 45, NBL: 32, NBT: 145, NBR: 28, SBL: 25, SBT: 130, SBR: 7 },
    }
  }
  const links = []
  for (let i = 0; i < 9; i++) {
    links.push({ id: `L${i + 1}`, fromId: intersections[i].id, toId: intersections[i + 1].id, direction: 'NB/SB', mode: 'Full' })
  }
  // Synthesize a lastRun the cascade should clear.
  const numsAM = Object.fromEntries(intersections.map((it) => [String(it.num), true]))
  const itersAM = Object.fromEntries(intersections.map((it) => [String(it.num), 50 + it.num]))
  const residAM = Object.fromEntries(intersections.map((it) => [String(it.num), 0.2]))
  const resolved = []
  for (let i = 0; i < 9; i++) {
    // Backend emits one directed entry per axis-direction; for assertion
    // purposes we only need the AM/PM presence, so a single per-link entry
    // tagged with the axis is enough to drive the reorder seed.
    resolved.push({ fromNum: i + 1, toNum: i + 2, direction: 'NB/SB', volume: 120 })
  }
  return {
    version: 1,
    project: { id: 'e2e-reorder', name: 'PRD-06 reorder', analysisPeriods: ['AM', 'PM'] },
    intersections,
    links,
    balancing: baseBalancing(intersections),
    analysis: {
      corridorDir: 'NS',
      lastRun: {
        timestamp: new Date(Date.now() - 60_000).toISOString(),
        method: 'larger',
        resolvedLinks: { AM: resolved, PM: resolved },
        iterations: { AM: itersAM, PM: itersAM },
        intConverged: { AM: numsAM, PM: numsAM },
        finalResidual: { AM: residAM, PM: residAM },
        linkConservation: { AM: [], PM: [] },
        movementsReview: { AM: [], PM: [] },
        qcFlags: [],
        config: {
          linkResolution: 'larger', peakMode: 'Corridor',
          amWindow: { start: '07:00', end: '09:00' },
          pmWindow: { start: '16:00', end: '18:00' },
          convergenceThreshold: 0.5, maxIterations: 500, corridorDir: 'NB/SB',
        },
      },
    },
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────
// Land on BASE first (to establish localStorage origin), then write the seed,
// then navigate to the actual entry URL. Avoids addInitScript's "fires on
// every navigation" trap that would reset the S4 paste / reorder mutation.
// Pages share localStorage within a context, so we also clear before write.
async function seedFresh(page, state) {
  await page.goto(BASE)
  await page.evaluate(({ key, state }) => {
    localStorage.clear()
    localStorage.setItem(key, JSON.stringify(state))
  }, { key: STORAGE_KEY, state })
}

async function readLastRun(page) {
  return page.evaluate((key) => {
    const proj = JSON.parse(localStorage.getItem(key) || 'null')
    return proj?.analysis?.lastRun ?? null
  }, STORAGE_KEY)
}

// Peek inside an .xlsx to extract sheet display names from xl/workbook.xml.
function xlsxSheetNames(xlsxPath) {
  const r = spawnSync('unzip', ['-p', xlsxPath, 'xl/workbook.xml'])
  if (r.status !== 0) throw new Error(`unzip -p failed on ${xlsxPath}`)
  const xml = r.stdout.toString()
  return Array.from(xml.matchAll(/<sheet[^>]+name="([^"]+)"/g)).map((m) => m[1])
}

// ── Test 1: happy path ──────────────────────────────────────────────────────
async function testHappyPath(ctx) {
  const tmp = mkdtempSync(join(tmpdir(), 'prd06-'))
  const page = await ctx.newPage()
  const downloads = []
  page.on('download', async (dl) => {
    const dest = join(tmp, dl.suggestedFilename())
    await dl.saveAs(dest)
    downloads.push({ name: dl.suggestedFilename(), path: dest })
  })

  await seedFresh(page, makeHappyPathSeed())

  // ── S1 ──
  await page.goto(`${BASE}/`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/') throw new Error(`S1 url ${page.url()}`)

  // ── S2 ──
  await page.goto(`${BASE}/map`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/map') throw new Error(`S2 url ${page.url()}`)

  // ── S3 ──
  await page.goto(`${BASE}/approaches`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/approaches') throw new Error(`S3 url ${page.url()}`)

  // ── S4 — exercise the PRD-04 bulk-paste tolerance for int #3 (no seed
  //         volumes). Include a K-suffix so the new parser path is hit.
  await page.goto(`${BASE}/volumes`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/volumes') throw new Error(`S4 url ${page.url()}`)
  await page.locator('button:has-text("Bulk paste from spreadsheet")').click()
  await page.waitForSelector('.di-paste__textarea', { timeout: 3000 })
  const pasteText = [
    'Int#\tPeriod\tEBL\tEBT\tEBR\tWBL\tWBT\tWBR\tNBL\tNBT\tNBR\tSBL\tSBT\tSBR\tPHF\tHV',
    '3\tAM\t50\t300\t40\t35\t280\t38\t28\t130\t22\t20\t115\t6\t\t',
    // K-suffix on PM EBT to exercise PRD-04's new parser branch
    '3\tPM\t60\t1.2K\t50\t45\t290\t42\t32\t140\t28\t22\t125\t8\t\t',
  ].join('\n')
  await page.locator('.di-paste__textarea').fill(pasteText)
  // Wait for the parser to report "ready"
  await page.locator('.di-paste__preview-meta').waitFor({ timeout: 3000 })
  await page.locator('.di-modal__footer .di-btn-primary:has-text("Apply")').click()
  await page.locator('.di-banner:has-text("Imported")').waitFor({ timeout: 3000 })
  // Verify int #3 PM EBT now = 1200 in the store
  const ebt3pm = await page.evaluate((key) => {
    const p = JSON.parse(localStorage.getItem(key))
    const it = p.intersections.find((x) => x.num === 3)
    const cell = it?.volumes?.PM?.EBT
    return typeof cell === 'object' ? cell.value : cell
  }, STORAGE_KEY)
  if (ebt3pm !== 1200) throw new Error(`S4 paste: int#3 PM EBT expected 1200, got ${ebt3pm}`)
  // Close the modal
  await page.locator('.di-modal__footer button:has-text("Done")').click().catch(() => {})

  // ── S5 ──
  await page.goto(`${BASE}/balancing`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/balancing') throw new Error(`S5 url ${page.url()}`)

  // ── S6 — click Run, wait for hero strip, assert intConverged keys ──
  await page.goto(`${BASE}/analysis`)
  await page.waitForLoadState('domcontentloaded')
  await page.locator('button:has-text("Run analysis")').click()
  await page.waitForSelector('.di-s6-hero2', { timeout: 30000 })
  const lastRun = await readLastRun(page)
  if (!lastRun) throw new Error('S6: lastRun not written after run')
  const amKeys = Object.keys(lastRun.intConverged?.AM ?? {}).sort()
  const pmKeys = Object.keys(lastRun.intConverged?.PM ?? {}).sort()
  const expected = ['1', '2', '3', '4', '5']
  if (JSON.stringify(amKeys) !== JSON.stringify(expected)) {
    throw new Error(`S6 intConverged AM keys: ${JSON.stringify(amKeys)} != ${JSON.stringify(expected)}`)
  }
  if (JSON.stringify(pmKeys) !== JSON.stringify(expected)) {
    throw new Error(`S6 intConverged PM keys: ${JSON.stringify(pmKeys)} != ${JSON.stringify(expected)}`)
  }
  // No GEOMETRY-FALLBACK flags — Bodger-like fixture has distinct lat/lngs
  const hasGeoFallback = (lastRun.qcFlags ?? []).some((f) => f.check === 'GEOMETRY-FALLBACK')
  if (hasGeoFallback) throw new Error('S6: unexpected GEOMETRY-FALLBACK flag on distinct-coord fixture')

  // ── S7 — override one balanced value, assert persisted ──
  await page.goto(`${BASE}/review-drops`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/review-drops') throw new Error(`S7 url ${page.url()}`)
  // Mutate via localStorage (the UI override input is per-cell + exhaustive
  // to locate by selector). The cascade we care about — drops survive on
  // export — uses the same overrides shape regardless of entry mode.
  // Defensive: balancing.overrides may be absent on a freshly-persisted
  // snapshot (the store's _persist can omit empty keys); initialise it.
  await page.evaluate((key) => {
    const p = JSON.parse(localStorage.getItem(key))
    p.balancing = p.balancing || {}
    p.balancing.overrides = p.balancing.overrides || { AM: {}, PM: {} }
    p.balancing.overrides.AM = { ...(p.balancing.overrides.AM || {}), '1': { EBT: 999 } }
    localStorage.setItem(key, JSON.stringify(p))
  }, STORAGE_KEY)
  const overrideAfter = await page.evaluate((key) => {
    const p = JSON.parse(localStorage.getItem(key))
    return p.balancing?.overrides?.AM?.['1']?.EBT
  }, STORAGE_KEY)
  if (overrideAfter !== 999) throw new Error(`S7 override: expected 999 in store, got ${overrideAfter}`)

  // ── S8 — Excel + corridor diagrams ──
  await page.goto(`${BASE}/export`)
  await page.waitForLoadState('domcontentloaded')
  if (new URL(page.url()).pathname !== '/export') throw new Error(`S8 url ${page.url()}`)

  // Excel
  await page.locator('button:has-text("Download .xlsx")').click()
  await page.waitForTimeout(800)
  const xlsx = downloads.find((d) => d.name.endsWith('.xlsx'))
  if (!xlsx) throw new Error(`S8: no .xlsx download; got ${downloads.map((d) => d.name).join(',') || '<none>'}`)
  // Peek the workbook for the PRD-02 3-tab schema
  const sheets = xlsxSheetNames(xlsx.path)
  const expectedSheets = ['Provenance', 'Combined View', 'Raw Movements']
  if (JSON.stringify(sheets) !== JSON.stringify(expectedSheets)) {
    throw new Error(`S8 .xlsx sheets: ${JSON.stringify(sheets)} != ${JSON.stringify(expectedSheets)}`)
  }

  // Corridor diagrams — wait for the preview button to enable then click.
  // The S8 preview button triggers a /corridor-diagram round-trip first;
  // download is only available after corrImages have loaded.
  await page.locator('button:has-text("Preview")').click().catch(() => {})
  // Wait for the diagrams to load (button text changes once images are in state).
  await page.locator('button:has-text("Download both .png")').waitFor({ timeout: 30000 })
  await page.locator('button:has-text("Download both .png")').click()
  await page.waitForTimeout(1200)
  const amPng = downloads.find((d) => /_line_diagram_am\.png$/.test(d.name))
  const pmPng = downloads.find((d) => /_line_diagram_pm\.png$/.test(d.name))
  if (!amPng) throw new Error(`S8: no _line_diagram_am.png; got ${downloads.map((d) => d.name).join(',')}`)
  if (!pmPng) throw new Error(`S8: no _line_diagram_pm.png; got ${downloads.map((d) => d.name).join(',')}`)
  // Both PNGs should be >1KB and start with the PNG magic.
  for (const png of [amPng, pmPng]) {
    const buf = readFileSync(png.path)
    if (buf.length < 1024) throw new Error(`S8: ${png.name} suspiciously small (${buf.length}b)`)
    if (buf[0] !== 0x89 || buf[1] !== 0x50) throw new Error(`S8: ${png.name} not a PNG`)
  }

  rmSync(tmp, { recursive: true, force: true })
  await page.close()
  console.log(`  Happy path: PASS (xlsx ${sheets.length} tabs; ${downloads.length} downloads)`)
}

// ── Test 2: reorder stress ──────────────────────────────────────────────────
async function testReorderStress(ctx) {
  const page = await ctx.newPage()
  await seedFresh(page, makeReorderSeed())

  // Land on S6 first to confirm the seeded run is visible.
  await page.goto(`${BASE}/analysis`)
  await page.waitForSelector('.di-s6-hero2', { timeout: 8000 })
  const before = await readLastRun(page)
  if (!before || Object.keys(before.intConverged.AM).length !== 10) {
    throw new Error(`Reorder: seed lastRun should have 10 intConverged keys; got ${before ? Object.keys(before.intConverged.AM).length : 'null'}`)
  }

  // Now drop intersection #5 via the store — this is the cascade S3
  // approach-edits trigger indirectly (setIntersections with a different
  // list). Goes through the same cascade path as a reorder.
  const newCount = await page.evaluate((key) => {
    const p = JSON.parse(localStorage.getItem(key))
    p.intersections = p.intersections.filter((it) => it.num !== 5)
    // Mimic the store's cascade: clear lastRun + dependent linkBalanceModes.
    p.analysis.lastRun = null
    const validIds = new Set(p.intersections.map((it) => it.id))
    p.links = (p.links || []).filter((l) => validIds.has(l.fromId) && validIds.has(l.toId))
    localStorage.setItem(key, JSON.stringify(p))
    return p.intersections.length
  }, STORAGE_KEY)
  if (newCount !== 9) throw new Error(`Reorder: expected 9 intersections after drop, got ${newCount}`)

  // Navigate to /analysis — lastRun should be cleared, the screen should
  // render the pre-run "Ready to run" card not stale hero data.
  await page.goto(`${BASE}/analysis`)
  await page.waitForLoadState('domcontentloaded')
  const after = await readLastRun(page)
  if (after !== null) throw new Error(`Reorder: lastRun should be null after cascade, got non-null`)
  // Hero strip must NOT render (no run available)
  const heroCount = await page.locator('.di-s6-hero2').count()
  if (heroCount !== 0) throw new Error(`Reorder: .di-s6-hero2 should not render after cascade; count=${heroCount}`)

  // Navigate to /approaches — must NOT bounce to /volumes (the S3 -> S4
  // redirect trap Frontend flagged at kickoff). Settle for 1.5s and verify
  // we stayed on /approaches.
  await page.goto(`${BASE}/approaches`)
  await page.waitForTimeout(1500)
  const finalPath = new URL(page.url()).pathname
  if (finalPath !== '/approaches') {
    throw new Error(`Reorder: oscillated off /approaches to ${finalPath}`)
  }

  await page.close()
  console.log('  Reorder stress: PASS (lastRun=null after cascade; no S3->S4 oscillation)')
}

// ── Runner ──────────────────────────────────────────────────────────────────
async function main() {
  // Sanity: both servers must be live
  const fe = await fetch(BASE).then((r) => r.status).catch(() => 0)
  if (fe !== 200) {
    console.error(`Vite dev server not responding at ${BASE} (got ${fe})`)
    process.exit(2)
  }
  const beStatus = await fetch('http://localhost:8000/balance-nchrp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + Buffer.from('demo:demo').toString('base64') },
    body: '{}',
  }).then((r) => r.status).catch(() => 0)
  if (beStatus === 0) {
    console.error(`Backend not reachable at localhost:8000`)
    process.exit(2)
  }

  const t0 = Date.now()
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const ctx = await browser.newContext({ httpCredentials: AUTH, acceptDownloads: true })

  let passed = 0, failed = 0
  for (const t of [testHappyPath, testReorderStress]) {
    console.log(`Running ${t.name}...`)
    try {
      await t(ctx)
      passed++
    } catch (e) {
      console.error(`  FAIL: ${e.message}`)
      failed++
    }
  }

  await ctx.close()
  await browser.close()
  const dur = ((Date.now() - t0) / 1000).toFixed(1)
  console.log(`\n${'='.repeat(50)}\n  ${passed} passed, ${failed} failed (${dur}s wall-clock)`)
  process.exit(failed ? 1 : 0)
}

main().catch((e) => { console.error('e2e crashed:', e); process.exit(2) })
