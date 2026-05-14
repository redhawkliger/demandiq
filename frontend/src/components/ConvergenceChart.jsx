// Tiny inline SVG line chart for convergence visualization.
// No chart library — fixed viewBox, scales to container width via width="100%".
//
// Props:
//   amLog, pmLog: [{iteration, max_relative_gap}, ...]  (full logs from /balance)
//   amIter, pmIter: how many entries to render so far (drives the animation)
//   threshold:   convergence threshold, decimal (e.g. 0.01 = 1%)

const W = 600
const H = 240
const PADL = 44
const PADR = 20
const PADT = 16
const PADB = 30
const PLOTW = W - PADL - PADR
const PLOTH = H - PADT - PADB

const fmtPct = (v) => `${(v * 100).toFixed(1)}%`

export default function ConvergenceChart({ amLog, pmLog, amIter, pmIter, threshold }) {
  const visAm = amLog.slice(0, amIter)
  const visPm = pmLog.slice(0, pmIter)

  const allShown = [...visAm, ...visPm].map((e) => e.max_relative_gap)
  const dataMax = allShown.length ? Math.max(...allShown) : threshold
  const yMax = Math.max(dataMax * 1.1, threshold * 1.5)
  const xMax = Math.max(amLog.length, pmLog.length, 1)

  const x = (iter) =>
    PADL + (xMax === 1 ? PLOTW / 2 : ((iter - 1) / (xMax - 1)) * PLOTW)
  const y = (g) => PADT + PLOTH - (g / yMax) * PLOTH

  const polyPoints = (entries) =>
    entries.map((e) => `${x(e.iteration)},${y(e.max_relative_gap)}`).join(' ')

  const yThresh = y(threshold)
  const lastAm = visAm[visAm.length - 1]
  const lastPm = visPm[visPm.length - 1]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="di-s6-chart" preserveAspectRatio="xMidYMid meet">
      {/* Axes */}
      <line x1={PADL} x2={PADL}        y1={PADT} y2={PADT + PLOTH} stroke="var(--border)" />
      <line x1={PADL} x2={PADL + PLOTW} y1={PADT + PLOTH} y2={PADT + PLOTH} stroke="var(--border)" />

      {/* Y tick labels */}
      <text x={PADL - 6} y={PADT + PLOTH + 4} textAnchor="end" className="di-s6-chart__lbl">0%</text>
      <text x={PADL - 6} y={yThresh + 4}      textAnchor="end" className="di-s6-chart__lbl">{fmtPct(threshold)}</text>
      <text x={PADL - 6} y={PADT + 4}         textAnchor="end" className="di-s6-chart__lbl">{fmtPct(yMax)}</text>

      {/* X tick labels */}
      <text x={x(1)} y={PADT + PLOTH + 18} textAnchor="middle" className="di-s6-chart__lbl">1</text>
      {xMax > 2 && (
        <text x={x(Math.ceil(xMax / 2))} y={PADT + PLOTH + 18} textAnchor="middle" className="di-s6-chart__lbl">
          {Math.ceil(xMax / 2)}
        </text>
      )}
      {xMax > 1 && (
        <text x={x(xMax)} y={PADT + PLOTH + 18} textAnchor="middle" className="di-s6-chart__lbl">{xMax}</text>
      )}

      {/* Threshold dashed green line */}
      <line
        x1={PADL} x2={PADL + PLOTW}
        y1={yThresh} y2={yThresh}
        stroke="#34D399" strokeDasharray="4 4" strokeWidth="1"
      />
      <text x={PADL + PLOTW - 4} y={yThresh - 6} textAnchor="end" className="di-s6-chart__thresh-lbl">
        threshold
      </text>

      {/* AM (amber) */}
      {visAm.length > 1 && (
        <polyline points={polyPoints(visAm)} fill="none" stroke="#FFB627" strokeWidth="2" strokeLinejoin="round" />
      )}
      {lastAm && (
        <circle cx={x(lastAm.iteration)} cy={y(lastAm.max_relative_gap)} r="3.5" fill="#FFB627" />
      )}

      {/* PM (blue) */}
      {visPm.length > 1 && (
        <polyline points={polyPoints(visPm)} fill="none" stroke="#0A84FF" strokeWidth="2" strokeLinejoin="round" />
      )}
      {lastPm && (
        <circle cx={x(lastPm.iteration)} cy={y(lastPm.max_relative_gap)} r="3.5" fill="#0A84FF" />
      )}

      {/* Axis labels */}
      <text x={PADL + PLOTW / 2} y={H - 4} textAnchor="middle" className="di-s6-chart__axis-lbl">
        Iteration
      </text>
    </svg>
  )
}
