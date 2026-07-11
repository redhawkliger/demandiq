// Static contract guard for IntersectionDiagram's diagram-response field read.
// Run:  node frontend/src/components/reviewMovements/IntersectionDiagram.contract.test.mjs
//
// Regression protected: the /intersection-diagram endpoint returns { png_base64 }
// (backend app.py; S7/F4/S8 all read that key and remap it). IntersectionDiagram
// once read `d.png` — the fetch SUCCEEDED, the value was undefined, and the anchor
// rendered blank with no error banner. Every HTTP-200 / symbol-presence gate missed
// it because it is a runtime-render bug, not a build or import failure.
//
// This is a SOURCE guard, not a behavioral test, because this repo has no React test
// runner by design (logic lives in pure libs; components are untested). It mirrors the
// convergenceThreshold decoy grep-guard used for the ADR tolerance pin. It fails if the
// component reverts to a bare `d.png` read or stops reading png_base64.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const raw = readFileSync(join(here, 'IntersectionDiagram.jsx'), 'utf8')
// Strip comments so the assertions reflect real code, not this file's own prose.
const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')

let passed = 0, failed = 0
function ok(cond, msg) { if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) } }

// Positive: the diagram PNG must be read from the real response key.
ok(/\.png_base64\b/.test(code),
   'reads the diagram PNG via png_base64 (the /intersection-diagram response key)')

// Negative: must NOT read a bare `d.png` — the field that is undefined on the response
// and left the anchor blank. \bd\.png\b matches `d.png)` but not `d.png_base64` (no word
// boundary before `_base64`), so the correct read passes and only the bug trips this.
ok(!/\bd\.png\b/.test(code),
   'does not read d.png (undefined on the response → blank anchor, the fixed bug)')

console.log(`IntersectionDiagram.contract: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
