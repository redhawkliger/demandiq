#!/usr/bin/env node
// scripts/render-check.mjs
//
// Headless-Chrome render gate. Drives the running app over the Chrome DevTools
// Protocol using ONLY Node built-ins (child_process, http, ws via global
// WebSocket, fs) — no Playwright, no Puppeteer, no dependency. It seeds a
// synthetic project into localStorage['demandiq:project'], navigates a route,
// and ASSERTS the target component actually rendered: a root element exists, a
// required <img> has non-zero natural dimensions (i.e. is not a blank anchor),
// and the page logged no console errors. Exits non-zero on any failure.
//
// WHY THIS EXISTS: this repo shipped two bugs that every build-time gate
// (HTTP-200 curl, Vite-transform grep, node-ESM unit tests) waved through
// because none of them RAN THE APP:
//   1. IntersectionDiagram read `d.png` but the endpoint returns `png_base64`
//      → the fetch succeeded, the value was undefined, the anchor rendered
//      blank with no error. A "does the <img> actually have pixels?" check is
//      the only thing that catches that.
//   2. A synchronous setState in an effect body (a lint error) — caught by the
//      lint half of verify-frontend.sh, not here.
//
// Usage:
//   node scripts/render-check.mjs [--route /path] [--root <sel>] [--image <sel>]
//                                 [--seed <file.json>] [--click "<button text>"]
//                                 [--origin http://localhost:3000]
//                                 [--backend http://localhost:8000]
// Defaults target the S6 "Review Movements" view (the anchor-diagram render
// that blanked). --seed replaces the built-in project with a JSON file (needed
// for routes gated on extra store slices, e.g. F4's forecasting.results).
// --click reveals a diagram behind an interaction (e.g. S8's "Preview AM + PM")
// before the render assertion. Requires the Vite dev server and backend running.

import { spawn } from 'node:child_process'
import { mkdtempSync, writeFileSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, isAbsolute, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')

// ---- args ----
const argv = process.argv.slice(2)
function arg(name, def) {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def
}
const ROUTE = arg('--route', '/review-movements')
const ROOT_SEL = arg('--root', '.di-rm')
const IMAGE_SEL = arg('--image', '.di-rm__anchor img')
const ORIGIN = arg('--origin', 'http://localhost:3000')
const BACKEND = arg('--backend', 'http://localhost:8000')
const PORT = Number(arg('--port', '9245'))
// Optional: a JSON seed file (replaces the built-in default seed) and a button
// to click before asserting the render (for views whose diagram is behind an
// interaction, e.g. S8's "Preview AM + PM"). Relative --seed paths resolve
// against CWD first, then the repo root, so `--seed scripts/fixtures/x.json`
// works from anywhere.
const SEED_ARG = arg('--seed', null)
const CLICK_TEXT = arg('--click', null)

function resolveSeedPath(p) {
  if (isAbsolute(p)) return existsSync(p) ? p : null
  const fromCwd = join(process.cwd(), p)
  if (existsSync(fromCwd)) return fromCwd
  const fromRepo = join(REPO_ROOT, p)
  if (existsSync(fromRepo)) return fromRepo
  return null
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const fail = (msg) => { console.error(`render-check: FAIL — ${msg}`); process.exitCode = 1 }

// ---- synthetic project: a 3-intersection corridor with a completed lastRun.
// The diagram render needs intersection.balanced[period] + approaches (buildPayload
// reads those); the rail/verdict/changelog need lastRun. Kept minimal but real. ----
function vols(o) {
  return { EBL: 0, EBT: 0, EBR: 0, WBL: 0, WBT: 0, WBR: 0, NBL: 0, NBT: 0, NBR: 0, SBL: 0, SBT: 0, SBR: 0, ...o }
}
function mkInt(id, num, name) {
  const leg = { exists: true, lanes: [{ movement: 'T' }], stopControlled: false }
  return {
    id, num, name, lat: 32.71 + num * 0.004, lng: -117.16, control: 'Signalized', mainDir: 'EB/WB',
    approaches: { EB: leg, WB: leg, NB: leg, SB: leg },
    volumes: { AM: vols({ EBL: 120, EBT: 400, EBR: 60, WBT: 300, NBT: 120, NBR: 40 }), PM: vols({ EBT: 350 }) },
    balanced: { AM: vols({ EBL: 145, EBT: 400, EBR: 60, WBT: 288, NBT: 120, NBR: 55 }), PM: vols({ EBT: 350 }) },
  }
}
function buildSeed() {
  return {
    project: { name: 'render-check corridor (synthetic)' },
    intersections: [mkInt('i1', 1, 'Main St & 1st Ave'), mkInt('i2', 2, 'Main St & 2nd Ave'), mkInt('i3', 3, 'Main St & 3rd Ave')],
    links: [
      { id: 'l1', fromId: 'i1', toId: 'i2', direction: 'EB/WB', mode: 'Full' },
      { id: 'l2', fromId: 'i2', toId: 'i3', direction: 'EB/WB', mode: 'Full' },
    ],
    analysis: {
      corridorDir: 'EB/WB',
      lastRun: {
        timestamp: '2026-01-01T00:00:00Z', method: 'larger',
        resolvedLinks: { AM: [
          { fromNum: 1, toNum: 2, direction: 'EB', volume: 465, reconciliation_delta: 5 },
          { fromNum: 2, toNum: 3, direction: 'EB', volume: 470, reconciliation_delta: -3 }], PM: [] },
        iterations: { AM: { 1: 12, 2: 14, 3: 500 }, PM: { 1: 10, 2: 11, 3: 12 } },
        intConverged: { AM: { 1: true, 2: true, 3: false }, PM: { 1: true, 2: true, 3: true } },
        finalResidual: { AM: { 1: 0, 2: 12.6, 3: 48.2 }, PM: { 1: 0, 2: 0, 3: 0 } },
        linkConservation: { AM: [], PM: [] },
        movementsReview: { AM: [
          { int_num: 1, movement: 'EBL', raw: 120, balanced: 145, delta: 25 },
          { int_num: 1, movement: 'WBT', raw: 300, balanced: 288, delta: -12 },
          { int_num: 1, movement: 'NBR', raw: 40, balanced: 55, delta: 15 },
          { int_num: 1, movement: 'EBT', raw: 400, balanced: 400, delta: 0 }], PM: [] },
        qcFlags: [{ check: 'SOURCE-OUTLIER', int: 2, period: 'AM', message: 'Int 2 EB approach total = 1975 veh — verify the source count.' }],
        config: { linkResolution: 'larger', peakMode: 'Corridor', amWindow: { start: '07:00', end: '09:00' },
          pmWindow: { start: '16:00', end: '18:00' }, convergenceThreshold: 0.5, maxIterations: 500, corridorDir: 'EB/WB' },
      },
    },
  }
}

// ---- Chrome discovery + launch ----
function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
  ].filter(Boolean)
  return candidates.find((c) => existsSync(c)) || null
}

async function reachable(url) {
  try {
    const res = await fetch(url, { method: 'GET' })
    return res.status > 0
  } catch { return false }
}

async function waitForCDP(port, ms = 10000) {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/version`)
      if (r.ok) return await r.json()
    } catch { /* not up yet */ }
    await sleep(200)
  }
  return null
}

// ---- minimal CDP client over the global WebSocket ----
function cdpClient(ws) {
  let id = 0
  const pending = new Map()
  const listeners = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id)
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result)
    } else if (m.method) {
      for (const l of listeners) l(m)
    }
  })
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id; pending.set(mid, { res, rej })
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
  send.on = (fn) => listeners.push(fn)
  return send
}
async function evaluate(send, expression) {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (r.exceptionDetails) throw new Error('page eval threw: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text))
  return r?.result?.value
}

async function main() {
  // Resolve the seed first: built-in default, or a JSON file via --seed.
  let seed = buildSeed()
  if (SEED_ARG) {
    const p = resolveSeedPath(SEED_ARG)
    if (!p) { fail(`--seed file not found: ${SEED_ARG} (looked in CWD and ${REPO_ROOT})`); return }
    try { seed = JSON.parse(readFileSync(p, 'utf8')) }
    catch (e) { fail(`--seed file is not valid JSON (${p}): ${e.message}`); return }
  }

  const chrome = findChrome()
  if (!chrome) { fail('no Chrome/Chromium binary found (set CHROME_PATH)'); return }

  // Servers must be up — otherwise a "blank" is an environment problem, not a code bug.
  if (!(await reachable(ORIGIN))) { fail(`dev server not reachable at ${ORIGIN} — start it (cd frontend && npm run dev)`); return }
  if (!(await reachable(BACKEND))) { fail(`backend not reachable at ${BACKEND} — start it (cd backend && .venv-forecasting/bin/python app.py)`); return }

  const userDataDir = mkdtempSync(join(tmpdir(), 'render-check-'))
  const child = spawn(chrome, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDataDir}`,
    '--window-size=1400,1600', 'about:blank',
  ], { stdio: 'ignore' })

  let ws
  const cleanup = () => {
    try { ws?.close() } catch { /* ignore */ }
    try { child.kill('SIGKILL') } catch { /* ignore */ }
    try { rmSync(userDataDir, { recursive: true, force: true }) } catch { /* ignore */ }
  }

  try {
    const ver = await waitForCDP(PORT)
    if (!ver) { fail('Chrome DevTools endpoint did not come up'); cleanup(); return }

    const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${ORIGIN}/`, { method: 'PUT' })).json()
    ws = new WebSocket(target.webSocketDebuggerUrl)
    await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j) })
    const send = cdpClient(ws)
    await send('Page.enable'); await send('Runtime.enable')

    const consoleErrors = []
    send.on((m) => {
      if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
        consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
      } else if (m.method === 'Runtime.exceptionThrown') {
        consoleErrors.push('uncaught: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text))
      }
    })

    // Seed at the origin, then navigate to the route so the store hydrates from localStorage.
    await send('Page.navigate', { url: `${ORIGIN}/` })
    await sleep(1500)
    await evaluate(send, `localStorage.setItem('demandiq:project', ${JSON.stringify(JSON.stringify(seed))})`)
    await send('Page.navigate', { url: `${ORIGIN}${ROUTE}` })

    // Optional pre-step: click a button (matched by visible text) to reveal a
    // diagram that only renders after an interaction, e.g. S8's "Preview AM + PM".
    if (CLICK_TEXT) {
      let clicked = false
      const clickDeadline = Date.now() + 6000
      while (Date.now() < clickDeadline) {
        clicked = await evaluate(send, `(() => {
          const b = [...document.querySelectorAll('button')].find((x) => x.textContent.includes(${JSON.stringify(CLICK_TEXT)}))
          if (b) { b.click(); return true }
          return false
        })()`)
        if (clicked) break
        await sleep(300)
      }
      if (!clicked) { fail(`--click button not found: "${CLICK_TEXT}" at ${ROUTE}`); cleanup(); return }
      await sleep(1500) // let the click's fetch kick off before polling
    }

    // Poll for the render: root present AND the required image has real pixels.
    const check = `(() => {
      const root = document.querySelector(${JSON.stringify(ROOT_SEL)})
      const img = document.querySelector(${JSON.stringify(IMAGE_SEL)})
      const banner = document.querySelector('.di-banner')
      return {
        root: !!root,
        img: img ? { w: img.naturalWidth, h: img.naturalHeight, complete: img.complete } : null,
        banner: banner ? banner.innerText : null,
      }
    })()`
    let state = null
    const deadline = Date.now() + 9000
    while (Date.now() < deadline) {
      state = await evaluate(send, check)
      if (state.root && state.img && state.img.w > 0) break
      await sleep(300)
    }

    // Screenshot for a human to inspect on failure.
    const shot = await send('Page.captureScreenshot', { format: 'png' })
    const shotPath = join(tmpdir(), 'render-check.png')
    writeFileSync(shotPath, Buffer.from(shot.data, 'base64'))

    // Assertions.
    if (!state.root) fail(`root selector ${ROOT_SEL} did not render at ${ROUTE}`)
    if (!state.img) fail(`required image ${IMAGE_SEL} is ABSENT — component rendered blank (screenshot: ${shotPath})${state.banner ? ` [banner: ${state.banner}]` : ''}`)
    else if (!(state.img.w > 0)) fail(`required image ${IMAGE_SEL} has zero natural width — blank/broken image (screenshot: ${shotPath})`)
    if (consoleErrors.length) fail(`console errors on render:\n  - ${consoleErrors.join('\n  - ')}`)

    if (!process.exitCode) {
      console.log(`render-check: PASS — ${ROUTE} rendered; ${IMAGE_SEL} = ${state.img.w}x${state.img.h}; 0 console errors`)
    }
  } catch (e) {
    fail(e.stack || String(e))
  } finally {
    cleanup()
  }
}

main()
