// Live four-leg signalized intersection with a phase chip.
//
// Ported to JSX from signal-flow's SignalFlowHero.tsx (the app has no
// TypeScript toolchain); behaviour is unchanged. Needs bridge.css +
// components.css, both imported once in main.jsx.
//
// The simulation is ambient, not data: it shows a generic NEMA 2/6 main with a
// 4/8 side street, never this project's intersections. The caption says so,
// because a moving picture of traffic next to real volumes invites the
// assumption that it IS the volumes.
//
// Signal Flow's rule 6 — one loud element per page — so render at most one of
// these, and keep the rest of the screen quiet.
import { useEffect, useRef, useState } from 'react'
import './signal-flow.js'

const NAMES = { g: 'Green', y: 'Yellow', r: 'Red' }

export default function SignalFlowHero({
  mainLabel = 'Φ2/Φ6 Main St',
  sideLabel = 'Φ4/Φ8 Cross St',
  speed = 3,
  caption,
  className = '',
}) {
  const canvasRef = useRef(null)
  const [chip, setChip] = useState({
    state: 'g',
    title: `${mainLabel} · Green`,
    sub: '',
  })

  useEffect(() => {
    const canvas = canvasRef.current
    // The kit is a global side-effect module; if it failed to load, render the
    // static frame rather than throwing out of an effect.
    if (!canvas || !window.SignalFlow) return undefined

    let lastKey = ''
    const api = window.SignalFlow.intersection(canvas, {
      speed,
      onTick: (a) => {
        const m = a.main()
        const s = a.side()
        const mainHas = m.state !== 'r'
        const on = mainHas ? m : s
        const allRed = m.state === 'r' && s.state === 'r'
        const left = Math.ceil(on.left)
        // Re-render only when the displayed text would actually change —
        // onTick fires every animation frame.
        const key = `${on.state}${mainHas}${left}${allRed}`
        if (key === lastKey) return
        lastKey = key
        setChip({
          state: on.state,
          title: allRed
            ? 'All red clearance'
            : `${mainHas ? mainLabel : sideLabel} · ${NAMES[on.state]}`,
          sub: `C = ${m.cycle} s · ${left} s left · shown at ${speed}×`,
        })
      },
    })
    return () => api.destroy()
  }, [mainLabel, sideLabel, speed])

  return (
    <figure className={className} style={{ margin: 0 }}>
      <div className="sf-road">
        <canvas
          ref={canvasRef}
          aria-label="Animated four-leg signalized intersection with vehicles queuing on red and discharging on green"
        />
        <div className="sf-chip">
          <span className="sf-sig sf-sig--lg" data-s={chip.state}>
            <i /><i /><i />
          </span>
          <div>
            <span>{chip.title}</span>
            <small>{chip.sub}</small>
          </div>
        </div>
      </div>
      {caption && (
        <figcaption
          className="sf-mono"
          style={{ fontSize: 12, color: 'var(--muted)', marginTop: 8 }}
        >
          {caption}
        </figcaption>
      )}
    </figure>
  )
}
