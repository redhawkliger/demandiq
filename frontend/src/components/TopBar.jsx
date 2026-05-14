import { useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../store/projectStore'

export default function TopBar() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const name = snap.project?.name?.trim()
  const count = (snap.intersections || []).length
  const hasName = Boolean(name)

  let display
  if (hasName) {
    display = count > 0
      ? `${name} · ${count} intersection${count === 1 ? '' : 's'}`
      : name
  } else {
    display = 'Untitled Project'
  }

  return (
    <header
      style={{
        height: 56,
        flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        fontSize: 13,
        color: hasName ? 'var(--text-primary)' : 'var(--text-secondary)',
        fontWeight: hasName ? 500 : 400,
      }}
    >
      {display}
    </header>
  )
}
