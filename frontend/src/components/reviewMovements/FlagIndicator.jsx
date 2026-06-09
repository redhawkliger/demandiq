// frontend/src/components/reviewMovements/FlagIndicator.jsx
import { detailsModalData } from '../../lib/reviewMovements'

// Light per-intersection flag badge; links back to the S6 verdict/queue screen
// where flags are actioned. Reuses the same flag filter as the modal.
export default function FlagIndicator({ lastRun, intNum, period, onGoToVerdict }) {
  const { flags } = detailsModalData(lastRun, intNum, period)
  if (flags.length === 0) return null
  return (
    <button className="di-btn-ghost" onClick={onGoToVerdict}>
      ⚠ {flags.length} flag{flags.length > 1 ? 's' : ''} — review →
    </button>
  )
}
