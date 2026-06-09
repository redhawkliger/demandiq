// frontend/src/components/reviewMovements/IntersectionDiagram.jsx
import { useEffect, useState } from 'react'
import { buildPayload } from '../../lib/diagramPayload'

// Same fetch shape as S7_Results.jsx:45 — POST /api/intersection-diagram → { png: base64 }.
async function fetchDiagram(payload) {
  const res = await fetch('/api/intersection-diagram', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); if (j?.detail) detail = j.detail } catch { /* keep status */ }
    throw new Error(detail)
  }
  return await res.json()
}

export default function IntersectionDiagram({ intersection, period }) {
  // 'balanced' is the default (the deliverable). 'delta' is the Changes lens.
  const [mode, setMode] = useState('balanced')
  const [png, setPng] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let live = true
    if (!intersection) return
    setErr(null); setPng(null)
    fetchDiagram(buildPayload(intersection, period, mode))
      .then(d => { if (live) setPng(d.png) })
      .catch(e => { if (live) setErr(e.message) })
    return () => { live = false }
  }, [intersection, period, mode])

  return (
    <div className="di-rm__anchor">
      <div className="di-segmented" role="group" aria-label="diagram view mode">
        <button aria-pressed={mode === 'balanced'} onClick={() => setMode('balanced')}>Balanced</button>
        <button aria-pressed={mode === 'delta'} onClick={() => setMode('delta')}>Changes</button>
      </div>
      {err && <div className="di-banner">{err}</div>}
      {png && (
        <img
          src={`data:image/png;base64,${png}`}
          alt={`Intersection ${intersection?.num} line diagram (${mode})`}
          draggable={false}
          style={{ width: '100%', display: 'block' }}
        />
      )}
    </div>
  )
}
