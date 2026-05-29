// Stage 10.3 — bulk volume paste/import (pure parser).
//
// Parses a header-row-matched TSV/CSV block (as copied from Excel / Google
// Sheets) into per-(intersection, period) volume rows. Multi-intersection:
// one data row per intersection-period, matched to a project intersection by
// an Int# column. Column→movement mapping is by HEADER NAME (order-agnostic).
//
// PRD-04 tolerance: K-suffix values (1.2K → 1200), header variants
// (Movement/Direction; LT/TH/RT/U for movement-suffix columns), no-header
// paste (first row is data), mixed column orders, and partial-failure
// (one bad row does not reject the rest — row N is flagged inline).
//
// Pure — no React, no store, no DOM. The S4 modal renders the preview and
// calls applyParsedRows() with the store setters. Node-testable in isolation.

export const MOVEMENT_CODES = [
  'EBU', 'EBL', 'EBT', 'EBR',
  'WBU', 'WBL', 'WBT', 'WBR',
  'NBU', 'NBL', 'NBT', 'NBR',
  'SBU', 'SBL', 'SBT', 'SBR',
]
const MOVEMENT_SET = new Set(MOVEMENT_CODES)
const DIRECTIONS = ['EB', 'WB', 'NB', 'SB']
const DIRECTION_SET = new Set(DIRECTIONS)

// Header synonyms (compared after normalization: upper, no whitespace, no punctuation).
const INT_HEADERS    = new Set(['INT#', 'INT', 'INTERSECTION', '#', 'NUM', 'INTNUM', 'INT_NUM'])
const PERIOD_HEADERS = new Set(['PERIOD', 'PER', 'TIME', 'PEAK'])
const PHF_HEADERS    = new Set(['PHF'])
const HV_HEADERS     = new Set(['HV', 'HV%', 'HVPCT', 'HV_PCT', 'HEAVY', 'HEAVYVEHICLE', 'HVPERCENT'])
// PRD-04: a "direction"/"movement"/"mvt" column carries the per-row direction
// prefix (EB/WB/NB/SB) when paired with suffix-only movement columns.
const MVT_DIR_HEADERS = new Set(['MVT', 'MOVEMENT', 'DIR', 'DIRECTION', 'APPROACH', 'LEG'])

// Movement-suffix headers (case-insensitive) → suffix char in 'ULTR'.
// Used only when a MVT_DIR header is also present (resolves per-row to EB+L etc).
const SUFFIX_ALIASES = new Map([
  ['L',  'L'], ['LT',  'L'], ['LEFT',  'L'], ['LEFTS',  'L'],
  ['T',  'T'], ['TH',  'T'], ['THRU',  'T'], ['THROUGH', 'T'], ['THRUS', 'T'],
  ['R',  'R'], ['RT',  'R'], ['RIGHT', 'R'], ['RIGHTS', 'R'],
  ['U',  'U'], ['UT',  'U'], ['UTURN', 'U'], ['U-TURN', 'U'],
])

function normHeader(h) {
  return String(h ?? '').trim().toUpperCase().replace(/\s+/g, '')
}

// Delimiter is detected once from the first non-empty line and applied to every line:
// tab (Excel/Sheets paste) → comma (CSV) → runs of whitespace (fallback).
function detectDelimiter(line) {
  if (line.includes('\t')) return '\t'
  if (line.includes(',')) return ','
  return /\s+/
}

function splitLine(line, delim) {
  if (delim instanceof RegExp) return line.trim().split(delim)
  return line.split(delim).map((c) => c.trim())
}

// PRD-04: accept K-suffix (1.2K → 1200, 1.5k → 1500) in addition to plain
// non-negative numbers. Returns Number or NaN if unparseable. Empty string
// is treated as NaN by callers that check for blank first.
export function parseVolumeNumeric(raw) {
  if (raw == null) return NaN
  const s = String(raw).trim()
  if (s === '') return NaN
  const m = /^(-?\d+(?:\.\d+)?)\s*[Kk]$/.exec(s)
  if (m) {
    const base = Number(m[1])
    return Number.isFinite(base) ? base * 1000 : NaN
  }
  // Allow inner commas in thousands (Excel sometimes pastes "1,200")
  const stripped = /^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(s) ? s.replace(/,/g, '') : s
  const n = Number(stripped)
  return Number.isFinite(n) ? n : NaN
}

// Recognize a normalized header token as "any known header role".
// Used to decide whether row-1 is a header or data.
function isKnownHeader(h) {
  if (!h) return false
  if (INT_HEADERS.has(h) || PERIOD_HEADERS.has(h)) return true
  if (PHF_HEADERS.has(h) || HV_HEADERS.has(h)) return true
  if (MOVEMENT_SET.has(h)) return true
  if (MVT_DIR_HEADERS.has(h)) return true
  if (SUFFIX_ALIASES.has(h)) return true
  return false
}

// Active movement codes for an intersection, from its approach lane config.
// Used to warn (and skip) when a pasted cell targets a movement that doesn't
// exist at that intersection — the grid wouldn't show it anyway.
function activeCodeSet(it) {
  const out = new Set()
  for (const d of DIRECTIONS) {
    const ap = it.approaches?.[d]
    if (!ap || ap.exists === false) continue
    for (const lane of ap.lanes || []) {
      for (const ch of lane.movement || '') {
        if ('ULTR'.includes(ch)) out.add(d + ch)
      }
    }
  }
  return out
}

// Build the column map from a header row. Recognizes:
//   - Int#/Period/PHF/HV synonyms (INT_HEADERS, etc).
//   - Full movement codes (EBL, EBT, …).
//   - Mvt/Direction column + suffix-only columns (LT/TH/RT/U) — resolved per-row.
function buildColumnMap(headers) {
  const colMap = {
    int: -1, period: -1, phf: -1, hv: -1,
    movements: {},   // full code → column index (positional path)
    mvtDir: -1,      // direction column index (per-row path)
    suffixes: {},    // suffix char ('L','T','R','U') → column index
  }
  headers.forEach((h, i) => {
    if (INT_HEADERS.has(h)) colMap.int = i
    else if (PERIOD_HEADERS.has(h)) colMap.period = i
    else if (PHF_HEADERS.has(h)) colMap.phf = i
    else if (HV_HEADERS.has(h)) colMap.hv = i
    else if (MOVEMENT_SET.has(h)) colMap.movements[h] = i
    else if (MVT_DIR_HEADERS.has(h)) colMap.mvtDir = i
    else if (SUFFIX_ALIASES.has(h)) colMap.suffixes[SUFFIX_ALIASES.get(h)] = i
  })
  return colMap
}

// Synthesise a header row when the user pasted data only.
//   - 2 cols, col0 = movement code: ['MVT_CODE', 'VAL'] → vertical EBL=100 paste.
//   - else fall back to the canonical template positions, matching as many
//     of [Int#, Period, EBL, EBT, EBR, WBL, …, SBR, PHF, HV] as fit. This
//     mirrors the modal's PASTE_TEMPLATE header (no U-turn columns, which
//     are rare in practice and would shift the user's expected positions).
function inferPositionalHeader(firstRow) {
  const ncols = firstRow.length
  if (ncols === 2) {
    const c0 = normHeader(firstRow[0])
    if (MOVEMENT_SET.has(c0)) return ['__MVT_CODE__', '__VAL__']
  }
  const TEMPLATE_NO_U = MOVEMENT_CODES.filter((c) => !c.endsWith('U'))
  const canonical = ['INT#', 'PERIOD', ...TEMPLATE_NO_U, 'PHF', 'HV']
  return canonical.slice(0, ncols)
}

/**
 * Parse pasted bulk-volume text.
 * @param text  the pasted TSV/CSV block (header row + data rows; OR data-only)
 * @param opts.intersections  project intersections [{ id, num, name, approaches }]
 * @returns {
 *   headerMap, rows, errors, applicableRows, applicableCells, totalDataRows,
 *   skippedRows, vertical
 * } — `errors` here are header-level (fatal); per-row issues live on each row.
 */
export function parseBulkVolumes(text, { intersections = [] } = {}) {
  const result = {
    headerMap: null,
    rows: [],
    errors: [],
    applicableRows: 0,
    applicableCells: 0,
    totalDataRows: 0,
    skippedRows: 0,
    vertical: false,    // true when single-intersection EBL=100 style paste
  }
  if (!text || !text.trim()) return result

  const lines = text.replace(/\r\n?/g, '\n').split('\n').filter((l) => l.trim() !== '')
  if (lines.length < 1) return result

  const delim = detectDelimiter(lines[0])
  const firstCells = splitLine(lines[0], delim)
  const firstNorm = firstCells.map(normHeader)

  // PRD-04: vertical / single-intersection paste — 2 cells, col 0 is a
  // movement code, col 1 looks numeric. The movement code IS a known
  // header, but it's also a value here, so detect this shape explicitly.
  const isVerticalShape =
    firstCells.length === 2 &&
    MOVEMENT_SET.has(firstNorm[0]) &&
    Number.isFinite(parseVolumeNumeric(firstCells[1]))

  // PRD-04: detect no-header paste. If none of the first-row tokens are a known
  // header role AND the last cell parses as a number, treat row 1 as data
  // and synthesise positional headers from the canonical template.
  const anyKnownHeader = firstNorm.some(isKnownHeader)
  const looksLikeData =
    isVerticalShape ||
    (!anyKnownHeader &&
      Number.isFinite(parseVolumeNumeric(firstCells[firstCells.length - 1])))

  let headerLineCount = 1
  let headers
  if (looksLikeData) {
    headers = inferPositionalHeader(firstCells).map(normHeader)
    headerLineCount = 0
  } else {
    headers = firstNorm
  }

  // Vertical / single-intersection paste: header = ['__MVT_CODE__', '__VAL__'].
  if (headers[0] === '__MVT_CODE__' && headers[1] === '__VAL__') {
    return parseVerticalSingleIntersection(lines, delim, result)
  }

  // Need at least one data row for the multi-int horizontal path.
  if (lines.length - headerLineCount < 1) {
    result.errors.push('Need a header row plus at least one data row.')
    return result
  }

  const colMap = buildColumnMap(headers)
  result.headerMap = colMap

  if (colMap.int < 0) result.errors.push('No "Int#" column in the header row.')
  if (colMap.period < 0) result.errors.push('No "Period" column in the header row.')
  const hasFullMovements = Object.keys(colMap.movements).length > 0
  const hasSuffixMovements = Object.keys(colMap.suffixes).length > 0 && colMap.mvtDir >= 0
  if (!hasFullMovements && !hasSuffixMovements) {
    result.errors.push(
      'No movement columns (EBL, EBT, … or a Movement/Direction column with LT/TH/RT).'
    )
  }
  if (result.errors.length) return result

  const byNum = new Map(intersections.map((it) => [String(it.num), it]))

  for (let li = headerLineCount; li < lines.length; li++) {
    result.totalDataRows += 1
    const cells = splitLine(lines[li], delim)
    const intRaw = (cells[colMap.int] ?? '').trim()
    const perRaw = (cells[colMap.period] ?? '').trim().toUpperCase()
    const rowNo = li + 1
    const row = {
      lineNo: rowNo,
      intNum: intRaw,
      intId: null,
      intName: null,
      period: perRaw,
      cells: {},
      phf: null,
      hv: null,
      warnings: [],
      errors: [],
      applicable: false,
    }

    const it = byNum.get(intRaw)
    if (!it) row.errors.push(`row ${rowNo}: no project intersection #${intRaw || '?'}`)
    else { row.intId = it.id; row.intName = it.name }

    if (perRaw !== 'AM' && perRaw !== 'PM')
      row.errors.push(`row ${rowNo}: period must be AM or PM (got "${cells[colMap.period] ?? ''}")`)

    const active = it ? activeCodeSet(it) : null

    // Movement values: full-code columns OR suffix columns scoped by Mvt/Dir.
    const writeCell = (code, raw) => {
      if (raw === '' || raw == null) return
      const n = parseVolumeNumeric(raw)
      if (!Number.isFinite(n) || n < 0) {
        row.errors.push(`row ${rowNo}: unparseable value "${raw}" for ${code}`)
        return
      }
      if (active && active.size > 0 && !active.has(code)) {
        row.warnings.push(`${code} is not an active movement here — skipped`)
        return
      }
      row.cells[code] = n
    }

    for (const [code, ci] of Object.entries(colMap.movements)) {
      writeCell(code, (cells[ci] ?? '').trim())
    }

    if (hasSuffixMovements) {
      const dirRaw = (cells[colMap.mvtDir] ?? '').trim().toUpperCase()
      if (dirRaw) {
        if (!DIRECTION_SET.has(dirRaw)) {
          row.errors.push(`row ${rowNo}: unrecognised direction "${dirRaw}" (expected EB/WB/NB/SB)`)
        } else {
          for (const [suf, ci] of Object.entries(colMap.suffixes)) {
            writeCell(dirRaw + suf, (cells[ci] ?? '').trim())
          }
        }
      }
    }

    const scalar = (ci, label) => {
      if (ci < 0) return null
      const raw = (cells[ci] ?? '').trim()
      if (raw === '') return null
      const n = parseVolumeNumeric(raw)
      if (Number.isFinite(n) && n >= 0) return n
      row.warnings.push(`${label}="${raw}" ignored (not a number)`)
      return null
    }
    row.phf = scalar(colMap.phf, 'PHF')
    row.hv = scalar(colMap.hv, 'HV')

    const cellCount = Object.keys(row.cells).length
    row.applicable = row.errors.length === 0 &&
      (cellCount > 0 || row.phf != null || row.hv != null)
    if (row.applicable) {
      result.applicableRows += 1
      result.applicableCells += cellCount
    } else if (row.errors.length > 0) {
      result.skippedRows += 1
    }
    result.rows.push(row)
  }

  return result
}

// Vertical / per-row "movement code, value" paste. Single intersection, no
// Int#/Period — the caller (S4 modal) is expected to supply context (selected
// intersection + period) downstream. We surface a single synthesised row with
// `row.cells` populated. Used in AC #1 ("EBL\t1.2K\nEBT\t800" → EBL:1200, EBT:800).
function parseVerticalSingleIntersection(lines, delim, result) {
  result.vertical = true
  const row = {
    lineNo: 1,
    intNum: '',
    intId: null,
    intName: null,
    period: '',
    cells: {},
    phf: null,
    hv: null,
    warnings: [],
    errors: [],
    applicable: false,
  }
  for (let li = 0; li < lines.length; li++) {
    result.totalDataRows += 1
    const rowNo = li + 1
    const cells = splitLine(lines[li], delim)
    const codeRaw = normHeader(cells[0])
    const valRaw = (cells[1] ?? '').trim()
    if (!MOVEMENT_SET.has(codeRaw)) {
      row.errors.push(`row ${rowNo}: unknown movement code "${cells[0]}"`)
      result.skippedRows += 1
      continue
    }
    if (valRaw === '') continue
    const n = parseVolumeNumeric(valRaw)
    if (!Number.isFinite(n) || n < 0) {
      row.errors.push(`row ${rowNo}: unparseable value "${valRaw}" for ${codeRaw}`)
      result.skippedRows += 1
      continue
    }
    row.cells[codeRaw] = n
  }
  const cellCount = Object.keys(row.cells).length
  row.applicable = cellCount > 0
  if (row.applicable) {
    result.applicableRows = 1
    result.applicableCells = cellCount
  }
  result.rows.push(row)
  return result
}

/**
 * Apply parsed rows to the store. Writes movement cells as _source:'manual'.
 * Setters are injected so this stays testable.
 * @returns { cells, intersections } counts actually written.
 */
export function applyParsedRows(rows, { setCellValue, setPhf, setHvPct }) {
  let cells = 0
  const touched = new Set()
  for (const row of rows) {
    if (!row.applicable || !row.intId) continue
    for (const [code, val] of Object.entries(row.cells)) {
      setCellValue(row.intId, row.period, code, val, 'manual')
      cells += 1
    }
    if (row.phf != null && setPhf) setPhf(row.intId, row.period, row.phf)
    if (row.hv != null && setHvPct) setHvPct(row.intId, row.period, row.hv)
    touched.add(row.intId)
  }
  return { cells, intersections: touched.size }
}
