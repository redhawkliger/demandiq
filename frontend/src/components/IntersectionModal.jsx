import { useEffect, useState } from 'react'
import { Target } from 'lucide-react'

const CONTROL_TYPES = [
  { key: 'Signalized',    label: '🚦 Signalized' },
  { key: 'Two-way stop',  label: '🛑 Two-way stop' },
  { key: 'All-way stop',  label: '🛑 All-way stop' },
  {
    key: 'Roundabout',
    label: (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <Target size={14} /> Roundabout
      </span>
    ),
  },
]
const LEGS = ['3-leg', '4-leg']
const DIRS = ['EB/WB', 'NB/SB', 'NE/SW', 'NW/SE']
const PERPENDICULAR = {
  'EB/WB': 'NB/SB', 'NB/SB': 'EB/WB',
  'NE/SW': 'NW/SE', 'NW/SE': 'NE/SW',
}

export default function IntersectionModal({
  open,
  mode,
  num,
  initial,
  geocodeName,
  geocodeFailed,
  skewDeg,
  onCancel,
  onConfirm,
}) {
  const [name, setName]         = useState('')
  const [control, setControl]   = useState('Signalized')
  const [legs, setLegs]         = useState('4-leg')
  const [mainDir, setMainDir]   = useState('EB/WB')
  const [crossDir, setCrossDir] = useState('NB/SB')
  const [userTouchedName, setUserTouchedName] = useState(false)

  // Reset whenever a new modal opens
  useEffect(() => {
    if (!open) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset all fields each time the modal (re)opens
    setName(initial?.name ?? '')
    setControl(initial?.control ?? 'Signalized')
    setLegs(initial?.legs ?? '4-leg')
    setMainDir(initial?.mainDir ?? 'EB/WB')
    setCrossDir(initial?.crossDir ?? 'NB/SB')
    setUserTouchedName(Boolean(initial?.name))
  }, [open, initial])

  // Pre-fill name from reverse geocode only if user hasn't typed
  useEffect(() => {
    if (!open || mode !== 'add' || userTouchedName) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot reverse-geocode name prefill until the user types
    if (geocodeName && !name) setName(geocodeName)
  }, [geocodeName, open, mode, userTouchedName, name])

  const onMainDirChange = (d) => {
    setMainDir(d)
    setCrossDir(PERPENDICULAR[d] ?? d)
  }

  const parts = name.split('&').map((s) => s.trim())
  const mainStreetLabel  = parts[0] || 'Main street'
  const crossStreetLabel = parts[1] || 'Cross street'

  const canConfirm = name.trim().length > 0 && Boolean(mainDir) && Boolean(crossDir)

  const handleConfirm = () => {
    if (!canConfirm) return
    onConfirm({
      name: name.trim(),
      control,
      legs,
      mainStreet: parts[0] || '',
      crossStreet: parts[1] || '',
      mainDir,
      crossDir,
    })
  }

  if (!open) return null

  return (
    <div className="di-modal-backdrop">
      <div className="di-modal" role="dialog" aria-modal="true" aria-labelledby="di-modal-title">
        <div className="di-modal__header">
          <h2 id="di-modal-title" className="di-modal__title">Intersection {num}</h2>
        </div>

        <div className="di-modal__body">
          {geocodeFailed && !geocodeName && (
            <div className="di-banner">Auto-name unavailable — enter manually</div>
          )}
          {skewDeg != null && skewDeg > 20 && (
            <div className="di-banner di-banner--warn">
              ⚠ This intersection appears skewed (~{Math.round(skewDeg)}° off cardinal).
              Confirm directions carefully.
            </div>
          )}

          <div className="di-field">
            <label className="di-label" htmlFor="m-name">Name</label>
            <input
              id="m-name"
              className="di-input"
              type="text"
              value={name}
              placeholder="e.g. Main St & 1st Ave"
              autoFocus
              autoComplete="off"
              onChange={(e) => { setName(e.target.value); setUserTouchedName(true) }}
            />
            <div className="di-help">
              Use <span className="di-mono">&amp;</span> to separate streets — e.g. Main St &amp; 1st Ave
            </div>
          </div>

          <div className="di-field">
            <label className="di-label">Control type</label>
            <div className="di-pill-grid">
              {CONTROL_TYPES.map((t) => {
                const selected = control === t.key
                return (
                  <button
                    key={t.key}
                    type="button"
                    aria-pressed={selected}
                    className={`di-pill${selected ? ' di-pill--selected' : ''}`}
                    onClick={() => setControl(t.key)}
                  >
                    {t.label}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="di-field">
            <label className="di-label">Legs</label>
            <div className="di-pill-group">
              {LEGS.map((l) => {
                const selected = legs === l
                return (
                  <button
                    key={l}
                    type="button"
                    aria-pressed={selected}
                    className={`di-pill${selected ? ' di-pill--selected' : ''}`}
                    onClick={() => setLegs(l)}
                  >
                    {l}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="di-row">
            <div className="di-field">
              <label className="di-label">{mainStreetLabel}</label>
              <select
                className="di-select"
                value={mainDir}
                onChange={(e) => onMainDirChange(e.target.value)}
              >
                {DIRS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div className="di-field">
              <label className="di-label">{crossStreetLabel}</label>
              <select
                className="di-select"
                value={crossDir}
                onChange={(e) => setCrossDir(e.target.value)}
              >
                {DIRS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div className="di-modal__footer">
          <button type="button" className="di-btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="di-btn-primary"
            disabled={!canConfirm}
            onClick={handleConfirm}
          >
            Confirm pin ✓
          </button>
        </div>
      </div>
    </div>
  )
}
