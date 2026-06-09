// frontend/src/components/reviewMovements/DetailsModal.jsx
import { detailsModalData } from '../../lib/reviewMovements'

// Defend-the-work surface. The tolerance shown is the real IPF tol (0.01)
// from the lib payload — the component NEVER reaches for config thresholds.
// ADR 0001 pin #1 lives in the lib, not here.
export default function DetailsModal({ lastRun, intNum, period, onClose }) {
  const d = detailsModalData(lastRun, intNum, period)
  return (
    <div className="di-modal" role="dialog" aria-modal="true" aria-label="Details — show the math">
      <div className="di-modal__body">
        <button className="di-modal__close" onClick={onClose} aria-label="Close">×</button>

        <h3>Convergence</h3>
        <p>{d.converged ? 'Converged ✓' : 'Did not converge'} in {d.iterations} iterations ·
           final residual {d.finalResidual} veh
           (tolerance {d.toleranceVeh} veh · max {d.maxIterations} iter)</p>

        <h3>Source statistics</h3>
        {d.flags.length === 0 ? <p>No flags for this intersection.</p>
          : <ul>{d.flags.map((f, i) => <li key={i}><b>{f.check}</b> — {f.message}</li>)}</ul>}

        <h3>Link resolution</h3>
        <table className="di-s6-rt__table">
          <thead><tr><th>link</th><th>dir</th><th>target</th><th>reconciliation Δ</th></tr></thead>
          <tbody>
            {d.resolvedLinks.map((l, i) => (
              <tr key={i}>
                <td>{l.fromNum}→{l.toNum}</td><td>{l.direction}</td>
                <td>{l.volume}</td><td>{l.reconciliation_delta}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
