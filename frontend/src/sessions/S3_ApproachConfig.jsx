import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, ChevronLeft, ChevronRight } from 'lucide-react'

import {
  subscribe,
  getSnapshot,
  setApproaches,
  isIntersectionConfigured,
} from '../store/projectStore'
import MovementSvg from '../components/MovementSvg'
import MovementPickerModal from '../components/MovementPickerModal'

import '../styles/forms.css'
import '../styles/map.css'    // reuses .di-modal, .di-banner, .di-btn-secondary
import '../styles/approach.css'

const ALL_DIRS = ['EB', 'WB', 'NB', 'SB']

const defaultApproach = () => ({ exists: true, lanes: [{ movement: 'T' }] })

const defaultApproaches = () => ({
  EB: defaultApproach(),
  WB: defaultApproach(),
  NB: defaultApproach(),
  SB: defaultApproach(),
})

// Major / cross grouping per the project-wide corridor direction (set in S2).
function groupedDirs(corridorDir) {
  if (corridorDir === 'NS') {
    return { major: ['NB', 'SB'], cross: ['EB', 'WB'], majorAxis: 'NB/SB', crossAxis: 'EB/WB' }
  }
  return   { major: ['EB', 'WB'], cross: ['NB', 'SB'], majorAxis: 'EB/WB', crossAxis: 'NB/SB' }
}

export default function S3_ApproachConfig() {
  const navigate = useNavigate()
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const intersections = snap.intersections || []
  const corridorDir = snap.analysis?.corridorDir ?? 'EW'

  // ── Empty-state redirect to S2 ──────────────────────────────────────
  useEffect(() => {
    if (intersections.length > 0) return
    const t = setTimeout(() => navigate('/map'), 1000)
    return () => clearTimeout(t)
  }, [intersections.length, navigate])

  // ── Default-fill approaches once on mount ───────────────────────────
  const didInit = useRef(false)
  useEffect(() => {
    if (didInit.current || intersections.length === 0) return
    didInit.current = true
    intersections.forEach((it) => {
      if (!it.approaches) setApproaches(it.id, defaultApproaches())
    })
  }, [intersections])

  // ── Active intersection (state-only nav) ────────────────────────────
  const [activeId, setActiveId] = useState(intersections[0]?.id ?? null)
  useEffect(() => {
    // If active id was removed, snap to the first
    if (!intersections.find((it) => it.id === activeId)) {
      setActiveId(intersections[0]?.id ?? null)
    }
  }, [intersections, activeId])

  // ── Movement picker state ───────────────────────────────────────────
  // { intersectionId, dir, laneIndex, current }
  const [picker, setPicker] = useState(null)

  if (intersections.length === 0) {
    return (
      <div className="di-s3 di-s3--center">
        <div className="di-s3-empty">
          <div className="di-banner">Add intersections first.</div>
          <p className="di-s3-empty__sub">Redirecting to the map…</p>
        </div>
      </div>
    )
  }

  const active = intersections.find((it) => it.id === activeId) ?? intersections[0]
  const activeIdx = intersections.findIndex((it) => it.id === active.id)
  const isFirst = activeIdx === 0
  const isLast = activeIdx === intersections.length - 1
  const allConfigured = intersections.every((it) => isIntersectionConfigured(it.id))
  const unconfigured = intersections.filter((it) => !isIntersectionConfigured(it.id)).map((it) => it.num)
  const groups = groupedDirs(corridorDir)

  // The active intersection might still be missing approaches on the very first
  // render (the default-fill effect runs *after* the first commit).
  const approaches = active.approaches ?? defaultApproaches()

  const updateApproach = (dir, next) => {
    const merged = { ...approaches, [dir]: next }
    setApproaches(active.id, merged)
  }

  const incLanes = (dir) => {
    const ap = approaches[dir]
    updateApproach(dir, { ...ap, lanes: [...ap.lanes, { movement: 'T' }] })
  }
  const decLanes = (dir) => {
    const ap = approaches[dir]
    if (ap.lanes.length <= 1) return
    updateApproach(dir, { ...ap, lanes: ap.lanes.slice(0, -1) })
  }
  const toggleDne = (dir) => {
    const ap = approaches[dir]
    if (ap.exists === false) {
      // Restore: re-add a single default lane
      updateApproach(dir, { exists: true, lanes: [{ movement: 'T' }] })
    } else {
      updateApproach(dir, { exists: false, lanes: [] })
    }
  }

  const openPicker = (dir, laneIndex) => {
    setPicker({
      intersectionId: active.id,
      dir,
      laneIndex,
      current: approaches[dir].lanes[laneIndex].movement,
    })
  }

  const handlePickerConfirm = (movement) => {
    if (!picker) return
    const ap = approaches[picker.dir]
    const nextLanes = ap.lanes.map((lane, i) =>
      i === picker.laneIndex ? { ...lane, movement } : lane
    )
    updateApproach(picker.dir, { ...ap, lanes: nextLanes })
    setPicker(null)
  }

  const goPrev = () => !isFirst && setActiveId(intersections[activeIdx - 1].id)
  const goNext = () => !isLast && setActiveId(intersections[activeIdx + 1].id)
  const goVolumes = () => navigate('/volumes')

  return (
    <div className="di-s3">
      <div className="di-s3__body">
        {/* ── Nav ─────────────────────────────────────────────────── */}
        <aside className="di-s3__nav">
          <div className="di-s3-nav__title">Intersections</div>
          {intersections.map((it) => {
            const done = isIntersectionConfigured(it.id)
            const isActive = it.id === active.id
            return (
              <button
                key={it.id}
                type="button"
                className={`di-s3-nav__item${isActive ? ' di-s3-nav__item--active' : ''}`}
                onClick={() => setActiveId(it.id)}
              >
                <span className="di-s3-nav__num">
                  {String(it.num).padStart(2, '0')}
                </span>
                <span className="di-s3-nav__name" title={it.name}>{it.name}</span>
                {done && <Check size={14} className="di-s3-nav__check" />}
              </button>
            )
          })}
        </aside>

        {/* ── Main editor ─────────────────────────────────────────── */}
        <div className="di-s3__main">
          <div className="di-ap-header">
            <div className="di-ap-header__num">{active.num}</div>
            <div className="di-ap-header__name">{active.name}</div>
            <span className="di-ap-header__badge">{active.control}</span>
            <span className="di-ap-header__badge">{active.legs}</span>
          </div>

          <Section
            title={`Major street (${groups.majorAxis})`}
            dirs={groups.major}
            approaches={approaches}
            onInc={incLanes}
            onDec={decLanes}
            onDne={toggleDne}
            onLaneClick={openPicker}
          />
          <Section
            title={`Cross street (${groups.crossAxis})`}
            dirs={groups.cross}
            approaches={approaches}
            onInc={incLanes}
            onDec={decLanes}
            onDne={toggleDne}
            onLaneClick={openPicker}
          />
        </div>
      </div>

      {/* ── Sticky footer ─────────────────────────────────────────── */}
      <footer className="di-s3__footer">
        <button
          type="button"
          className="di-btn-secondary"
          disabled={isFirst}
          onClick={goPrev}
        >
          <ChevronLeft size={16} style={{ verticalAlign: '-3px' }} /> Previous
        </button>

        <span className="di-s3__footer-pos">
          Intersection {activeIdx + 1} of {intersections.length}
        </span>

        {/* Page-advance is ALWAYS available (gated on all intersections being
            configured) — not hidden behind reaching the last one. "Next" is a
            secondary stepper for moving between intersections. */}
        <div className="di-s3__footer-adv">
          {!allConfigured && (
            <span className="di-s3__footer-hint">
              Configure intersection{unconfigured.length === 1 ? '' : 's'} {unconfigured.join(', ')} to continue
            </span>
          )}
          {!isLast && (
            <button type="button" className="di-btn-secondary" onClick={goNext}>
              Next <ChevronRight size={16} style={{ verticalAlign: '-3px' }} />
            </button>
          )}
          <button
            type="button"
            className="di-btn-primary"
            disabled={!allConfigured}
            onClick={goVolumes}
            title={allConfigured ? 'Go to volume entry' : 'Configure all intersections first'}
          >
            Continue to volume entry →
          </button>
        </div>
      </footer>

      <MovementPickerModal
        open={picker !== null}
        direction={picker?.dir}
        laneNumber={picker ? picker.laneIndex + 1 : 0}
        current={picker?.current}
        onCancel={() => setPicker(null)}
        onConfirm={handlePickerConfirm}
      />
    </div>
  )
}

// ── Section: Major or Cross ─────────────────────────────────────────────
function Section({ title, dirs, approaches, onInc, onDec, onDne, onLaneClick }) {
  return (
    <section className="di-ap-section">
      <div className="di-ap-section__title">{title}</div>
      {dirs.map((dir) => (
        <ApproachCard
          key={dir}
          dir={dir}
          ap={approaches[dir]}
          onInc={() => onInc(dir)}
          onDec={() => onDec(dir)}
          onDne={() => onDne(dir)}
          onLaneClick={(idx) => onLaneClick(dir, idx)}
        />
      ))}
    </section>
  )
}

// ── One approach card (header + lanes + pills, or DNE state) ───────────
function ApproachCard({ dir, ap, onInc, onDec, onDne, onLaneClick }) {
  const dne = ap.exists === false
  return (
    <div className={`di-ap-card${dne ? ' di-ap-card--dne' : ''}`}>
      <div className="di-ap-card__head">
        <div className="di-ap-card__dir">{dir}</div>

        {!dne && (
          <div className="di-ap-card__stepper">
            <button
              type="button"
              aria-label="Remove last lane"
              onClick={onDec}
              disabled={ap.lanes.length <= 1}
            >
              −
            </button>
            <span className="di-ap-card__stepper-count">{ap.lanes.length}</span>
            <button type="button" aria-label="Add lane" onClick={onInc}>+</button>
          </div>
        )}

        <div className="di-ap-card__spacer" />

        <button type="button" className="di-ap-card__dne-toggle" onClick={onDne}>
          {dne ? 'Restore approach' : 'Does not exist'}
        </button>
      </div>

      {dne ? (
        <div className="di-ap-card__dne-body">Does not exist</div>
      ) : (
        <>
          <div className="di-ap-card__lanes">
            {ap.lanes.map((lane, i) => (
              <button
                key={i}
                type="button"
                className="di-ap-card__lane"
                onClick={() => onLaneClick(i)}
                aria-label={`${dir} lane ${i + 1}: ${lane.movement}`}
              >
                <MovementSvg code={lane.movement} height={32} />
                <span className="di-ap-card__lane-code">{lane.movement}</span>
              </button>
            ))}
          </div>
          <div className="di-ap-card__pills">
            <span className="di-ap-pill di-ap-pill--blue">{ap.lanes.length} Lanes</span>
            <span className="di-ap-pill di-ap-pill--amber">
              {ap.lanes.map((l) => l.movement).join(', ')}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
