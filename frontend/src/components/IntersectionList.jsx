import { Trash2, MapPin, GripVertical } from 'lucide-react'
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCenter,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  arrayMove,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

export default function IntersectionList({
  intersections,
  selectedId,
  onSelect,
  onRemove,
  onReorder,
  onContinue,
  canContinue,
  inspector,
}) {
  const sensors = useSensors(
    // Require a small drag distance so clicks on the row/remove button still fire.
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = (event) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = intersections.findIndex((it) => it.id === active.id)
    const newIndex = intersections.findIndex((it) => it.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reorderedIds = arrayMove(intersections, oldIndex, newIndex).map((it) => it.id)
    onReorder(reorderedIds)
  }

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
            <span>Click <strong>＋ Add intersection</strong>, then click the map to drop a pin</span>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={intersections.map((it) => it.id)}
              strategy={verticalListSortingStrategy}
            >
              {intersections.map((it, idx) => (
                <SortableIntersection
                  key={it.id}
                  it={it}
                  idx={idx}
                  selected={selectedId === it.id}
                  onSelect={onSelect}
                  onRemove={onRemove}
                />
              ))}
            </SortableContext>
          </DndContext>
        )}
      </div>

      {inspector}

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

function SortableIntersection({ it, idx, selected, onSelect, onRemove }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: it.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`di-int${isDragging ? ' di-int--dragging' : ''}${selected ? ' di-int--selected' : ''}`}
    >
      <button
        type="button"
        className="di-int__drag"
        aria-label={`Drag intersection ${it.num} to reorder`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} />
      </button>
      <div className="di-int__num">{it.num}</div>
      <button
        type="button"
        className="di-int__body"
        aria-pressed={selected}
        onClick={() => onSelect(it.id)}
      >
        <div className="di-int__name" title={it.name}>{it.name}</div>
        <div className="di-int__pills">
          <span className="di-int__pill">{it.control}</span>
          <span className="di-int__pill">{it.legs}</span>
          <span className="di-int__pill">{it.mainDir}</span>
          <span className="di-int__pill">{it.crossDir}</span>
        </div>
      </button>
      <div className="di-int__actions">
        <button type="button" aria-label="Remove" onClick={() => onRemove(idx)}><Trash2 size={14}/></button>
      </div>
    </div>
  )
}
