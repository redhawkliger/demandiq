// frontend/src/components/reviewMovements/ChangelogCard.jsx
import { useState } from 'react'
import { changelog, deltaClass } from '../../lib/reviewMovements'
import MovementSvg from '../MovementSvg'

function Row({ m }) {
  const sign = m.delta > 0 ? '+' : ''
  const arrow = m.delta > 0 ? '▲' : '▼'
  return (
    <div className="di-rm-change">
      <MovementSvg code={m.movement} height={20} color="var(--delta-up)" />
      <span>{m.movement}&nbsp;&nbsp;{m.raw} → {m.balanced}</span>
      <span className={`di-rm-delta ${deltaClass(m.delta)}`}>{sign}{m.delta} {arrow}</span>
    </div>
  )
}

export default function ChangelogCard({ lastRun, intNum, period }) {
  const [showUnchanged, setShowUnchanged] = useState(false)
  const cl = changelog(lastRun, intNum, period)
  return (
    <div className="di-rm-card">
      <div className="di-rm-card__label">What changed · {cl.headline}</div>
      {cl.changed.map((m, i) => <Row key={i} m={m} />)}
      {cl.unchanged.length > 0 && (
        <>
          <button className="di-rm-unchanged-toggle" onClick={() => setShowUnchanged(s => !s)}>
            {showUnchanged ? '▾' : '▸'} {cl.unchanged.length} unchanged
          </button>
          {showUnchanged && cl.unchanged.map((m, i) => (
            <div className="di-rm-change" key={`u${i}`}>
              <MovementSvg code={m.movement} height={20} color="var(--text-tertiary)" />
              <span>{m.movement}&nbsp;&nbsp;{m.raw} → {m.balanced}</span>
              <span className="di-rm-delta">0</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
