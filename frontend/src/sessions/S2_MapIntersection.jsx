import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import 'leaflet/dist/leaflet.css'
import '../styles/forms.css'
import '../styles/map.css'

import MapView from '../components/MapView'
import IntersectionModal from '../components/IntersectionModal'
import IntersectionList from '../components/IntersectionList'
import {
  getIntersections,
  setIntersections as persistIntersections,
  reorderIntersections,
  setCorridorDir,
} from '../store/projectStore'
import { reverseGeocode } from '../lib/photon'
import {
  bearing,
  deviationFromCardinal,
  detectCorridorDir,
  sortAlongCorridor,
} from '../lib/geo'

const PERPENDICULAR = {
  'EB/WB': 'NB/SB', 'NB/SB': 'EB/WB',
  'NE/SW': 'NW/SE', 'NW/SE': 'NE/SW',
}

const newId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

export default function S2_MapIntersection() {
  const navigate = useNavigate()
  const [intersections, setIntersections] = useState(() => getIntersections())

  // Modal state shape:
  //   null when closed, otherwise:
  //   { mode: 'add' | 'edit', num, initial, pendingPin?, geocodeName?,
  //     geocodeFailed, skewDeg?, editIndex? }
  const [modal, setModal] = useState(null)

  // Persist on every change after the initial mount
  const skipFirstSaveRef = useRef(true)
  useEffect(() => {
    if (skipFirstSaveRef.current) {
      skipFirstSaveRef.current = false
      return
    }
    persistIntersections(intersections)
  }, [intersections])

  const openAdd = (latlng) => {
    const num = intersections.length + 1
    let skewDeg = null
    if (intersections.length > 0) {
      const last = intersections[intersections.length - 1]
      const b = bearing(
        { lat: last.lat, lng: last.lng },
        { lat: latlng.lat, lng: latlng.lng }
      )
      skewDeg = deviationFromCardinal(b)
    }
    setModal({
      mode: 'add',
      num,
      initial: {
        name: '',
        control: 'Signalized',
        legs: '4-leg',
        mainDir: 'EB/WB',
        crossDir: PERPENDICULAR['EB/WB'],
      },
      pendingPin: { lat: latlng.lat, lng: latlng.lng },
      geocodeName: null,
      geocodeFailed: false,
      skewDeg,
      editIndex: null,
    })

    // Reverse geocode in background; only apply if this same pin is still open.
    reverseGeocode(latlng.lat, latlng.lng)
      .then((name) => {
        setModal((prev) => {
          if (
            !prev ||
            !prev.pendingPin ||
            prev.pendingPin.lat !== latlng.lat ||
            prev.pendingPin.lng !== latlng.lng
          ) return prev
          return { ...prev, geocodeName: name || null, geocodeFailed: !name }
        })
      })
      .catch(() => {
        setModal((prev) => {
          if (
            !prev ||
            !prev.pendingPin ||
            prev.pendingPin.lat !== latlng.lat ||
            prev.pendingPin.lng !== latlng.lng
          ) return prev
          return { ...prev, geocodeFailed: true }
        })
      })
  }

  const openEdit = (idx) => {
    const it = intersections[idx]
    setModal({
      mode: 'edit',
      num: it.num,
      initial: {
        name: it.name,
        control: it.control,
        legs: it.legs,
        mainDir: it.mainDir,
        crossDir: it.crossDir,
      },
      pendingPin: null,
      geocodeName: null,
      geocodeFailed: false,
      skewDeg: null,
      editIndex: idx,
    })
  }

  const handleConfirm = (form) => {
    if (modal.mode === 'add') {
      setIntersections([
        ...intersections,
        {
          id: newId(),
          num: modal.num,
          lat: modal.pendingPin.lat,
          lng: modal.pendingPin.lng,
          ...form,
        },
      ])
    } else {
      const next = [...intersections]
      next[modal.editIndex] = { ...next[modal.editIndex], ...form }
      setIntersections(next)
    }
    setModal(null)
  }

  const handleCancel = () => setModal(null)

  const handleRemove = (idx) => {
    const next = intersections
      .filter((_, i) => i !== idx)
      .map((it, i) => ({ ...it, num: i + 1 }))
    setIntersections(next)
  }

  // Atomic: build the reordered list with renumbered `num` in a single setState,
  // mirroring the store-side reorderIntersections (which the persist effect calls).
  const handleReorder = (orderedIds) => {
    const byId = new Map(intersections.map((it) => [it.id, it]))
    const next = orderedIds
      .map((id, i) => {
        const it = byId.get(id)
        return it ? { ...it, num: i + 1 } : null
      })
      .filter(Boolean)
    if (next.length !== intersections.length) return
    setIntersections(next)
    // Belt-and-braces store-side reorder so the new order is canonical even if
    // a parallel render swallowed the effect (e.g. unmount mid-drag).
    reorderIntersections(orderedIds)
  }

  const handleContinue = () => {
    const dir = detectCorridorDir(intersections)
    const sorted = sortAlongCorridor(intersections, dir).map((it, i) => ({
      ...it,
      num: i + 1,
    }))
    setIntersections(sorted)
    setCorridorDir(dir)
    navigate('/approaches')
  }

  return (
    <div className="di-s2">
      <div className="di-s2__map">
        <MapView
          intersections={intersections}
          pendingPin={modal?.pendingPin ?? null}
          onMapClick={openAdd}
        />
      </div>

      <IntersectionList
        intersections={intersections}
        onEdit={openEdit}
        onRemove={handleRemove}
        onReorder={handleReorder}
        onContinue={handleContinue}
        canContinue={intersections.length >= 2}
      />

      <IntersectionModal
        open={modal !== null}
        mode={modal?.mode}
        num={modal?.num}
        initial={modal?.initial}
        geocodeName={modal?.geocodeName}
        geocodeFailed={modal?.geocodeFailed ?? false}
        skewDeg={modal?.skewDeg}
        onCancel={handleCancel}
        onConfirm={handleConfirm}
      />
    </div>
  )
}
