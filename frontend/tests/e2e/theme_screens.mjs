// Phase 6 — theme verification screenshots (Night Traffic / Sunshine).
//
// Self-contained ESM. Prerequisites (same as s1_s8.spec.mjs):
//   - Vite dev server on http://localhost:3000  (cd frontend && npm run dev)
//   - playwright-core in /tmp/node_modules       (auto-installed below)
//   - system Chrome (channel: 'chrome')
//
// Run:
//   node frontend/tests/e2e/theme_screens.mjs
//
// Captures, per theme: S1 (appearance picker), the open picker modal, and the
// /map basemap over the Alpine corridor fixture. Verifies Phase 4 (Voyager /
// Positron tiles) + Phase 5 (picker + boot apply) + Phase 3.5 chrome theming.

import { existsSync, mkdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'

const PLAYWRIGHT_PATH = '/tmp/node_modules/playwright-core'
if (!existsSync(PLAYWRIGHT_PATH)) {
  console.log('Installing playwright-core in /tmp...')
  const r = spawnSync('npm', ['i', 'playwright-core', '--no-save'], { cwd: '/tmp', stdio: 'inherit' })
  if (r.status !== 0) { console.error('playwright-core install failed'); process.exit(2) }
}
const { default: pkg } = await import('/tmp/node_modules/playwright-core/index.js')
const { chromium } = pkg

const BASE = 'http://localhost:3000'
const AUTH = { username: 'demo', password: 'demo' }
const PROJECT_KEY = 'demandiq:project'
const THEME_KEY = 'demandiq:theme'
const OUT = '/tmp/theme_shots'
mkdirSync(OUT, { recursive: true })

// ── Alpine corridor fixture (5 NB intersections near Alpine, CA) ────────────
// legs is the UI's '4-leg'/'3-leg' string (what IntersectionModal stores), NOT
// the {N,S,E,W} object — S2 renders legs as a React child, so the object form
// would crash the page (and tank the map screenshots).
const LTR = [{ movement: 'LTR' }]
const FULL_APPROACHES = {
  EB: { exists: true, lanes: LTR }, WB: { exists: true, lanes: LTR },
  NB: { exists: true, lanes: LTR }, SB: { exists: true, lanes: LTR },
}
function makeIntersection(num, name, lat, lng) {
  return {
    id: `i${num}`, num, name, lat, lng,
    legs: '4-leg', approaches: FULL_APPROACHES, control: 'Signalized', mainDir: 'NB/SB',
    volumes: { AM: {}, PM: {} },
  }
}
function alpineSeed() {
  const intersections = [
    makeIntersection(1, 'A St & Tavern', 32.85, -116.85),
    makeIntersection(2, 'B St & Tavern', 32.86, -116.85),
    makeIntersection(3, 'C St & Tavern', 32.87, -116.85),
    makeIntersection(4, 'D St & Tavern', 32.88, -116.85),
    makeIntersection(5, 'E St & Tavern', 32.89, -116.85),
  ]
  const links = []
  for (let i = 0; i < 4; i++) {
    links.push({ id: `L${i + 1}`, fromId: intersections[i].id, toId: intersections[i + 1].id, direction: 'NB/SB', mode: 'Full' })
  }
  return {
    version: 1,
    project: { id: 'phase6', name: 'Alpine Corridor', analysisPeriods: ['AM', 'PM'] },
    intersections, links,
    analysis: { corridorDir: 'NS', lastRun: null },
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function run() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const ctx = await browser.newContext({
    httpCredentials: AUTH,
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
  })
  const page = await ctx.newPage()
  const themes = ['night-traffic', 'sunshine']
  const checks = []

  for (const theme of themes) {
    // Seed project + theme on the BASE origin, then reload so initTheme() applies.
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.evaluate(({ pk, tk, seed, theme }) => {
      localStorage.clear()
      localStorage.setItem(pk, JSON.stringify(seed))
      localStorage.setItem(tk, theme)
    }, { pk: PROJECT_KEY, tk: THEME_KEY, seed: alpineSeed(), theme })

    // ── S1 — appearance picker visible ──────────────────────────────────────
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
    const applied = await page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    checks.push([`${theme}: data-theme applied on boot`, applied === theme])
    const trigger = page.locator('.di-appearance-trigger')
    checks.push([`${theme}: appearance trigger present`, await trigger.count() === 1])
    await page.screenshot({ path: `${OUT}/s1_${theme}.png`, fullPage: true })

    // ── Picker modal open ───────────────────────────────────────────────────
    await trigger.click()
    await page.waitForSelector('.di-theme-card', { timeout: 3000 })
    const cards = await page.locator('.di-theme-card').count()
    checks.push([`${theme}: modal shows 2 theme cards`, cards === 2])
    const selected = await page.locator('.di-theme-card--selected').count()
    checks.push([`${theme}: exactly one card marked selected`, selected === 1])
    await page.screenshot({ path: `${OUT}/modal_${theme}.png` })
    await page.keyboard.press('Escape').catch(() => {})
    await page.locator('.di-modal__footer .di-btn-primary').click().catch(() => {})

    // ── /map — themed basemap over the Alpine corridor ──────────────────────
    await page.goto(`${BASE}/map`, { waitUntil: 'networkidle' })
    // Wait for Leaflet tiles to actually paint.
    await page.waitForSelector('img.leaflet-tile-loaded', { timeout: 8000 }).catch(() => {})
    await sleep(1500)
    const tileSrc = await page.evaluate(() => {
      const img = document.querySelector('img.leaflet-tile-loaded') || document.querySelector('img.leaflet-tile')
      return img ? img.src : ''
    })
    const expectTile = theme === 'sunshine' ? 'positron' : 'voyager'
    checks.push([`${theme}: map uses ${expectTile} tiles`, tileSrc.includes(expectTile)])
    const pins = await page.locator('.di-pin').count()
    checks.push([`${theme}: 5 corridor pins render`, pins === 5])
    await page.screenshot({ path: `${OUT}/map_${theme}.png` })
  }

  await browser.close()

  // ── Report ────────────────────────────────────────────────────────────────
  let failed = 0
  console.log('\nPhase 6 theme verification:')
  for (const [label, pass] of checks) {
    console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${label}`)
    if (!pass) failed++
  }
  console.log(`\nScreenshots in ${OUT}/  (s1_, modal_, map_ × 2 themes)`)
  console.log(`${checks.length - failed}/${checks.length} checks passed`)
  if (failed > 0) process.exit(1)
}

run().catch((e) => { console.error(e); process.exit(1) })
