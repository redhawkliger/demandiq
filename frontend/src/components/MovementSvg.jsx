// Traffic-engineering movement glyphs.
// Each base arrow (T, L, R, U) is drawn relative to a horizontal centre `cx`.
// Composite movements (LT, ULTR, etc.) place multiple arrows in one viewBox.

const STROKE = 2.5

function ArrowT({ cx }) {
  return (
    <>
      <line
        x1={cx} y1={28} x2={cx} y2={9}
        stroke="currentColor" strokeWidth={STROKE} strokeLinecap="round"
      />
      <polygon points={`${cx - 5},10 ${cx + 5},10 ${cx},2`} fill="currentColor" />
    </>
  )
}

function ArrowL({ cx }) {
  return (
    <>
      <path
        d={`M ${cx} 28 L ${cx} 16 L ${cx - 7} 16`}
        stroke="currentColor" strokeWidth={STROKE} fill="none"
        strokeLinecap="round" strokeLinejoin="round"
      />
      <polygon points={`${cx - 6},12 ${cx - 6},20 ${cx - 13},16`} fill="currentColor" />
    </>
  )
}

function ArrowR({ cx }) {
  return (
    <>
      <path
        d={`M ${cx} 28 L ${cx} 16 L ${cx + 7} 16`}
        stroke="currentColor" strokeWidth={STROKE} fill="none"
        strokeLinecap="round" strokeLinejoin="round"
      />
      <polygon points={`${cx + 6},12 ${cx + 6},20 ${cx + 13},16`} fill="currentColor" />
    </>
  )
}

// U-turn: up the left side, arc over the top, back down the right side,
// arrowhead pointing DOWN.
function ArrowU({ cx, bottom = 28 }) {
  const left = cx - 4
  const right = cx + 4
  const arcTop = 10
  return (
    <>
      <path
        d={`M ${left} ${bottom} L ${left} ${arcTop + 4}
            Q ${left} ${arcTop} ${cx} ${arcTop}
            Q ${right} ${arcTop} ${right} ${arcTop + 4}
            L ${right} ${bottom - 2}`}
        stroke="currentColor" strokeWidth={STROKE} fill="none"
        strokeLinecap="round" strokeLinejoin="round"
      />
      <polygon
        points={`${right - 4},${bottom - 3} ${right + 4},${bottom - 3} ${right},${bottom + 4}`}
        fill="currentColor"
      />
    </>
  )
}

const ARROW = { T: ArrowT, L: ArrowL, R: ArrowR, U: ArrowU }

// One row per movement code: viewBox + ordered arrow placements.
const MOVEMENT_SPECS = {
  L:    { vb: '0 0 32 32', arrows: [['L', 16]] },
  T:    { vb: '0 0 32 32', arrows: [['T', 16]] },
  R:    { vb: '0 0 32 32', arrows: [['R', 16]] },
  U:    { vb: '0 0 32 32', arrows: [['U', 16]] },

  LT:   { vb: '0 0 40 32', arrows: [['L', 12], ['T', 28]] },
  TR:   { vb: '0 0 40 32', arrows: [['T', 12], ['R', 28]] },
  LR:   { vb: '0 0 40 32', arrows: [['L', 12], ['R', 28]] },

  LTR:  { vb: '0 0 44 32', arrows: [['L', 8], ['T', 22], ['R', 36]] },

  UL:   { vb: '0 0 40 32', arrows: [['U', 12], ['L', 28]] },
  UT:   { vb: '0 0 40 32', arrows: [['U', 12], ['T', 28]] },

  ULT:  { vb: '0 0 44 36', arrows: [['U', 8], ['L', 22], ['T', 36]] },
  ULTR: { vb: '0 0 56 36', arrows: [['U', 8], ['L', 22], ['T', 36], ['R', 50]] },
}

export const MOVEMENT_CODES = Object.keys(MOVEMENT_SPECS)

export default function MovementSvg({ code, height = 28, color }) {
  const spec = MOVEMENT_SPECS[code]
  if (!spec) return null
  const [, , w, h] = spec.vb.split(' ').map(Number)
  return (
    <svg
      viewBox={spec.vb}
      width={(w / h) * height}
      height={height}
      style={{ color: color ?? 'var(--text-primary)', display: 'block', overflow: 'visible' }}
      role="img"
      aria-label={`${code} movement`}
    >
      {spec.arrows.map(([type, cx], i) => {
        const A = ARROW[type]
        return <A key={i} cx={cx} />
      })}
    </svg>
  )
}
