import { useRef, useState } from 'react'
import { Upload, X, FileText, Loader2, Check, AlertCircle, Info } from 'lucide-react'

const ACCEPT = '.xlsx,.xls,.pdf,.csv'

const STATUS_ICON = {
  pending:    <FileText size={14} className="di-up-file__icon" />,
  processing: <Loader2 size={14} className="di-up-file__icon di-spin" />,
  done:       <Check size={14} className="di-up-file__icon di-up-file__icon--ok" />,
  error:      <AlertCircle size={14} className="di-up-file__icon di-up-file__icon--err" />,
}

const STATUS_LABEL = {
  pending: 'Pending',
  processing: 'Processing…',
  done: 'Done',
  error: 'Error',
}

export default function UploadBar({
  files,
  extracting,
  extractError,
  onAdd,
  onRemove,
  onExtract,
}) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef(null)

  const pendingCount = files.filter((f) => f.status === 'pending').length

  const handlePick = () => inputRef.current?.click()

  const handleInput = (e) => {
    if (e.target.files?.length) onAdd(e.target.files)
    e.target.value = '' // allow re-picking the same file
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer.files?.length) onAdd(e.dataTransfer.files)
  }

  return (
    <div className="di-up">
      <div
        className={`di-up__drop${dragOver ? ' di-up__drop--over' : ''}`}
        onDragEnter={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={handlePick}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') handlePick() }}
      >
        <Upload size={18} className="di-up__drop-icon" />
        <span className="di-up__drop-text">
          Drag count files here, or click to browse
        </span>
        <span className="di-up__drop-hint">.xlsx · .xls · .pdf · .csv</span>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          onChange={handleInput}
          style={{ display: 'none' }}
        />
      </div>

      <div className="di-up__bar">
        <div className="di-up__bar-left">
          {files.length > 0 && (
            <span className="di-up__count">
              {files.length} file{files.length === 1 ? '' : 's'}
              {pendingCount > 0 && ` · ${pendingCount} pending`}
            </span>
          )}
        </div>
        <div className="di-up__bar-right">
          <button
            type="button"
            className="di-up__link"
            onClick={() => setDrawerOpen((o) => !o)}
          >
            <Info size={13} /> View agent instructions
          </button>
          <button
            type="button"
            className="di-btn-primary"
            disabled={extracting || pendingCount === 0}
            onClick={onExtract}
          >
            {extracting ? (
              <>
                <Loader2 size={14} className="di-spin" style={{ verticalAlign: '-2px' }} />
                {' '}Extracting…
              </>
            ) : (
              <>Extract counts ({pendingCount})</>
            )}
          </button>
        </div>
      </div>

      {extractError && (
        <div className="di-banner di-banner--err">{extractError}</div>
      )}

      {drawerOpen && (
        <div className="di-up__drawer">
          <div className="di-up__drawer-title">Extraction agent</div>
          <p>
            Reads turning movement count files (Excel, PDF, CSV) and pulls peak-hour
            volumes for all 16 movements per intersection, plus PHF and heavy-vehicle %.
            Auto-detects the vendor (NDS, Quality Counts, Counts Unlimited, GRAM,
            Pape-Dawson…) and uses 8 in-context reference examples from{' '}
            <span className="di-mono">training_data.jsonl</span> to match the file's layout.
          </p>
          <p>
            For the full system prompt, see{' '}
            <span className="di-mono">backend/count_agent.py</span>.
          </p>
        </div>
      )}

      {files.length > 0 && (
        <ul className="di-up__list">
          {files.map((f) => (
            <li key={f.id} className={`di-up-file di-up-file--${f.status}`}>
              {STATUS_ICON[f.status]}
              <span className="di-up-file__name" title={f.name}>{f.name}</span>
              <span className="di-up-file__status">
                {STATUS_LABEL[f.status]}
                {f.error && f.status === 'error' && (
                  <span className="di-up-file__err" title={f.error}> — {f.error.slice(0, 80)}</span>
                )}
              </span>
              <button
                type="button"
                className="di-up-file__remove"
                aria-label="Remove file"
                onClick={() => onRemove(f.id)}
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
