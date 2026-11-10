import { act, fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach } from 'vitest'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'
import Agents from '../src/pages/Agents'
import Journal from '../src/pages/Journal'
import Memory from '../src/pages/Memory'
import Planning from '../src/pages/Planning'
import Prompts from '../src/pages/Prompts'
import Quality from '../src/pages/Quality'
import { demoReducer, initialDemo } from '../src/state/demoData'
import { DemoDataProvider } from '../src/state/demoContext'
import { EngineProvider, useEngine } from '../src/state/useEngine'

function wrap(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <EngineProvider engine={new MockEngine({ route })}>
        <DemoDataProvider>{ui}</DemoDataProvider>
      </EngineProvider>
    </MemoryRouter>,
  )
}

test.each([
  [Memory, 'Memory'],
  [Agents, 'Agents'],
  [Quality, 'Quality'],
  [Prompts, 'Prompts'],
  [Journal, 'Log'],
  [Planning, 'Scheduling'],
])('each page renders with its title', (Page, title) => {
  wrap(<Page />)
  expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument()
})

describe('demo data reducer', () => {
  test('ignores an empty or duplicate preference', () => {
    let s = demoReducer(initialDemo, { type: 'add_pref', text: '  ' })
    expect(s.prefs).toEqual(initialDemo.prefs)
    s = demoReducer(s, { type: 'add_pref', text: initialDemo.prefs[0] })
    expect(s.prefs).toHaveLength(initialDemo.prefs.length)
  })
  test('ignores an unknown prompt version', () => {
    const s = demoReducer(initialDemo, { type: 'use_prompt', name: 'system', version: 'v99' })
    expect(s.promptActive.system).toBe('v1')
  })
  test('ignores a task without a title', () => {
    const s = demoReducer(initialDemo, { type: 'add_task', title: ' ', every: 'every day' })
    expect(s.tasks).toEqual(initialDemo.tasks)
  })
})

test('memory: add, ignore empty, forget all', () => {
  wrap(<Memory />)
  const input = screen.getByLabelText(/new preference/i)
  fireEvent.change(input, { target: { value: 'comment in English' } })
  fireEvent.click(screen.getByRole('button', { name: /^add$/i }))
  expect(screen.getByText('comment in English')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^add$/i })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /forget everything/i }))
  expect(screen.queryByText('comment in English')).not.toBeInTheDocument()
  expect(screen.getByText(/no saved preference/i)).toBeInTheDocument()
})

test('prompts: view a diff, activate, then roll back', () => {
  wrap(<Prompts />)
  expect(screen.getByTestId('active-system')).toHaveTextContent('v1')
  fireEvent.click(screen.getByRole('button', { name: /v2/i }))
  expect(screen.getAllByText(/^\+ /).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: /activate/i }))
  expect(screen.getByTestId('active-system')).toHaveTextContent('v2')
  fireEvent.click(screen.getByRole('button', { name: /v1/i }))
  fireEvent.click(screen.getByRole('button', { name: /activate/i }))
  expect(screen.getByTestId('active-system')).toHaveTextContent('v1')
})

test('scheduling: create, ignore empty title, disable', () => {
  wrap(<Planning />)
  fireEvent.click(screen.getByRole('button', { name: /schedule/i }))
  expect(screen.queryByText('Dependency watch')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/task title/i), { target: { value: 'Dependency watch' } })
  fireEvent.change(screen.getByLabelText(/frequency/i), { target: { value: 'every Monday' } })
  fireEvent.click(screen.getByRole('button', { name: /schedule/i }))
  const row = screen.getByText('Dependency watch').closest('li') as HTMLElement
  expect(row).toHaveTextContent('every Monday')
  fireEvent.click(within(row).getByRole('switch'))
  expect(within(row).getByRole('switch')).toHaveAttribute('aria-checked', 'false')
})

describe('session-fed pages', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function Driver({ text }: { text: string }) {
    const { send } = useEngine()
    return <button onClick={() => send(text)}>go</button>
  }

  test('log empty, then filled by the real session calls', () => {
    wrap(<><Driver text="Write a function that computes the average latency of the log" /><Journal /></>)
    expect(screen.getByText(/no call yet/i)).toBeInTheDocument()
    fireEvent.click(screen.getByText('go'))
    act(() => { vi.advanceTimersByTime(30000) })
    expect(screen.getAllByText('sandbox.run')).toHaveLength(2)
    expect(screen.getByTestId('metric-calls')).toHaveTextContent('2')
    expect(screen.getByTestId('metric-latency')).toHaveTextContent('395 ms')
    expect(screen.getByTestId('metric-errors')).toHaveTextContent('50 %')
  })

  test('agents: enabling an agent creates a visible handoff', () => {
    wrap(<Agents />)
    fireEvent.click(screen.getByRole('button', { name: /enable reviewer/i }))
    expect(screen.getByText(/CodeSensai → Reviewer/)).toBeInTheDocument()
  })

  test('quality: lists the adversarial tests, including an acknowledged weakness', () => {
    wrap(<Quality />)
    expect(screen.getAllByText(/blocked/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/weakness/i).length).toBeGreaterThan(0)
  })

  test('quality: structured output points to /structured in the terminal, with no fake example', () => {
    wrap(<Quality />)
    expect(screen.queryByRole('heading', { name: /structured output/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/accepted by the schema/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('structured-note')).toHaveTextContent('/structured')
    expect(screen.getByTestId('structured-note')).toHaveTextContent('ADR-0039')
  })

  test('quality: without a server, the adversarial tests are labeled as a simulated example', () => {
    wrap(<Quality />)
    expect(screen.getByText(/Simulated example for the demo/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rerun the attacks' })).not.toBeInTheDocument()
  })
})

test('#44: with the real server, the Memory page lists the real conversations and reopens one', async () => {
  const { Routes, Route } = await import('react-router-dom')
  const engine = new MockEngine({ route })
  const openSession = vi.fn(async () => [{ id: 'h0', role: 'user' as const, text: 'q1' }])
  Object.assign(engine, {
    listSessions: vi.fn(async () => [{ id: 'OLD', title: 'Yesterday', updatedAt: '2026-10-28T18:00:00+00:00', messageCount: 4 }]),
    openSession,
  })
  render(
    <MemoryRouter initialEntries={['/memoire']}>
      <DemoDataProvider>
        <EngineProvider engine={engine}>
          <Routes>
            <Route path="/memoire" element={<Memory />} />
            <Route path="/chat" element={<p>chat page</p>} />
          </Routes>
        </EngineProvider>
      </DemoDataProvider>
    </MemoryRouter>,
  )
  expect(await screen.findByText('Yesterday')).toBeInTheDocument()
  expect(screen.getByText(/4 messages · 2026-10-28 18:00/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Reopen Yesterday' }))
  expect(await screen.findByText('chat page')).toBeInTheDocument()
  expect(openSession).toHaveBeenCalledWith('OLD')
})

test('with the real server, the Memory page shows and edits the real profile and facts', async () => {
  const engine = new MockEngine({ route })
  let prefs = ['use pytest']
  const addPreference = vi.fn(async (t: string) => { prefs = [...prefs, t]; return { name: '', instructions: '', preferences: prefs } })
  const forgetPreferences = vi.fn(async () => { prefs = []; return { name: '', instructions: '', preferences: [] } })
  Object.assign(engine, {
    getProfile: vi.fn(async () => ({ name: '', instructions: '', preferences: prefs })),
    getFacts: vi.fn(async () => [{ entity: 'redis', attribute: 'version', value: '7' }]),
    addPreference,
    forgetPreferences,
  })
  render(
    <MemoryRouter>
      <EngineProvider engine={engine}>
        <DemoDataProvider><Memory /></DemoDataProvider>
      </EngineProvider>
    </MemoryRouter>,
  )
  expect(await screen.findByText('use pytest')).toBeInTheDocument()
  expect(await screen.findByText('version : 7')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('New preference'), { target: { value: 'comment in English' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add' }))
  expect(await screen.findByText('comment in English')).toBeInTheDocument()
  expect(addPreference).toHaveBeenCalledWith('comment in English')
  fireEvent.click(screen.getByRole('button', { name: 'Forget everything' }))
  expect(await screen.findByText('No saved preference.')).toBeInTheDocument()
})

test('Memory: "Forget" removes the facts of an entity (real server)', async () => {
  const engine = new MockEngine({ route })
  const forgetFact = vi.fn(async () => true)
  Object.assign(engine, {
    getProfile: vi.fn(async () => ({ name: '', instructions: '', preferences: [] })),
    getFacts: vi.fn(async () => [{ entity: 'mot_de_test', attribute: 'mot', value: 'zebre' }]),
    forgetFact,
  })
  render(<MemoryRouter><EngineProvider engine={engine}><DemoDataProvider><Memory /></DemoDataProvider></EngineProvider></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Forget mot_de_test' }))
  expect(forgetFact).toHaveBeenCalledWith('mot_de_test')
  await vi.waitFor(() => expect(screen.queryByText('mot : zebre')).not.toBeInTheDocument())
})
