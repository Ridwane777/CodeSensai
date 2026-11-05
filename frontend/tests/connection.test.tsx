import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConnectionProvider, useConnection } from '../src/state/connection'
import { ConnectGate } from '../src/ui/ConnectGate'
import { SimBadge } from '../src/ui/SimBadge'

const CONFIG = { model: 'qwen3-coder:30b', project: 'projet', rag: true, rerank: true, cache: true, notices: [] }

function server({ up = true, token = 'BON' } = {}) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (!up) throw new Error('injoignable')
    if (url.endsWith('/api/health')) return new Response(JSON.stringify({ status: 'ok' }))
    const auth = new Headers(init?.headers).get('Authorization')
    if (auth !== `Bearer ${token}`) return new Response('{}', { status: 401 })
    return new Response(JSON.stringify(CONFIG))
  }) as unknown as typeof fetch
}

function Probe() {
  const c = useConnection()
  if (!c || c.mode === 'checking' || c.mode === 'login') return <ConnectGate />
  return (
    <p>
      mode {c.mode} <SimBadge />
    </p>
  )
}

beforeEach(() => sessionStorage.clear())

test('sans serveur, la démonstration démarre seule', async () => {
  render(<ConnectionProvider fetchFn={server({ up: false })}><Probe /></ConnectionProvider>)
  expect(await screen.findByText(/mode demo/)).toBeInTheDocument()
  expect(screen.getByText(/moteur simulé/i)).toBeInTheDocument()
})

test('avec un serveur, le jeton est demandé puis vérifié', async () => {
  render(<ConnectionProvider fetchFn={server()}><Probe /></ConnectionProvider>)
  const input = await screen.findByLabelText(/jeton/i)
  await userEvent.type(input, 'FAUX')
  await userEvent.click(screen.getByRole('button', { name: /se connecter/i }))
  expect(await screen.findByRole('alert')).toHaveTextContent(/jeton refusé/i)
  await userEvent.clear(input)
  await userEvent.type(input, 'BON')
  await userEvent.click(screen.getByRole('button', { name: /se connecter/i }))
  expect(await screen.findByText(/mode live/)).toBeInTheDocument()
  expect(screen.getByText(/agent réel · qwen3-coder:30b/i)).toBeInTheDocument()
  expect(sessionStorage.getItem('sensai.token')).toBe('BON')
})

test("le jeton gardé dans l'onglet reconnecte sans redemander", async () => {
  sessionStorage.setItem('sensai.token', 'BON')
  render(<ConnectionProvider fetchFn={server()}><Probe /></ConnectionProvider>)
  expect(await screen.findByText(/mode live/)).toBeInTheDocument()
})

test('un jeton gardé mais périmé redemande le jeton', async () => {
  sessionStorage.setItem('sensai.token', 'VIEUX')
  render(<ConnectionProvider fetchFn={server()}><Probe /></ConnectionProvider>)
  expect(await screen.findByLabelText(/jeton/i)).toBeInTheDocument()
})

test('on peut choisir la démonstration même avec un serveur', async () => {
  render(<ConnectionProvider fetchFn={server()}><Probe /></ConnectionProvider>)
  await userEvent.click(await screen.findByRole('button', { name: /démonstration/i }))
  expect(await screen.findByText(/mode demo/)).toBeInTheDocument()
})

test("sensai-web lancé après l'interface : la démonstration le retrouve et demande le jeton", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  let up = false
  const fetchFn = vi.fn(async (url: string, init?: RequestInit) => server({ up })(url, init)) as unknown as typeof fetch
  render(<ConnectionProvider fetchFn={fetchFn}><Probe /></ConnectionProvider>)
  expect(await screen.findByText(/mode demo/)).toBeInTheDocument()
  up = true
  await vi.advanceTimersByTimeAsync(3100)
  expect(await screen.findByLabelText(/jeton/i)).toBeInTheDocument()
  vi.useRealTimers()
})

test('sans serveur, la démonstration arrête de le chercher au bout de 5 minutes', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const fetchFn = vi.fn(async (url: string, init?: RequestInit) => server({ up: false })(url, init)) as unknown as typeof fetch
  render(<ConnectionProvider fetchFn={fetchFn}><Probe /></ConnectionProvider>)
  expect(await screen.findByText(/mode demo/)).toBeInTheDocument()
  await vi.advanceTimersByTimeAsync(5 * 60 * 1000 + 4000)
  const calls = (fetchFn as unknown as { mock: { calls: unknown[] } }).mock.calls.length
  await vi.advanceTimersByTimeAsync(60 * 1000)
  expect((fetchFn as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBe(calls)
  vi.useRealTimers()
})
