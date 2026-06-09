// frontend/src/components/reviewMovements/ProvenanceHeader.jsx
import { methodLabel } from '../../lib/reviewMovements'

export default function ProvenanceHeader({
  lastRun, intersection, position, total, period,
  onPrev, onNext, onPeriod, onOpenDetails,
}) {
  const m = methodLabel(lastRun)
  return (
    <div className="di-rm-prov">
      <button onClick={onPrev} aria-label="Previous intersection">◀</button>
      <span>Int {position} / {total} · {intersection?.name}</span>
      <button onClick={onNext} aria-label="Next intersection">▶</button>

      <div className="di-segmented" role="group" aria-label="peak period">
        <button aria-pressed={period === 'AM'} onClick={() => onPeriod('AM')}>AM</button>
        <button aria-pressed={period === 'PM'} onClick={() => onPeriod('PM')}>PM</button>
      </div>

      {/* Method meaning is VISIBLE surface text — not hover-gated (locked design). */}
      <span className="di-rm-prov__method">
        Resolution: <b>{m.label}</b> — {m.meaning}
      </span>

      <button className="di-btn-ghost" onClick={onOpenDetails} style={{ marginLeft: 'auto' }}>
        ▦ Details — show the math
      </button>
    </div>
  )
}
