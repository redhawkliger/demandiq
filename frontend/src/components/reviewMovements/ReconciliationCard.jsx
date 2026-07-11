// frontend/src/components/reviewMovements/ReconciliationCard.jsx
import { reconciliationVerdict, statusClass } from '../../lib/reviewMovements'

// Single verdict line. Per ADR 0001: NO twin in/out totals (they are always
// equal — a check that cannot fail). The verdict is read from the solver.
export default function ReconciliationCard({ lastRun, intNum, period }) {
  const v = reconciliationVerdict(lastRun, intNum, period)
  const glyph = v.status === 'green' ? '✓' : '⚠'
  return (
    <div className="di-rm-card">
      <div className="di-rm-card__label">Flow reconciles</div>
      <div className={`di-rm-status ${statusClass(v.status)}`}>
        <span aria-hidden="true">{glyph}</span>
        <span>{v.label}</span>
      </div>
    </div>
  )
}
