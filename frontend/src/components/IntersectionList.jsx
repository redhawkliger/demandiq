import { Pencil, Trash2, MapPin } from 'lucide-react'

export default function IntersectionList({
  intersections,
  onEdit,
  onRemove,
  onContinue,
  canContinue,
}) {
  return (
    <aside className="di-side">
      <div className="di-side__header">
        <span className="di-side__title">Intersections</span>
        <span className="di-side__count">{intersections.length}</span>
      </div>

      <div className="di-side__list">
        {intersections.length === 0 ? (
          <div className="di-side__empty">
            <MapPin size={20} />
            <span>Click the map to add your first intersection</span>
          </div>
        ) : (
          intersections.map((it, idx) => (
            <div key={it.id} className="di-int">
              <div className="di-int__num">{it.num}</div>
              <div className="di-int__body">
                <div className="di-int__name" title={it.name}>{it.name}</div>
                <div className="di-int__pills">
                  <span className="di-int__pill">{it.control}</span>
                  <span className="di-int__pill">{it.legs}</span>
                  <span className="di-int__pill">{it.mainDir}</span>
                  <span className="di-int__pill">{it.crossDir}</span>
                </div>
              </div>
              <div className="di-int__actions">
                <button type="button" aria-label="Edit"   onClick={() => onEdit(idx)}><Pencil size={14}/></button>
                <button type="button" aria-label="Remove" onClick={() => onRemove(idx)}><Trash2 size={14}/></button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="di-side__footer">
        {!canContinue && (
          <div className="di-side__hint">Confirm at least 2 intersections</div>
        )}
        <button
          type="button"
          className="di-btn-primary di-btn-primary--block"
          disabled={!canContinue}
          onClick={onContinue}
        >
          Continue →
        </button>
      </div>
    </aside>
  )
}
