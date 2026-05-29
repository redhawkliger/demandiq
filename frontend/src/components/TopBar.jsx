import { useState, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot, clearProject } from '../store/projectStore'
// Pulled in so the confirm modal + buttons are styled even on routes (e.g. S1)
// whose own modules don't import these sheets.
import '../styles/forms.css'
import '../styles/map.css'

export default function TopBar() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const [confirmOpen, setConfirmOpen] = useState(false)

  const name = snap.project?.name?.trim()
  const count = (snap.intersections || []).length
  const hasName = Boolean(name)

  let display
  if (hasName) {
    display = count > 0
      ? `${name} · ${count} intersection${count === 1 ? '' : 's'}`
      : name
  } else {
    display = 'Untitled Project'
  }

  // Globally-reachable reset: clear persisted + in-memory project state, then
  // hard-reload to S1 so every session's component-local state resets cleanly.
  // Reachable from S1–S8 because TopBar renders outside <Routes> in App.jsx.
  const handleNewProject = () => {
    clearProject()
    window.location.assign('/')
  }

  return (
    <header
      style={{
        height: 56,
        flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '0 24px',
        fontSize: 13,
      }}
    >
      <span
        style={{
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          color: hasName ? 'var(--text-primary)' : 'var(--text-secondary)',
          fontWeight: hasName ? 500 : 400,
        }}
      >
        {display}
      </span>

      <button
        type="button"
        className="di-btn-secondary"
        style={{ height: 32, padding: '0 14px', fontSize: 13, flexShrink: 0 }}
        onClick={() => setConfirmOpen(true)}
      >
        New project
      </button>

      {confirmOpen && (
        <div className="di-modal-backdrop">
          <div className="di-modal" role="dialog" aria-modal="true">
            <div className="di-modal__header">
              <h2 className="di-modal__title">Start a new project?</h2>
            </div>
            <div className="di-modal__body">
              <p style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.55 }}>
                Discard the current project and start fresh? This cannot be undone.
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
                onClick={handleNewProject}
              >
                Discard &amp; start fresh
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  )
}
