import { MotionConfig } from 'framer-motion'
import { lazy, Suspense, type ReactNode } from 'react'
import { HashRouter, Route, Routes } from 'react-router-dom'
import Landing from './pages/Landing'
import { ConnectionProvider, useConnection } from './state/connection'
import { DemoDataProvider } from './state/demoContext'
import { EngineProvider } from './state/useEngine'
import { AppShell } from './ui/AppShell'
import { ConnectGate } from './ui/ConnectGate'

const Chat = lazy(() => import('./pages/Chat'))
const Memory = lazy(() => import('./pages/Memory'))
const Agents = lazy(() => import('./pages/Agents'))
const Quality = lazy(() => import('./pages/Quality'))
const Prompts = lazy(() => import('./pages/Prompts'))
const Journal = lazy(() => import('./pages/Journal'))
const Planning = lazy(() => import('./pages/Planning'))
const Export = lazy(() => import('./pages/Export'))

/** Le vrai agent si `sensai-web` répond et que le jeton est bon, sinon la démonstration (ADR-0035). */
function Engine({ children }: { children: ReactNode }) {
  const conn = useConnection()
  if (!conn || conn.mode === 'checking' || conn.mode === 'login') return <ConnectGate />
  // Une clé par moteur : une reconnexion repart d'une conversation neuve.
  return (
    <EngineProvider key={conn.engine ? `live-${conn.generation}` : 'demo'} engine={conn.engine ?? undefined}>
      {children}
    </EngineProvider>
  )
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
    <HashRouter>
      <ConnectionProvider>
        <Engine>
          <DemoDataProvider>
            <AppShell>
              <Suspense fallback={<p className="p-8 text-muted">Chargement…</p>}>
                <Routes>
                  <Route path="/" element={<Landing />} />
                  <Route path="/chat" element={<Chat />} />
                  <Route path="/memoire" element={<Memory />} />
                  <Route path="/agents" element={<Agents />} />
                  <Route path="/qualite" element={<Quality />} />
                  <Route path="/prompts" element={<Prompts />} />
                  <Route path="/journal" element={<Journal />} />
                  <Route path="/planification" element={<Planning />} />
                  <Route path="/export" element={<Export />} />
                </Routes>
              </Suspense>
            </AppShell>
          </DemoDataProvider>
        </Engine>
      </ConnectionProvider>
    </HashRouter>
    </MotionConfig>
  )
}
