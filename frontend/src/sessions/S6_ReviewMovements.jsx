// frontend/src/sessions/S6_ReviewMovements.jsx
import { useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { subscribe, getSnapshot } from '../store/projectStore'
import { stepIndex } from '../lib/reviewMovements'

import ProvenanceHeader from '../components/reviewMovements/ProvenanceHeader'
import IntersectionDiagram from '../components/reviewMovements/IntersectionDiagram'
import ChangelogCard from '../components/reviewMovements/ChangelogCard'
import ReconciliationCard from '../components/reviewMovements/ReconciliationCard'
import CorridorRail from '../components/reviewMovements/CorridorRail'
import FlagIndicator from '../components/reviewMovements/FlagIndicator'
import DetailsModal from '../components/reviewMovements/DetailsModal'

import '../styles/forms.css'
import '../styles/balancing.css' // .di-segmented
import '../styles/map.css'       // .di-modal, .di-banner, .di-btn-ghost
import '../styles/reviewMovements.css'

export default function S6_ReviewMovements() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const navigate = useNavigate()
  const lastRun = snap.analysis?.lastRun ?? null
  const intersections = snap.intersections || [] // GIVEN order = corridor order

  const [selectedIndex, setSelectedIndex] = useState(0)
  const [period, setPeriod] = useState('AM')
  const [showDetails, setShowDetails] = useState(false)

  if (!lastRun) return <div className="di-rm"><p style={{ padding: 20 }}>No analysis run yet.</p></div>
  if (intersections.length === 0) return <div className="di-rm"><p style={{ padding: 20 }}>No corridor.</p></div>

  const idx = Math.min(selectedIndex, intersections.length - 1)
  const intersection = intersections[idx]
  const intNum = intersection.num

  return (
    <div className="di-rm">
      <ProvenanceHeader
        lastRun={lastRun}
        intersection={intersection}
        position={idx + 1}
        total={intersections.length}
        period={period}
        onPrev={() => setSelectedIndex(stepIndex(intersections.length, idx, -1))}
        onNext={() => setSelectedIndex(stepIndex(intersections.length, idx, +1))}
        onPeriod={setPeriod}
        onOpenDetails={() => setShowDetails(true)}
      />

      <div className="di-rm__body">
        <IntersectionDiagram intersection={intersection} period={period} />
        <div className="di-rm__rail">
          <ChangelogCard lastRun={lastRun} intNum={intNum} period={period} />
          <ReconciliationCard lastRun={lastRun} intNum={intNum} period={period} />
          <FlagIndicator lastRun={lastRun} intNum={intNum} period={period}
                         onGoToVerdict={() => navigate('/analysis')} />
        </div>
      </div>

      <CorridorRail intersections={intersections} selectedIndex={idx} onSelect={setSelectedIndex} />

      {showDetails && (
        <DetailsModal lastRun={lastRun} intNum={intNum} period={period}
                      onClose={() => setShowDetails(false)} />
      )}
    </div>
  )
}
