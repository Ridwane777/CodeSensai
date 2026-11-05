/**
 * Choix du moteur au démarrage (ADR-0035).
 *
 * - Un serveur `sensai-web` répond sur la même origine : on demande le jeton affiché à son
 *   démarrage, on le vérifie, puis l'interface parle au vrai agent (`HttpEngine`).
 * - Aucun serveur : l'interface reste en démonstration (`MockEngine`, ADR-0020), et le dit.
 *
 * Le jeton est gardé dans `sessionStorage` (l'onglet seulement), jamais dans l'URL (ADR-0023).
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Engine } from '../contract/engine'
import { HttpEngine } from '../engine/httpEngine'

export interface ServerConfig {
  model: string
  project: string
  rag: boolean
  rerank: boolean
  cache: boolean
  notices: string[]
}

export type Mode = 'checking' | 'login' | 'live' | 'demo'

interface Connection {
  mode: Mode
  config: ServerConfig | null
  engine: Engine | null
  /** Le serveur a répondu au démarrage : on peut proposer de se connecter. */
  serverFound: boolean
  /** Change à chaque connexion réussie : l'interface repart d'un moteur neuf. */
  generation: number
  login(token: string): Promise<string | null>
  logout(): void
  chooseDemo(): void
  /** Lecture authentifiée d'une route de l'API (pages mémoire…) ; null hors connexion. */
  getJson<T>(path: string): Promise<T | null>
}

const TOKEN_KEY = 'sensai.token'
/** Délai entre deux recherches du serveur en mode démonstration. */
const RETRY_MS = 3000
/** Au-delà, on arrête de chercher (une démo laissée ouverte n'interroge pas le réseau sans fin) ;
 *  recharger la page relance la recherche. */
const RETRY_FOR_MS = 5 * 60 * 1000
const ConnectionContext = createContext<Connection | null>(null)

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

async function withTimeout(fetchFn: typeof fetch, url: string, init: RequestInit, ms: number) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  try {
    return await fetchFn(url, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

const defaultFetch: typeof fetch = (...args) => fetch(...args)

export function ConnectionProvider({
  children,
  fetchFn = defaultFetch,
  baseUrl = '',
}: {
  children: ReactNode
  fetchFn?: typeof fetch
  baseUrl?: string
}) {
  const [mode, setMode] = useState<Mode>('checking')
  const [config, setConfig] = useState<ServerConfig | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [serverFound, setServerFound] = useState(false)
  const [generation, setGeneration] = useState(0)

  const logout = useCallback(() => {
    storage()?.removeItem(TOKEN_KEY)
    setToken(null)
    setConfig(null)
    setMode('login')
  }, [])

  const login = useCallback(
    async (candidate: string): Promise<string | null> => {
      const clean = candidate.trim()
      if (!clean) return 'Collez le jeton affiché au démarrage de sensai-web.'
      let res: Response
      try {
        res = await withTimeout(fetchFn, `${baseUrl}/api/config`, { headers: { Authorization: `Bearer ${clean}` } }, 5000)
      } catch {
        return 'Serveur injoignable.'
      }
      if (res.status === 401) return 'Jeton refusé : vérifiez le jeton affiché par sensai-web (il change à chaque démarrage).'
      if (!res.ok) return `Réponse inattendue du serveur (${res.status}).`
      setConfig((await res.json()) as ServerConfig)
      storage()?.setItem(TOKEN_KEY, clean)
      setToken(clean)
      setGeneration((g) => g + 1)
      setMode('live')
      return null
    },
    [fetchFn, baseUrl],
  )

  const healthy = useCallback(async () => {
    try {
      const res = await withTimeout(fetchFn, `${baseUrl}/api/health`, {}, 2000)
      return res.ok && ((await res.json()) as { status?: string }).status === 'ok'
    } catch {
      return false
    }
  }, [fetchFn, baseUrl])

  const connect = useCallback(async (isCancelled: () => boolean) => {
    const saved = storage()?.getItem(TOKEN_KEY)
    if (saved && (await login(saved)) === null) return
    if (!isCancelled()) setMode('login')
  }, [login])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const found = await healthy()
      if (cancelled) return
      setServerFound(found)
      if (!found) {
        setMode('demo')
        return
      }
      await connect(() => cancelled)
    })()
    return () => {
      cancelled = true
    }
  }, [healthy, connect])

  // Démonstration faute de serveur : on revérifie de temps en temps, pour que lancer sensai-web
  // après l'interface suffise (sans recharger la page). Un choix explicite de la démo n'est pas repris.
  useEffect(() => {
    if (mode !== 'demo' || serverFound) return
    let cancelled = false
    const startedAt = Date.now()
    const id = setInterval(() => {
      if (Date.now() - startedAt > RETRY_FOR_MS) {
        clearInterval(id)
        return
      }
      void healthy().then(async (found) => {
        if (cancelled || !found) return
        clearInterval(id)
        setServerFound(true)
        await connect(() => cancelled)
      })
    }, RETRY_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [mode, serverFound, healthy, connect])

  const engine = useMemo(
    () => (mode === 'live' && token ? new HttpEngine({ token, baseUrl, fetchFn, onUnauthorized: logout }) : null),
    [mode, token, baseUrl, fetchFn, logout],
  )

  const getJson = useCallback(
    async <T,>(path: string): Promise<T | null> => {
      if (mode !== 'live' || !token) return null
      try {
        const res = await fetchFn(`${baseUrl}${path}`, { headers: { Authorization: `Bearer ${token}` } })
        if (res.status === 401) {
          logout()
          return null
        }
        return res.ok ? ((await res.json()) as T) : null
      } catch {
        return null
      }
    },
    [mode, token, baseUrl, fetchFn, logout],
  )

  const value: Connection = {
    mode,
    config,
    engine,
    serverFound,
    generation,
    login,
    logout,
    chooseDemo: () => setMode('demo'),
    getJson,
  }
  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>
}

/** null hors de `ConnectionProvider` (tests de composants, démo autonome). */
export function useConnection(): Connection | null {
  return useContext(ConnectionContext)
}
