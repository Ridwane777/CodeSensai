/**
 * Engine choice at startup (ADR-0035).
 *
 * - A `sensai-web` server answers on the same origin: we ask for the token it printed at
 *   startup, check it, then the interface talks to the real agent (`HttpEngine`).
 * - No server: the interface stays in demo mode (`MockEngine`, ADR-0020), and says so.
 *
 * The token is kept in `sessionStorage` (this tab only), never in the URL (ADR-0023).
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
  /** The server answered at startup: we can offer to connect. */
  serverFound: boolean
  /** Changes on each successful connection: the interface restarts with a fresh engine. */
  generation: number
  login(token: string): Promise<string | null>
  logout(): void
  chooseDemo(): void
  /** Authenticated read of an API route (memory pages…); null when not connected. */
  getJson<T>(path: string): Promise<T | null>
}

const TOKEN_KEY = 'sensai.token'
/** Delay between two server lookups in demo mode. */
const RETRY_MS = 3000
/** Beyond this, we stop looking (a demo left open does not poll the network forever);
 *  reloading the page restarts the lookup. */
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
      if (!clean) return 'Paste the token printed when sensai-web starts.'
      let res: Response
      try {
        res = await withTimeout(fetchFn, `${baseUrl}/api/config`, { headers: { Authorization: `Bearer ${clean}` } }, 5000)
      } catch {
        return 'Server unreachable.'
      }
      if (res.status === 401) return 'Token rejected: check the token printed by sensai-web (it changes on every start).'
      if (!res.ok) return `Unexpected server response (${res.status}).`
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

  // Demo because there is no server: we check again from time to time, so that starting sensai-web
  // after the interface is enough (no page reload). An explicit choice of the demo is not overridden.
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

/** null outside `ConnectionProvider` (component tests, standalone demo). */
export function useConnection(): Connection | null {
  return useContext(ConnectionContext)
}
