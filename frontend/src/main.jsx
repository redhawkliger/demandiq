import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// themes.css must load BEFORE index.css so :root[data-theme] gates win.
import './styles/themes.css'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
