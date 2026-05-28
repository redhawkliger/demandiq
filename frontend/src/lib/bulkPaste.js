// Stage 10.3 — bulk volume paste/import (pure parser).
//
// Parses a header-row-matched TSV/CSV block (as copied from Excel / Google
// Sheets) into per-(intersection, period) volume rows. Multi-intersection:
// one data row per intersection-period, matched to a project intersection by
// an Int# column. Column→movement mapping is by HEADER NAME (order-agnostic).
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

// Header synonyms (compared after normalization: upper, no whitespace).
const INT_HEADERS    = new Set(['INT#', 'INT', 'INTERSECTION', '#', 'NUM', 'INTNUM', 'INT_NUM'])
const PERIOD_HEADERS = new Set(['PERIOD', 'PER', 'TIME', 'PEAK'])
const PHF_HEADERS    = new Set(['PHF'])
const HV_HEADERS     = new Set(['HV', 'HV%', 'HVPCT', 'HV_PCT', 'HEAVY', 'HEAVYVEHICLE', 'HVPERCENT'])

function normHeader(h) {
  return String(h ?? '').trim().toUpperCase().replace(/\s+/g, '')
}

// Delimiter is detected once from the header line and applied to every line:
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

// Active movement codes for an intersection, from its approach lane config.
// Used to warn (and skip) when a pasted cell targets a movement that doesn't
// exist at that intersection — the grid wouldn't show it anyway.
function activeCodeSet(it) {
  const out = new Set()
  for (const d of ['EB', 'WB', 'NB', 'SB']) {
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

/**
 * Parse pasted bulk-volume text.
 * @param text  the pasted TSV/CSV block (header row + data rows)
 * @param opts.intersections  project intersections [{ id, num, name, approaches }]
 * @returns {
 *   headerMap, rows, errors, applicableRows, applicableCells
 * } — `errors` here are header-level (fatal); per-row issues live on each row.
 */
export function parseBulkVolumes(text, { intersections = [] } = {}) {
  const result = { headerMap: null, rows: [], errors: [], applicableRows: 0, applicableCells: 0 }
  if (!text || !text.trim()) return result

  const lines = text.replace(/\r\n?/g, '\n').split('\n').filter((l) => l.trim() !== '')
  if (lines.length < 2) {
    result.errors.push('Need a header row plus at least one data row.')
    return result
  }

  const delim = detectDelimiter(lines[0])
  const headers = splitLine(lines[0], delim).map(normHeader)

  const colMap = { int: -1, period: -1, phf: -1, hv: -1, movements: {} }
  headers.forEach((h, i) => {
    if (INT_HEADERS.has(h)) colMap.int = i
    else if (PERIOD_HEADERS.has(h)) colMap.period = i
    else if (PHF_HEADERS.has(h)) colMap.phf = i
    else if (HV_HEADERS.has(h)) colMap.hv = i
    else if (MOVEMENT_SET.has(h)) colMap.movements[h] = i
  })
  result.headerMap = colMap

  if (colMap.int < 0) result.errors.push('No "Int#" column in the header row.')
  if (colMap.period < 0) result.errors.push('No "Period" column in the header row.')
  if (Object.keys(colMap.movements).length === 0)
    result.errors.push('No movement columns (EBL, EBT, …) in the header row.')
  if (result.errors.length) return result

  const byNum = new Map(intersections.map((it) => [String(it.num), it]))

  for (let li = 1; li < lines.length; li++) {
    const cells = splitLine(lines[li], delim)
    const intRaw = (cells[colMap.int] ?? '').trim()
    const perRaw = (cells[colMap.period] ?? '').trim().toUpperCase()
    const row = {
      lineNo: li + 1,
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
    if (!it) row.errors.push(`No project intersection #${intRaw || '?'}`)
    else { row.intId = it.id; row.intName = it.name }

    if (perRaw !== 'AM' && perRaw !== 'PM')
      row.errors.push(`Period must be AM or PM (got "${cells[colMap.period] ?? ''}")`)

    const active = it ? activeCodeSet(it) : null

    for (const [code, ci] of Object.entries(colMap.movements)) {
      const raw = (cells[ci] ?? '').trim()
      if (raw === '') continue                      // blank → leave existing untouched
      const n = Number(raw)
      if (!Number.isFinite(n) || n < 0) {
        row.errors.push(`${code}="${raw}" is not a non-negative number`)
        continue
      }
      if (active && active.size > 0 && !active.has(code)) {
        row.warnings.push(`${code} is not an active movement here — skipped`)
        continue
      }
      row.cells[code] = n
    }

    const scalar = (ci, label) => {
      if (ci < 0) return null
      const raw = (cells[ci] ?? '').trim()
      if (raw === '') return null
      const n = Number(raw)
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
    }
    result.rows.push(row)
  }

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
