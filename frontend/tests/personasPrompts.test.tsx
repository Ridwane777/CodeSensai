// [Lot A — Fresnel] Personas (A5) et versions de prompts (A4) avec le serveur réel :
// ADR-0054 et ADR-0055.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { Engine, PersonaInfo, PromptEntry, PromptTrial } from '../src/contract/engine'
import { HttpEngine } from '../src/engine/httpEngine'
import Agents from '../src/pages/Agents'
import Chat from '../src/pages/Chat'
import Prompts from '../src/pages/Prompts'
import { DemoDataProvider } from '../src/state/demoContext'
import { EngineProvider } from '../src/state/useEngine'

vi.mock('../src/state/connection', () => ({
  useConnection: () => ({
    mode: 'live',
    config: { model: 'qwen', project: 'projet', rag: false, rerank: false, cache: false, notices: [] },
  }),
}))

const PERSONAS: PersonaInfo[] = [
  { id: 'assistant', name: 'Sensai', role: 'assistant de développement', tone: 'neutre', scope: 'le projet', toolsDisabled: [], isDefault: true },
  { id: 'relecteur', name: 'Relecteur', role: 'relecteur de code', tone: 'direct', scope: 'la relecture', toolsDisabled: ['write_file'], isDefault: false },
]

const PROMPTS: PromptEntry[] = [
  {
    name: 'system',
    active: 'v3',
    versions: [
      { id: 'v3', date: '2026-10-20', author: 'Fresnel', description: 'troisième', active: true },
      { id: 'v2', date: '2026-10-10', author: 'Ridwane', description: 'deuxième', active: false },
    ],
  },
]

function fakeEngine() {
  let persona = 'assistant'
  let trial: string | null = null
  return {
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
    listPersonas: vi.fn(async () => PERSONAS),
    getPersona: vi.fn(async () => PERSONAS.find((p) => p.id === persona)!),
    setPersona: vi.fn(async (id: string) => {
      persona = id
      return PERSONAS.find((p) => p.id === id)!
    }),
    listPrompts: vi.fn(async () => PROMPTS),
    getPromptText: vi.fn(async (_n: string, v: string) => `Texte de ${v}`),
    diffPrompts: vi.fn(async () => '--- system v2\n+++ system v3\n-ancien\n+nouveau\n'),
    getPromptTrial: vi.fn(async (): Promise<PromptTrial> => ({ active: 'v3', trial })),
    setPromptTrial: vi.fn(async (v: string | null): Promise<PromptTrial> => {
      trial = v
      return { active: 'v3', trial }
    }),
  }
}

function mount(e: ReturnType<typeof fakeEngine>, page: JSX.Element) {
  return render(
    <MemoryRouter>
      <EngineProvider engine={e as unknown as Engine}>
        <DemoDataProvider>{page}</DemoDataProvider>
      </EngineProvider>
    </MemoryRouter>,
  )
}

test('Agents : les vraies personas, leurs outils désactivés et la persona active', async () => {
  const e = fakeEngine()
  mount(e, <Agents />)
  expect(await screen.findByTestId('persona-relecteur')).toHaveTextContent('write_file')
  expect(screen.getByTestId('persona-assistant')).toHaveTextContent('Actif')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Activer Relecteur' })) })
  expect(e.setPersona).toHaveBeenCalledWith('relecteur')
  expect(screen.getByTestId('persona-relecteur')).toHaveTextContent('Actif')
  expect(e.switchPersona).not.toHaveBeenCalled()
})

test('Chat : le sélecteur « Agent actif » liste les vraies personas et change celle de la conversation', async () => {
  const e = fakeEngine()
  // Le sélecteur est dans la barre du chat, affichée dès qu'il y a un message.
  e.subscribe = vi.fn((listener: (ev: unknown) => void) => {
    queueMicrotask(() => listener({ type: 'turn_start', turnId: 't1', agent: 'assistant' }))
    return () => {}
  }) as never
  mount(e, <Chat />)
  const select = (await screen.findByLabelText('Agent actif')) as HTMLSelectElement
  await vi.waitFor(() => expect([...select.options].map((o) => o.textContent)).toEqual(['Sensai', 'Relecteur']))
  await act(async () => { fireEvent.change(select, { target: { value: 'relecteur' } }) })
  expect(e.setPersona).toHaveBeenCalledWith('relecteur')
  expect(select.value).toBe('relecteur')
})

test('Prompts : le vrai registre, le texte, le diff et l’essai dans la conversation', async () => {
  const e = fakeEngine()
  mount(e, <Prompts />)
  expect(await screen.findByText(/troisième/)).toBeInTheDocument()
  expect(screen.getByText(/Ridwane/)).toBeInTheDocument()
  expect(screen.getByTestId('active-system')).toHaveTextContent('v3')
  await vi.waitFor(() => expect(screen.getByTestId('prompt-text')).toHaveTextContent('Texte de v3'))
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /v2/ })) })
  await vi.waitFor(() => expect(screen.getByTestId('prompt-text')).toHaveTextContent('Texte de v2'))
  await act(async () => { fireEvent.change(screen.getByLabelText('Comparer avec'), { target: { value: 'v3' } }) })
  expect(e.diffPrompts).toHaveBeenCalledWith('system', 'v3', 'v2')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Essayer dans cette conversation' })) })
  expect(e.setPromptTrial).toHaveBeenCalledWith('v2')
  expect(screen.getByText(/Essai en cours/)).toHaveTextContent('v2')
  // Pas de « Mettre en service » : le web ne modifie jamais le registre.
  expect(screen.queryByRole('button', { name: 'Mettre en service' })).not.toBeInTheDocument()
})

test('Chat : un badge signale l’essai de prompt et permet de revenir à l’active', async () => {
  const e = fakeEngine()
  e.getPromptTrial = vi.fn(async () => ({ active: 'v3', trial: 'v2' }))
  e.subscribe = vi.fn((listener: (ev: unknown) => void) => {
    queueMicrotask(() => listener({ type: 'turn_start', turnId: 't1', agent: 'assistant' }))
    return () => {}
  }) as never
  mount(e, <Chat />)
  expect(await screen.findByTestId('prompt-trial-badge')).toHaveTextContent('prompt system v2 (essai)')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Revenir à la version active du prompt' })) })
  expect(e.setPromptTrial).toHaveBeenCalledWith(null)
  expect(screen.queryByTestId('prompt-trial-badge')).not.toBeInTheDocument()
})

test('HttpEngine : personas et prompts passent par les routes de la conversation', async () => {
  const calls: { method: string; path: string; body: unknown }[] = []
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
  const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace('http://api.test', '')
    calls.push({ method: init?.method ?? 'GET', path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (path === '/api/personas')
      return json([{ id: 'assistant', name: 'Sensai', role: 'r', tone: 't', scope: 's', tools_disabled: [], default: true }])
    if (path === '/api/sessions') return json({ session_id: 'S1' }, 201)
    if (path === '/api/sessions/S1/persona')
      return json({ id: 'relecteur', name: 'Relecteur', role: 'r', tone: 't', scope: 's', tools_disabled: ['write_file'], default: false })
    if (path === '/api/sessions/S1/prompt-trial') return json({ prompt: 'system', active: 'v3', trial: 'v2' })
    if (path === '/api/prompts/system/diff?a=v2&b=v3') return json({ diff: '-a\n+b' })
    return json({ error: 'inconnu' }, 404)
  })
  const engine = new HttpEngine({ baseUrl: 'http://api.test', token: 't', fetchFn: fetchFn as unknown as typeof fetch })
  // Sans conversation : la persona par défaut, sans créer de session.
  expect((await engine.getPersona())?.id).toBe('assistant')
  expect(calls.some((c) => c.path === '/api/sessions')).toBe(false)
  const p = await engine.setPersona('relecteur')
  expect(p?.toolsDisabled).toEqual(['write_file'])
  expect(calls.at(-1)).toEqual({ method: 'POST', path: '/api/sessions/S1/persona', body: { persona: 'relecteur' } })
  expect((await engine.setPromptTrial('v2'))?.trial).toBe('v2')
  expect(calls.at(-1)).toEqual({ method: 'POST', path: '/api/sessions/S1/prompt-trial', body: { version: 'v2' } })
  expect(await engine.diffPrompts('system', 'v2', 'v3')).toBe('-a\n+b')
})
