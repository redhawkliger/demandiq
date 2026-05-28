// Stage 10.3 — bulk-paste parser tests. Pure ESM, no test runner required:
//   node src/lib/bulkPaste.test.mjs
import { parseBulkVolumes, applyParsedRows } from './bulkPaste.js'

let passed = 0, failed = 0
function ok(cond, msg) {
  if (cond) { passed++ } else { failed++; console.error('  FAIL:', msg) }
}

// Project: int 1 has all approaches/movements; int 2 has only EB+WB through.
const LTR = [{ movement: 'LTR' }]
const intersections = [
  {
    id: 'i1', num: 1, name: 'A & B',
    approaches: {
      EB: { exists: true, lanes: LTR }, WB: { exists: true, lanes: LTR },
      NB: { exists: true, lanes: LTR }, SB: { exists: true, lanes: LTR },
    },
  },
  {
    id: 'i2', num: 2, name: 'C & D',
    approaches: {
      EB: { exists: true, lanes: [{ movement: 'T' }] },
      WB: { exists: true, lanes: [{ movement: 'T' }] },
      NB: { exists: false }, SB: { exists: false },
    },
  },
]

// ── 1. Header-matched, order-independent, tab-delimited ──────────────────
const tsv = [
  'Int#\tPeriod\tEBL\tEBT\tWBT\tPHF',
  '1\tAM\t37\t1898\t943\t0.95',
  '1\tPM\t74\t1266\t1675\t0.97',
].join('\n')
let r = parseBulkVolumes(tsv, { intersections })
ok(r.errors.length === 0, `no header errors: ${r.errors}`)
ok(r.rows.length === 2, `2 data rows, got ${r.rows.length}`)
ok(r.rows[0].intId === 'i1' && r.rows[0].period === 'AM', 'row0 matched int1 AM')
ok(r.rows[0].cells.EBT === 1898, `EBT=1898, got ${r.rows[0].cells.EBT}`)
ok(r.rows[0].phf === 0.95, `PHF=0.95, got ${r.rows[0].phf}`)
ok(r.applicableRows === 2 && r.applicableCells === 6, `applicable 2 rows / 6 cells, got ${r.applicableRows}/${r.applicableCells}`)

// ── 2. Column order shuffled + comma-delimited → still matched by name ───
const csv = 'PHF,EBT,Period,Int#,EBL\n0.9,1000,AM,1,80'
r = parseBulkVolumes(csv, { intersections })
ok(r.errors.length === 0, 'shuffled CSV parses')
ok(r.rows[0].cells.EBT === 1000 && r.rows[0].cells.EBL === 80, 'shuffled columns mapped by name')
ok(r.rows[0].phf === 0.9, 'shuffled PHF mapped')

// ── 3. Unmatched int# + bad period + negative value → per-row errors ─────
const bad = [
  'Int#\tPeriod\tEBT',
  '99\tAM\t100',     // no project int 99
  '1\tMID\t100',     // bad period
  '1\tAM\t-5',       // negative
].join('\n')
r = parseBulkVolumes(bad, { intersections })
ok(r.rows[0].errors.some((e) => e.includes('99')), 'unmatched int flagged')
ok(r.rows[1].errors.some((e) => e.includes('AM or PM')), 'bad period flagged')
ok(r.rows[2].errors.some((e) => e.includes('non-negative')), 'negative flagged')
ok(r.applicableRows === 0, `no applicable rows in bad input, got ${r.applicableRows}`)

// ── 4. Inactive movement at int2 (no NB/SB, no turns) → warn + skip ──────
const inactive = 'Int#\tPeriod\tEBT\tNBL\n2\tAM\t900\t50'
r = parseBulkVolumes(inactive, { intersections })
ok(r.rows[0].cells.EBT === 900, 'active EBT kept at int2')
ok(!('NBL' in r.rows[0].cells), 'inactive NBL skipped at int2')
ok(r.rows[0].warnings.some((w) => w.includes('NBL')), 'inactive NBL warned')

// ── 5. Blank cells left untouched (not written as 0) ─────────────────────
const blanks = 'Int#\tPeriod\tEBL\tEBT\n1\tAM\t\t1898'
r = parseBulkVolumes(blanks, { intersections })
ok(!('EBL' in r.rows[0].cells), 'blank EBL not written')
ok(r.rows[0].cells.EBT === 1898, 'present EBT written')

// ── 6. Missing required column → fatal header error ──────────────────────
r = parseBulkVolumes('EBL\tEBT\n10\t20', { intersections })
ok(r.errors.some((e) => e.includes('Int#')), 'missing Int# header errors')

// ── 7. applyParsedRows writes via injected setters, manual source ────────
r = parseBulkVolumes(tsv, { intersections })
const writes = []
const stats = applyParsedRows(r.rows, {
  setCellValue: (id, p, code, v, src) => writes.push({ id, p, code, v, src }),
  setPhf: () => {},
  setHvPct: () => {},
})
ok(stats.cells === 6, `wrote 6 cells, got ${stats.cells}`)
ok(stats.intersections === 1, `touched 1 intersection, got ${stats.intersections}`)
ok(writes.every((w) => w.src === 'manual'), 'all writes tagged manual')
ok(writes.some((w) => w.code === 'EBT' && w.v === 1898 && w.p === 'AM'), 'EBT AM write present')

console.log(`\n${'='.repeat(46)}\n  ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
