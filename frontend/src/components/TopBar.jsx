export default function TopBar() {
  return (
    <header
      style={{
        height: 56,
        flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        color: 'var(--text-secondary)',
        fontSize: 13,
      }}
    >
      Untitled Project
    </header>
  )
}
