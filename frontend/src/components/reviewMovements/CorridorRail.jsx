// frontend/src/components/reviewMovements/CorridorRail.jsx
// Iterates intersections in array order (= corridor order). NEVER sorts by num
// — see memory corridor-order-invariant. Selection is by array index.
export default function CorridorRail({ intersections, selectedIndex, onSelect }) {
  return (
    <div className="di-rm-rail-strip" role="tablist" aria-label="corridor intersections">
      {intersections.map((it, i) => (
        <button
          key={it.id ?? i}
          role="tab"
          aria-selected={i === selectedIndex}
          onClick={() => onSelect(i)}
          style={{ fontWeight: i === selectedIndex ? 700 : 400 }}
        >
          {it.num}
        </button>
      ))}
    </div>
  )
}
