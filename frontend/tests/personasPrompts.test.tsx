// [Workstream A - Fresnel] Personas (A5) and prompt versions (A4) with the real server:
// ADR-0054 and ADR-0055.
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
    config: { model: 'qwen', project: 'project', rag: false, rerank: false, cache: false, notices: [] },
  }),
}))

const PERSONAS: PersonaInfo[] = [
  { id: 'assistant', name: 'CodeSensai', role: 'development assistant', tone: 'neutral', scope: 'the project', toolsDisabled: [], isDefault: true },
  { id: 'reviewer', name: 'Reviewer', role: 'code reviewer', tone: 'direct', scope: 'reviews', toolsDisabled: ['write_file'], isDefault: false },
]

const PROMPTS: PromptEntry[] = [
  {
    name: 'system',
    active: 'v3',
    versions: [
      { id: 'v3', date: '2026-10-20', author: 'Fresnel', description: 'third', active: true },
      { id: 'v2', date: '2026-10-10', author: 'Ridwane', description: 'second', active: false },
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
    getPromptText: vi.fn(async (_n: string, v: string) => `Text of ${v}`),
    diffPrompts: vi.fn(async () => '--- system v2\n+++ system v3\n-old\n+new\n'),
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

test('Agents: the real personas, their disabled tools and the active persona', async () => {
  const e = fakeEngine()
  mount(e, <Agents />)
  expect(await screen.findByTestId('persona-reviewer')).toHaveTextContent('write_file')
  expect(screen.getByTestId('persona-assistant')).toHaveTextContent('Active')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Enable Reviewer' })) })
  expect(e.setPersona).toHaveBeenCalledWith('reviewer')
  expect(screen.getByTestId('persona-reviewer')).toHaveTextContent('Active')
  expect(e.switchPersona).not.toHaveBeenCalled()
})

test('Chat: the "Agent actif" selector lists the real personas and changes the conversation persona', async () => {
  const e = fakeEngine()
  // The selector is in the chat bar, shown as soon as there is a message.
  e.subscribe = vi.fn((listener: (ev: unknown) => void) => {
    queueMicrotask(() => listener({ type: 'turn_start', turnId: 't1', agent: 'assistant' }))
    return () => {}
  }) as never
  mount(e, <Chat />)
  const select = (await screen.findByLabelText('Agent actif')) as HTMLSelectElement
  await vi.waitFor(() => expect([...select.options].map((o) => o.textContent)).toEqual(['CodeSensai', 'Reviewer']))
  await act(async () => { fireEvent.change(select, { target: { value: 'reviewer' } }) })
  expect(e.setPersona).toHaveBeenCalledWith('reviewer')
  expect(select.value).toBe('reviewer')
})

test('Prompts: the real registry, the text, the diff and the trial in the conversation', async () => {
  const e = fakeEngine()
  mount(e, <Prompts />)
  expect(await screen.findByText(/third/)).toBeInTheDocument()
  expect(screen.getByText(/Ridwane/)).toBeInTheDocument()
  expect(screen.getByTestId('active-system')).toHaveTextContent('v3')
  await vi.waitFor(() => expect(screen.getByTestId('prompt-text')).toHaveTextContent('Text of v3'))
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /v2/ })) })
  await vi.waitFor(() => expect(screen.getByTestId('prompt-text')).toHaveTextContent('Text of v2'))
  await act(async () => { fireEvent.change(screen.getByLabelText('Compare with'), { target: { value: 'v3' } }) })
  expect(e.diffPrompts).toHaveBeenCalledWith('system', 'v3', 'v2')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Try in this conversation' })) })
  expect(e.setPromptTrial).toHaveBeenCalledWith('v2')
  expect(screen.getByText(/Trial run/)).toHaveTextContent('v2')
  // No "Mettre en service": the web UI never modifies the registry.
  expect(screen.queryByRole('button', { name: 'Activate' })).not.toBeInTheDocument()
})

test('Chat: a badge flags the prompt trial and allows going back to the active one', async () => {
  const e = fakeEngine()
  e.getPromptTrial = vi.fn(async () => ({ active: 'v3', trial: 'v2' }))
  e.subscribe = vi.fn((listener: (ev: unknown) => void) => {
    queueMicrotask(() => listener({ type: 'turn_start', turnId: 't1', agent: 'assistant' }))
    return () => {}
  }) as never
  mount(e, <Chat />)
  expect(await screen.findByTestId('prompt-trial-badge')).toHaveTextContent('system prompt v2 (trial run)')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Back to the active prompt version' })) })
  expect(e.setPromptTrial).toHaveBeenCalledWith(null)
  expect(screen.queryByTestId('prompt-trial-badge')).not.toBeInTheDocument()
})

test('HttpEngine: personas and prompts go through the conversation routes', async () => {
  const calls: { method: string; path: string; body: unknown }[] = []
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
  const fetchFn = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace('http://api.test', '')
    calls.push({ method: init?.method ?? 'GET', path, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (path === '/api/personas')
      return json([{ id: 'assistant', name: 'CodeSensai', role: 'r', tone: 't', scope: 's', tools_disabled: [], default: true }])
    if (path === '/api/sessions') return json({ session_id: 'S1' }, 201)
    if (path === '/api/sessions/S1/persona')
      return json({ id: 'reviewer', name: 'Reviewer', role: 'r', tone: 't', scope: 's', tools_disabled: ['write_file'], default: false })
    if (path === '/api/sessions/S1/prompt-trial') return json({ prompt: 'system', active: 'v3', trial: 'v2' })
    if (path === '/api/prompts/system/diff?a=v2&b=v3') return json({ diff: '-a\n+b' })
    return json({ error: 'unknown' }, 404)
  })
  const engine = new HttpEngine({ baseUrl: 'http://api.test', token: 't', fetchFn: fetchFn as unknown as typeof fetch })
  // No conversation: the default persona, without creating a session.
  expect((await engine.getPersona())?.id).toBe('assistant')
  expect(calls.some((c) => c.path === '/api/sessions')).toBe(false)
  const p = await engine.setPersona('reviewer')
  expect(p?.toolsDisabled).toEqual(['write_file'])
  expect(calls.at(-1)).toEqual({ method: 'POST', path: '/api/sessions/S1/persona', body: { persona: 'reviewer' } })
  expect((await engine.setPromptTrial('v2'))?.trial).toBe('v2')
  expect(calls.at(-1)).toEqual({ method: 'POST', path: '/api/sessions/S1/prompt-trial', body: { version: 'v2' } })
  expect(await engine.diffPrompts('system', 'v2', 'v3')).toBe('-a\n+b')
})
