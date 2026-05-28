import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FileSpreadsheet,
  FileJson,
  FileText,
  Image as ImageIcon,
  Loader2,
} from 'lucide-react'

import { subscribe, getSnapshot } from '../store/projectStore'
import { buildGridCell } from '../lib/diagramPayload'

import '../styles/forms.css'
import '../styles/map.css'        // .di-modal*, .di-banner, .di-btn-primary, .di-btn-secondary
import '../styles/export.css'

const GRID_VIEWS = ['combined', 'balanced', 'unbalanced', 'delta']
const GRID_PERIODS = ['Both', 'AM', 'PM']

const STORAGE_KEY = 'demandiq:project'

function hasAnyBalanced(intersections) {
  for (const it of intersections) {
    if (it.balanced?.AM && Object.keys(it.balanced.AM).length > 0) return true
    if (it.balanced?.PM && Object.keys(it.balanced.PM).length > 0) return true
  }
  return false
}

const slugify = (s) =>
  String(s ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'project'

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function S8_Export() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const project = snap.project || {}
  const balancing = snap.balancing || {}
  const lastRun = snap.analysis?.lastRun ?? null

  const needsRun = intersections.length === 0 || !hasAnyBalanced(intersections)

  // Empty / unconfigured guard
  useEffect(() => {
    if (!needsRun) return
    const t = setTimeout(() => navigate('/results'), 1000)
    return () => clearTimeout(t)
  }, [needsRun, navigate])

  // Local UI state
  const [filename, setFilename] = useState(() => slugify(project.name || 'project'))
  const [excelStatus, setExcelStatus] = useState('idle')   // idle | loading | error
  const [excelError, setExcelError] = useState(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  // Stage 10.5: diagram batch (composite grid PNG)
  const [gridPeriod, setGridPeriod] = useState('Both')
  const [gridView, setGridView] = useState('combined')
  const [gridStatus, setGridStatus] = useState('idle')     // idle | loading | error
  const [gridError, setGridError] = useState(null)

  if (needsRun) {
    return (
      <div className="di-s8 di-s8--center">
        <div className="di-s8-empty">
          <div className="di-banner">Generate results first.</div>
          <p style={{ fontSize: 13, color: 'var(--text-tertiary)', margin: 0 }}>Redirecting…</p>
        </div>
      </div>
    )
  }

  // ── Excel download ──────────────────────────────────────────────────
  const downloadExcel = async () => {
    setExcelStatus('loading')
    setExcelError(null)
    try {
      const res = await fetch('/api/export-excel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(snap),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch {}
        throw new Error(detail)
      }
      const blob = await res.blob()
      triggerBlobDownload(blob, `${filename}.xlsx`)
      setExcelStatus('idle')
    } catch (err) {
      setExcelError(
        `${err.message}. Make sure the backend is running (cd backend && python3.12 app.py).`
      )
      setExcelStatus('error')
    }
  }

  // ── JSON download ───────────────────────────────────────────────────
  const downloadJson = () => {
    const json = JSON.stringify(snap, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    triggerBlobDownload(blob, `${filename}.demandiq.json`)
  }

  // ── Diagram batch (composite grid PNG) ──────────────────────────────
  const downloadDiagramGrid = async () => {
    setGridStatus('loading')
    setGridError(null)
    try {
      const overrides = snap.balancing?.overrides ?? { AM: {}, PM: {} }
      const periods = gridPeriod === 'Both' ? ['AM', 'PM'] : [gridPeriod]
      // Cells ordered intersection-major: Int1 AM, Int1 PM, Int2 AM, … so an
      // intersection's two periods sit adjacent in the grid.
      const cells = []
      for (const it of intersections) {
        for (const p of periods) cells.push(buildGridCell(it, p, overrides))
      }
      if (cells.length === 0) throw new Error('No intersections to export')

      const title = `${project.name || 'Project'} — ${gridPeriod} · ${gridView}`
      const res = await fetch('/api/export-diagram-grid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cells, view_mode: gridView, cols: 3, title }),
      })
      if (!res.ok) {
        let detail = `HTTP ${res.status}`
        try { const j = await res.json(); if (j?.detail) detail = j.detail } catch {}
        throw new Error(detail)
      }
      const blob = await res.blob()
      triggerBlobDownload(blob, `${filename}_diagrams_${gridPeriod}_${gridView}.png`)
      setGridStatus('idle')
    } catch (err) {
      setGridError(
        `${err.message}. Make sure the backend is running (cd backend && python3.12 app.py).`
      )
      setGridStatus('error')
    }
  }

  // ── New project ─────────────────────────────────────────────────────
  const confirmNewProject = () => {
    localStorage.removeItem(STORAGE_KEY)
    // Hard reload to clear every component's local state cleanly.
    window.location.href = '/'
  }

  // ── Summary derivation ──────────────────────────────────────────────
  const intCount = intersections.length
  const corridor = balancing.corridorDir ?? snap.analysis?.corridorDir ?? '—'
  const convPct = ((balancing.convergenceThreshold ?? 0.01) * 100).toFixed(1)
  const amConv = lastRun?.convergence?.AM
  const pmConv = lastRun?.convergence?.PM
  const convergedCount = (amConv?.converged ? 1 : 0) + (pmConv?.converged ? 1 : 0)
  const qcCount = lastRun?.qcFlags?.length ?? 0

  return (
    <div className="di-s8">
      <div className="di-s8__body">
        <div className="di-s8__inner">

          {/* ── Project summary card ────────────────────────────────── */}
          <div className="di-s8-summary">
            <div className="di-s8-summary__eyebrow">Ready to Export</div>
            <h1 className="di-s8-summary__title">{project.name || 'Untitled Project'}</h1>
            <div className="di-s8-summary__grid">
              <SumRow k="Client"        v={project.client || '—'} />
              <SumRow k="Analyst"       v={project.analyst || '—'} />
              <SumRow k="Intersections" v={String(intCount)} />
              <SumRow k="Date"          v={project.date || '—'} />
              <SumRow k="Scenario"      v={project.scenario || '—'} />
              <SumRow k="Corridor"      v={corridor === 'EW' ? 'EB/WB' : corridor === 'NS' ? 'NB/SB' : corridor} />
              <SumRow k="Convergence"   v={`${convPct}% (${convergedCount}/2 converged)`} />
              <SumRow k="QC"            v={qcCount === 0 ? 'Clean' : `${qcCount} flag${qcCount === 1 ? '' : 's'}`} />
            </div>
          </div>

          {/* ── Filename input ──────────────────────────────────────── */}
          <div className="di-s8-filename">
            <label className="di-s8-filename__label" htmlFor="s8-filename">
              Output file name
            </label>
            <input
              id="s8-filename"
              className="di-input"
              type="text"
              value={filename}
              onChange={(e) => setFilename(slugify(e.target.value) || 'project')}
              spellCheck={false}
              autoComplete="off"
            />
            <span className="di-s8-filename__hint">
              Used as the base for all downloads. Extensions are added automatically.
            </span>
          </div>

          {/* ── 2x2 export cards ─────────────────────────────────────── */}
          <div className="di-s8-grid">
            {/* Card 1 — Excel */}
            <div className="di-s8-card">
              <div className="di-s8-card__head">
                <div className="di-s8-card__icon"><FileSpreadsheet size={20} /></div>
                <div className="di-s8-card__title-wrap">
                  <div className="di-s8-card__title">Excel Workbook</div>
                </div>
              </div>
              <p className="di-s8-card__desc">
                Multi-sheet workbook with project info, balanced + unbalanced volumes,
                convergence log, QC flags, and top adjustments.
              </p>
              <button
                type="button"
                className="di-btn-primary di-s8-card__btn"
                disabled={excelStatus === 'loading'}
                onClick={downloadExcel}
              >
                {excelStatus === 'loading' ? (
                  <>
                    <Loader2 size={14} className="di-spin" style={{ verticalAlign: '-2px' }} />
                    {' '}Generating…
                  </>
                ) : (
                  <>Download .xlsx</>
                )}
              </button>
              {excelStatus === 'error' && excelError && (
                <div className="di-s8-error">{excelError}</div>
              )}
            </div>

            {/* Card 2 — JSON */}
            <div className="di-s8-card">
              <div className="di-s8-card__head">
                <div className="di-s8-card__icon"><FileJson size={20} /></div>
                <div className="di-s8-card__title-wrap">
                  <div className="di-s8-card__title">Project File</div>
                </div>
              </div>
              <p className="di-s8-card__desc">
                Complete project state — re-import later to continue work.
                Includes all intersections, approaches, volumes, balanced results, and QC flags.
              </p>
              <button
                type="button"
                className="di-btn-primary di-s8-card__btn"
                onClick={downloadJson}
              >
                Download .demandiq.json
              </button>
            </div>

            {/* Card 3 — PDF Report (Phase 2) */}
            <div className="di-s8-card di-s8-card--phase2">
              <div className="di-s8-card__head">
                <div className="di-s8-card__icon"><FileText size={20} /></div>
                <div className="di-s8-card__title-wrap">
                  <div className="di-s8-card__title">PDF Report</div>
                  <span className="di-s8-card__badge">Phase 2</span>
                </div>
              </div>
              <p className="di-s8-card__desc">
                Multi-intersection line diagram report with corridor map and project header.
              </p>
              <button
                type="button"
                className="di-btn-secondary di-s8-card__btn"
                disabled
              >
                Coming soon
              </button>
            </div>

            {/* Card 4 — Diagram grid (composite PNG) */}
            <div className="di-s8-card">
              <div className="di-s8-card__head">
                <div className="di-s8-card__icon"><ImageIcon size={20} /></div>
                <div className="di-s8-card__title-wrap">
                  <div className="di-s8-card__title">Diagram Grid</div>
                </div>
              </div>
              <p className="di-s8-card__desc">
                All intersection diagrams in a single composite image, sized to print
                (3 across). Reflects engineer overrides; each cell is tagged with its period.
              </p>
              <div className="di-s8-grid-opts">
                <label className="di-s8-grid-opt">
                  <span>Period</span>
                  <select
                    className="di-input di-s8-grid-select"
                    value={gridPeriod}
                    onChange={(e) => setGridPeriod(e.target.value)}
                  >
                    {GRID_PERIODS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </label>
                <label className="di-s8-grid-opt">
                  <span>View</span>
                  <select
                    className="di-input di-s8-grid-select"
                    value={gridView}
                    onChange={(e) => setGridView(e.target.value)}
                  >
                    {GRID_VIEWS.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </label>
              </div>
              <button
                type="button"
                className="di-btn-primary di-s8-card__btn"
                disabled={gridStatus === 'loading'}
                onClick={downloadDiagramGrid}
              >
                {gridStatus === 'loading' ? (
                  <>
                    <Loader2 size={14} className="di-spin" style={{ verticalAlign: '-2px' }} />
                    {' '}Rendering…
                  </>
                ) : (
                  <>Download .png</>
                )}
              </button>
              {gridStatus === 'error' && gridError && (
                <div className="di-s8-error">{gridError}</div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Sticky footer ─────────────────────────────────────────── */}
      <footer className="di-s8__footer">
        <button
          type="button"
          className="di-btn-secondary"
          onClick={() => setConfirmOpen(true)}
        >
          Start new project
        </button>
        <span className="di-s8__done">
          🎉 Project complete. Don&apos;t forget to download your work before starting new.
        </span>
      </footer>

      {/* ── Confirm modal ─────────────────────────────────────────── */}
      {confirmOpen && (
        <div className="di-modal-backdrop">
          <div className="di-modal" role="dialog" aria-modal="true">
            <div className="di-modal__header">
              <h2 className="di-modal__title">Start a new project?</h2>
            </div>
            <div className="di-modal__body">
              <p className="di-s8-confirm-msg">
                This clears the current project from your browser. Make sure
                you've exported the Excel workbook or saved the .demandiq.json
                file first — there's no undo.
              </p>
            </div>
            <div className="di-modal__footer">
              <button
                type="button"
                className="di-btn-secondary"
                onClick={() => setConfirmOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="di-btn-primary"
                onClick={confirmNewProject}
              >
                Yes, start new
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SumRow({ k, v }) {
  return (
    <div className="di-s8-summary__row">
      <span className="di-s8-summary__k">{k}</span>
      <span className="di-s8-summary__v">{v}</span>
    </div>
  )
}

