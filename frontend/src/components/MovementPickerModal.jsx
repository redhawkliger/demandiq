import { useEffect, useState } from 'react'
import MovementSvg from './MovementSvg'

const SECTIONS = [
  { title: 'Single',       codes: ['U', 'L', 'T', 'R'] },
  { title: 'Two-shared',   codes: ['UL', 'UT', 'LT', 'TR', 'LR'] },
  { title: 'Three-shared', codes: ['ULT', 'LTR'] },
  { title: 'Four-shared',  codes: ['ULTR'] },
]

export default function MovementPickerModal({
  open,
  direction,
  laneNumber,
  current,
  onCancel,
  onConfirm,
}) {
  const [selected, setSelected] = useState(current)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset selection to current each time the picker opens
    if (open) setSelected(current)
  }, [open, current])

  if (!open) return null

  const canConfirm = selected && selected !== current

  return (
    <div className="di-modal-backdrop">
      <div className="di-modal" role="dialog" aria-modal="true">
        <div className="di-modal__header">
          <h2 className="di-modal__title">{direction} — Lane {laneNumber} movement</h2>
        </div>

        <div className="di-modal__body">
          {SECTIONS.map((section) => (
            <div key={section.title} className="di-mp-section">
              <div className="di-mp-section__title">{section.title}</div>
              <div className="di-mp-grid">
                {section.codes.map((code) => {
                  const isSel = selected === code
                  return (
                    <button
                      key={code}
                      type="button"
                      aria-pressed={isSel}
                      className={`di-mp-card${isSel ? ' di-mp-card--selected' : ''}`}
                      onClick={() => setSelected(code)}
                    >
                      <MovementSvg code={code} height={30} />
                      <span className="di-mp-card__code">{code}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="di-modal__footer">
          <button type="button" className="di-btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="di-btn-primary"
            disabled={!canConfirm}
            onClick={() => onConfirm(selected)}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}
