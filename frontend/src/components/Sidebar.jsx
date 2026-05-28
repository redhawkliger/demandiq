import { NavLink } from 'react-router-dom'
import { LifeBuoy } from 'lucide-react'
import { exportDiagnostics } from '../lib/diagnostics'

const STEPS = [
  { num: 1, label: 'Project Setup',      path: '/' },
  { num: 2, label: 'Map / Intersection', path: '/map' },
  { num: 3, label: 'Approach Config',    path: '/approaches' },
  { num: 4, label: 'Volume Entry',       path: '/volumes' },
  { num: 5, label: 'Balancing Settings', path: '/balancing' },
  { num: 6, label: 'Run Analysis',       path: '/analysis' },
  { num: 7, label: 'Results',            path: '/results' },
  { num: 8, label: 'Export',             path: '/export' },
]

export default function Sidebar() {
  return (
    <aside
      style={{
        width: 240,
        flexShrink: 0,
        background: 'var(--bg-elevated)',
        borderRight: '1px solid var(--border)',
        padding: '24px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 18,
          fontWeight: 600,
          color: 'var(--text-primary)',
          padding: '0 12px 28px',
          letterSpacing: '-0.01em',
        }}
      >
        DemandIQ
      </div>
      {STEPS.map(({ num, label, path }) => (
        <NavLink
          key={num}
          to={path}
          end={path === '/'}
          style={({ isActive }) => ({
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: 13,
            color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
            background: isActive ? 'var(--accent-glow)' : 'transparent',
            borderLeft: isActive
              ? '2px solid var(--accent)'
              : '2px solid transparent',
          })}
        >
          <span
            style={{
              color: 'var(--text-tertiary)',
              fontSize: 11,
              fontVariantNumeric: 'tabular-nums',
              width: 18,
            }}
          >
            {String(num).padStart(2, '0')}
          </span>
          <span>{label}</span>
        </NavLink>
      ))}

      {/* App-level actions — pinned to the bottom */}
      <button
        type="button"
        onClick={() => exportDiagnostics()}
        title="Download a JSON snapshot of project state for debugging (no credentials)"
        style={{
          marginTop: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 12px',
          borderRadius: 6,
          border: '1px solid var(--border)',
          background: 'transparent',
          color: 'var(--text-secondary)',
          fontSize: 12,
          cursor: 'pointer',
          fontFamily: 'inherit',
        }}
      >
        <LifeBuoy size={14} />
        <span>Export diagnostics</span>
      </button>
    </aside>
  )
}
