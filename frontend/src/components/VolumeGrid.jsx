import { setCellValue, setPhf, setHvPct } from '../store/projectStore'

const DIRS = ['EB', 'WB', 'NB', 'SB']
const MVTS = ['U', 'L', 'T', 'R']

const DIR_ARROWS = { EB: 'EB →', WB: '← WB', NB: 'NB ↑', SB: 'SB ↓' }

// Compute which of {U, L, T, R} are active for an approach, based on its lanes.
export function activeMovements(approach) {
  const out = { U: false, L: false, T: false, R: false }
  if (!approach || approach.exists === false) return out
  for (const lane of approach.lanes || []) {
    for (const ch of lane.movement || '') if (ch in out) out[ch] = true
  }
  return out
}

// Cell renderer: dot if inactive, otherwise number input with source colouring.
function Cell({ active, cell, onChange }) {
  if (!active) return <td className="di-vol-td di-vol-td--dot">·</td>

  const source = cell?._source
  const value = cell?.value
  const cls =
    source === 'agent'  ? 'di-vol-td--agent'  :
    source === 'manual' ? 'di-vol-td--manual' : ''

  return (
    <td className={`di-vol-td di-vol-td--cell ${cls}`}>
      {source === 'agent' && <span className="di-vol-badge">AI</span>}
      <input
        type="number"
        min="0"
        className="di-vol-input"
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          const v = raw === '' ? null : Number(raw)
          onChange(v)
        }}
      />
    </td>
  )
}

function ScalarCell({ value, step, onChange }) {
  return (
    <td className="di-vol-td di-vol-td--cell">
      <input
        type="number"
        step={step}
        min="0"
        className="di-vol-input"
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          onChange(raw === '' ? null : Number(raw))
        }}
      />
    </td>
  )
}

export default function VolumeGrid({ intersections }) {
  return (
    <div className="di-vol-wrap">
      <table className="di-vol-grid">
        <thead>
          <tr>
            <th rowSpan={2} className="di-vol-th di-vol-th--meta">Intersection</th>
            <th rowSpan={2} className="di-vol-th di-vol-th--period">Per</th>
            {DIRS.map((d) => (
              <th key={d} colSpan={4} className="di-vol-th di-vol-th--dir">
                {DIR_ARROWS[d]}
              </th>
            ))}
            <th rowSpan={2} className="di-vol-th di-vol-th--scalar">PHF</th>
            <th rowSpan={2} className="di-vol-th di-vol-th--scalar">HV%</th>
          </tr>
          <tr>
            {DIRS.flatMap((d) =>
              MVTS.map((m) => (
                <th key={`${d}${m}`} className="di-vol-th di-vol-th--sub">{m}</th>
              ))
            )}
          </tr>
        </thead>
        <tbody>
          {intersections.map((it) => {
            const approachActive = {
              EB: activeMovements(it.approaches?.EB),
              WB: activeMovements(it.approaches?.WB),
              NB: activeMovements(it.approaches?.NB),
              SB: activeMovements(it.approaches?.SB),
            }
            const renderRow = (period) => (
              <tr key={`${it.id}-${period}`}>
                {period === 'AM' && (
                  <td rowSpan={2} className="di-vol-td di-vol-td--meta">
                    <div className="di-vol-meta__num">{it.num}</div>
                    <div className="di-vol-meta__name" title={it.name}>{it.name}</div>
                    <div className="di-vol-meta__sub">
                      <span>{it.control}</span>
                      {it.vendorDetected && (
                        <span className="di-vol-meta__vendor" title={it.sourceFile || ''}>
                          {it.vendorDetected}
                        </span>
                      )}
                    </div>
                  </td>
                )}
                <td className="di-vol-td di-vol-td--period">{period}</td>
                {DIRS.flatMap((d) =>
                  MVTS.map((m) => {
                    const code = `${d}${m}`
                    const cell = it.volumes?.[period]?.[code]
                    return (
                      <Cell
                        key={code}
                        active={approachActive[d][m]}
                        cell={cell}
                        onChange={(v) => setCellValue(it.id, period, code, v, 'manual')}
                      />
                    )
                  })
                )}
                <ScalarCell
                  value={it.phf?.[period]}
                  step="0.001"
                  onChange={(v) => setPhf(it.id, period, v)}
                />
                <ScalarCell
                  value={it.hvPct?.[period]}
                  step="0.1"
                  onChange={(v) => setHvPct(it.id, period, v)}
                />
              </tr>
            )
            return [renderRow('AM'), renderRow('PM')]
          })}
        </tbody>
      </table>
    </div>
  )
}
