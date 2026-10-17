import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// themes.css must load BEFORE index.css so :root[data-theme] gates win.
import './styles/themes.css'
import './index.css'
// Signal Flow: bridge aliases its token names onto DemandIQ's, so it must come
// after themes.css (which defines the targets) and before the components that
// read them.
import './lib/signal-flow/bridge.css'
import './lib/signal-flow/components.css'
import App from './App.jsx'
import { initTheme } from './lib/theme.js'

// Apply the saved appearance preference before first paint so Sunshine users
// don't flash the dark default. themes.css's bare :root keeps night-traffic as
// the no-attribute fallback if nothing is stored.
initTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
