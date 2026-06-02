import { useSyncExternalStore } from 'react'
import { NavLink } from 'react-router-dom'
import { LifeBuoy } from 'lucide-react'
import { exportDiagnostics } from '../lib/diagnostics'
import { subscribe, getSnapshot, isExistingAnalysisDone } from '../store/projectStore'

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

// Forecasting phase (Method 1 / NCHRP 765). `built` flips on as each F-screen
// lands; until then the row is a disabled placeholder. The whole group is gated
// on the existing analysis having produced balanced TMCs.
const FORECAST_STEPS = [
  { key: 'F1', label: 'Horizon & Network', path: '/forecast/setup',   built: true },
  { key: 'F2', label: 'Network Match',     path: '/forecast/match',   built: true },
  { key: 'F3', label: 'Run Forecast',      path: '/forecast/run',     built: true },
  { key: 'F4', label: 'Future Results',    path: '/forecast/results', built: true },
]

const itemBase = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  padding: '8px 12px',
  borderRadius: 6,
  fontSize: 13,
}

function Badge({ children, color }) {
  return (
    <span style={{ color, fontSize: 11, fontVariantNumeric: 'tabular-nums', width: 18 }}>
      {children}
    </span>
  )
}

export default function Sidebar() {
  useSyncExternalStore(subscribe, getSnapshot, () => ({}))
  const gateOpen = isExistingAnalysisDone()

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
            ...itemBase,
            color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
            background: isActive ? 'var(--accent-glow)' : 'transparent',
            borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
          })}
        >
          <Badge color="var(--text-tertiary)">{String(num).padStart(2, '0')}</Badge>
          <span>{label}</span>
        </NavLink>
      ))}

      {/* ── Forecasting (Method 1 / NCHRP 765) — amber-anchored, gated ──────── */}
      <div
        style={{
          margin: '18px 12px 6px',
          paddingTop: 14,
          borderTop: '1px solid var(--border)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: gateOpen ? 'var(--signal-amber)' : 'var(--text-tertiary)',
        }}
      >
        Forecasting
      </div>

      {FORECAST_STEPS.map(({ key, label, path, built }) => {
        const enabled = built && gateOpen
        if (enabled) {
          return (
            <NavLink
              key={key}
              to={path}
              style={({ isActive }) => ({
                ...itemBase,
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                background: isActive ? 'var(--signal-amber-glow)' : 'transparent',
                borderLeft: isActive
                  ? '2px solid var(--signal-amber)'
                  : '2px solid transparent',
              })}
            >
              <Badge color="var(--signal-amber)">{key}</Badge>
              <span>{label}</span>
            </NavLink>
          )
        }
        const title = !gateOpen
          ? 'Balance the existing volumes first (Run Analysis → Results)'
          : 'Available after the earlier forecasting steps'
        return (
          <div
            key={key}
            title={title}
            style={{
              ...itemBase,
              color: 'var(--text-tertiary)',
              opacity: 0.45,
              cursor: 'default',
              borderLeft: '2px solid transparent',
            }}
          >
            <Badge color="var(--text-tertiary)">{key}</Badge>
            <span>{label}</span>
          </div>
        )
      })}

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
