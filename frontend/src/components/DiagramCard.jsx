import { useEffect, useState } from 'react'
import { Download, Loader2, AlertCircle } from 'lucide-react'

// One per intersection. Presenter — fetch state lives in S7's cache.
//
// Props:
//   intersection: project intersection
//   diagram: { status: 'loading'|'done'|'error', png?, error? } | undefined
//   isSelected: bool
//   onSelect: () => void
//   onRetry: () => void
//   filename: string  (already composed by parent so download matches current view)
//   note: string                  (Stage 10.4 — current diagram annotation)
//   onNoteCommit: (string) => void (commit a new annotation; re-renders the PNG)

function downloadPng(pngBase64, filename) {
  const bin = atob(pngBase64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'image/png' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export default function DiagramCard({
  intersection,
  diagram,
  isSelected,
  onSelect,
  onRetry,
  filename,
  note = '',
  onNoteCommit,
}) {
  const status = diagram?.status ?? 'loading'

  // Local draft; commit on blur / Enter so we re-render the PNG once per edit
  // (not on every keystroke). Re-sync if the stored note changes externally.
  const [draft, setDraft] = useState(note)
  useEffect(() => { setDraft(note) }, [note])

  const commit = () => {
    if ((draft ?? '').trim() !== (note ?? '').trim()) onNoteCommit?.(draft)
  }

  return (
    <div
      className={`di-s7-card${isSelected ? ' di-s7-card--selected' : ''}${status === 'error' ? ' di-s7-card--err' : ''}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onSelect() }}
    >
      <div className="di-s7-card__head">
        <div className="di-s7-card__num">{intersection.num}</div>
        <div className="di-s7-card__name" title={intersection.name}>{intersection.name}</div>
        {status === 'done' && (
          <button
            type="button"
            className="di-s7-card__dl"
            onClick={(e) => { e.stopPropagation(); downloadPng(diagram.png, filename) }}
            aria-label="Download PNG"
            title={`Download ${filename}`}
          >
            <Download size={14} />
          </button>
        )}
      </div>

      <div className="di-s7-card__body">
        {status === 'loading' && (
          <div className="di-s7-card__status">
            <Loader2 size={16} className="di-spin" />
            <span>Rendering diagram…</span>
          </div>
        )}
        {status === 'error' && (
          <div className="di-s7-card__status di-s7-card__status--err">
            <AlertCircle size={16} />
            <span>Failed to render</span>
            <button
              type="button"
              className="di-s7-card__retry"
              onClick={(e) => { e.stopPropagation(); onRetry() }}
            >
              Retry
            </button>
          </div>
        )}
        {status === 'done' && (
          <img
            className="di-s7-card__img"
            src={`data:image/png;base64,${diagram.png}`}
            alt={`Intersection ${intersection.num} line diagram`}
            draggable={false}
          />
        )}
      </div>

      <div className="di-s7-card__note" onClick={(e) => e.stopPropagation()}>
        <input
          type="text"
          className="di-s7-card__note-input"
          placeholder="Add a diagram note…"
          value={draft}
          maxLength={140}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur()
            if (e.key === 'Escape') { setDraft(note); e.currentTarget.blur() }
          }}
          aria-label={`Diagram note for intersection ${intersection.num}`}
        />
      </div>
    </div>
  )
}
