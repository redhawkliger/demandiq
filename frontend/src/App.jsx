import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import TopBar from './components/TopBar'
import S1_ProjectSetup from './sessions/S1_ProjectSetup'
import S2_MapIntersection from './sessions/S2_MapIntersection'
import S3_ApproachConfig from './sessions/S3_ApproachConfig'
import S4_VolumeEntry from './sessions/S4_VolumeEntry'
import S5_BalancingSettings from './sessions/S5_BalancingSettings'
import S6_RunAnalysis from './sessions/S6_RunAnalysis'
import S7_Results from './sessions/S7_Results'
import S8_Export from './sessions/S8_Export'

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ display: 'flex', height: '100vh', background: 'var(--bg-base)' }}>
        <Sidebar />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <TopBar />
          <main style={{ flex: 1, overflow: 'auto', padding: '24px 32px' }}>
            <Routes>
              <Route path="/" element={<S1_ProjectSetup />} />
              <Route path="/map" element={<S2_MapIntersection />} />
              <Route path="/approaches" element={<S3_ApproachConfig />} />
              <Route path="/volumes" element={<S4_VolumeEntry />} />
              <Route path="/balancing" element={<S5_BalancingSettings />} />
              <Route path="/analysis" element={<S6_RunAnalysis />} />
              <Route path="/results" element={<S7_Results />} />
              <Route path="/export" element={<S8_Export />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
