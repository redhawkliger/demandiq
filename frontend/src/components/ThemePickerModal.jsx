import { THEMES } from '../lib/theme'

// Appearance picker — two selectable cards (Night Traffic / Sunshine).
// Selection applies LIVE (the parent calls applyTheme on select, so the whole
// app — including the map basemap — re-themes behind the modal), then "Done"
// closes. Backdrop click also closes, keeping the current selection.
//
// Props:
//   open     — render gate
//   value    — currently applied theme id (highlights its card)
//   onSelect — (id) => void, fired on card click (parent applies + persists)
//   onClose  — () => void
export default function ThemePickerModal({ open, value, onSelect, onClose }) {
  if (!open) return null

  return (
    <div className="di-modal-backdrop" onClick={onClose}>
      <div
        className="di-modal di-modal--theme"
        role="dialog"
        aria-modal="true"
        aria-labelledby="di-theme-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="di-modal__header">
          <h2 id="di-theme-title" className="di-modal__title">Appearance</h2>
        </div>

        <div className="di-modal__body">
          <p className="di-help" style={{ marginTop: 0 }}>
            Applies across the whole app, including the map. Saved on this device.
          </p>

          <div className="di-theme-grid">
            {THEMES.map((t) => {
              const selected = value === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-pressed={selected}
                  className={`di-theme-card${selected ? ' di-theme-card--selected' : ''}`}
                  onClick={() => onSelect(t.id)}
                >
                  <span
                    className="di-theme-card__swatch"
                    aria-hidden="true"
                    style={{ background: t.swatch.bg }}
                  >
                    <span
                      className="di-theme-card__surface"
                      style={{ background: t.swatch.surface }}
                    />
                    <span
                      className="di-theme-card__accent"
                      style={{ background: t.swatch.accent }}
                    />
                  </span>
                  <span className="di-theme-card__meta">
                    <span className="di-theme-card__label">
                      {t.label}
                      {selected && <span className="di-theme-card__check" aria-hidden="true"> ✓</span>}
                    </span>
                    <span className="di-theme-card__blurb">{t.blurb}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>

        <div className="di-modal__footer">
          <button type="button" className="di-btn-primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
