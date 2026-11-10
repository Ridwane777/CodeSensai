import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { Engine, ScheduledTask } from '../src/contract/engine'
import { WireAdapter } from '../src/engine/wire'
import Planning, { taskIdFrom } from '../src/pages/Planning'
import Quality from '../src/pages/Quality'
import { DemoDataProvider } from '../src/state/demoContext'
import { EngineProvider, useEngine } from '../src/state/useEngine'

const base = () => ({
  send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
  switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
})

test('wire: usage, compression, artifact and sub-agent step come from the server', () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({ type: 'usage', used: 2048, budget: 6192, num_ctx: 8192, estimated: true })).toEqual([
    { type: 'usage', used: 2048, budget: 6192, contextPct: 25 },
  ])
  expect(a.push({ type: 'compression', saved_tokens: 900 })).toEqual([{ type: 'compression', savedTokens: 900 }])
  expect(a.push({ type: 'artifact_patch', section: 'Decisions', markdown: '- SQLite' })).toEqual([
    { type: 'artifact_patch', section: 'Decisions', markdown: '- SQLite' },
  ])
  const step = a.push({ type: 'subagent_step', agent: 'explorateur', tool: 'read_file', arguments: { path: 'a.py' }, ok: true, content: 'x', duration_ms: 37 })
  expect(step.map((e) => e.type)).toEqual(['action', 'observation'])
  expect(step[0]).toMatchObject({ tool: 'explorateur › read_file', args: { path: 'a.py' } })
  expect(step[1]).toMatchObject({ ms: 37, ok: true })
  expect(a.push({ type: 'usage', used: 1 })).toEqual([]) // incomplete: ignored
})

test('the real state document fills the Artifact panel on load', async () => {
  const e = { ...base(), getState: vi.fn(async () => ({ Decisions: '- SQLite', Empty: '' })) }
  let seen: Record<string, string> = {}
  function Probe() {
    seen = useEngine().state.artifact
    return null
  }
  render(<EngineProvider engine={e as unknown as Engine}><Probe /></EngineProvider>)
  await vi.waitFor(() => expect(seen).toEqual({ Decisions: '- SQLite' }))
})

test('Quality: "Evaluate the latest answer" adds the real score, without the fixed examples', async () => {
  const e = { ...base(), evaluate: vi.fn(async () => ({ relevance: 4, coherence: 5, faithfulness: 0.5, passages: 2 })) }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><Quality /></EngineProvider></MemoryRouter>,
  )
  expect(screen.getByText(/No evaluated answer/)).toBeInTheDocument()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Evaluate the latest answer' })) })
  expect(e.evaluate).toHaveBeenCalled()
  expect(screen.getByText('Evaluated answer #1')).toBeInTheDocument()
})

test('Scheduling: the real tasks, add, pause and remove', async () => {
  let tasks: ScheduledTask[] = [
    { id: 'veille', prompt: 'Summarize the TODOs', intervalS: 86400, enabled: true, lastRunAt: null, lastStatus: null, nextDue: null },
  ]
  const e = {
    ...base(),
    listTasks: vi.fn(async () => tasks),
    addTask: vi.fn(async (id: string, prompt: string) => {
      const t = { id, prompt, intervalS: 86400, enabled: true, lastRunAt: null, lastStatus: null, nextDue: null }
      tasks = [...tasks, t]
      return t
    }),
    setTaskEnabled: vi.fn(async (id: string, enabled: boolean) => { tasks = tasks.map((t) => (t.id === id ? { ...t, enabled } : t)); return true }),
    removeTask: vi.fn(async (id: string) => { tasks = tasks.filter((t) => t.id !== id); return true }),
  }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><DemoDataProvider><Planning /></DemoDataProvider></EngineProvider></MemoryRouter>,
  )
  expect(await screen.findByText('Summarize the TODOs')).toBeInTheDocument()
  expect(screen.getByText(/every day · never run/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/What the agent should do/), { target: { value: 'Failed tests recap' } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Schedule' })) })
  expect(e.addTask).toHaveBeenCalledWith('failed-tests-recap', 'Failed tests recap', '1d')
  expect(await screen.findByText('Failed tests recap')).toBeInTheDocument()
  await act(async () => { fireEvent.click(screen.getByRole('switch', { name: 'Enable veille' })) })
  expect(e.setTaskEnabled).toHaveBeenCalledWith('veille', false)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Remove veille' })) })
  expect(screen.queryByText('Summarize the TODOs')).not.toBeInTheDocument()
})

test('a task id follows the sensai-schedule format', () => {
  expect(taskIdFrom('  Bilan : tests échoués !! ')).toBe('bilan-tests-echoues')
  expect(taskIdFrom('???')).toBe('task')
  expect(taskIdFrom('a'.repeat(60))).toHaveLength(40)
})

test('A7: the Prompts page shows the real few-shot examples', async () => {
  const { default: Prompts } = await import('../src/pages/Prompts')
  const e = {
    ...base(),
    getFewshot: vi.fn(async () => ({ configured: true, file: 'examples.jsonl', minScore: 0.6, questions: ['How do I run the tests?'], error: null })),
  }
  render(<MemoryRouter><EngineProvider engine={e as unknown as Engine}><DemoDataProvider><Prompts /></DemoDataProvider></EngineProvider></MemoryRouter>)
  expect(await screen.findByText('How do I run the tests?')).toBeInTheDocument()
  expect(screen.getByText(/threshold 0.6/)).toBeInTheDocument()
  expect(screen.queryByText(/variant is scored/)).not.toBeInTheDocument()
})

const RUN = {
  cases: [
    { id: 'EV4-INJ-01', category: 'INJ', attempt: 'injection split by spaces', expected: 'FLAGGED', observed: 'FLAGGED', verdict: 'OK', detail: '' },
    { id: 'EV4-INJ-05', category: 'INJ', attempt: 'Cyrillic o', expected: 'KNOWN GAP (safe: FLAGGED)', observed: 'PASSED', verdict: 'KNOWN GAP', detail: '' },
  ],
  summary: { total: 2, ok: 1, knownGaps: 1, regressions: 0, fixed: 0, skipped: 0 },
}

test('Quality (EV4): the real corpus results, and "Rerun the attacks" calls the engine', async () => {
  const e = {
    ...base(),
    adversarialResults: vi.fn(async () => ({ ...RUN, ranAt: null, source: 'committed' as const })),
    runAdversarial: vi.fn(async () => ({ ...RUN, ranAt: '2026-11-01T10:00:00+00:00', source: 'run' as const })),
  }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><Quality /></EngineProvider></MemoryRouter>,
  )
  expect(await screen.findByText('EV4-INJ-05')).toBeInTheDocument()
  expect(screen.getByText('Cyrillic o')).toBeInTheDocument()
  expect(screen.queryByText(/Simulated example/)).not.toBeInTheDocument()
  expect(screen.getByTestId('attack-summary')).toHaveTextContent('2 cases · 1 OK · 1 known gaps · 0 regressions')
  expect(screen.getByTestId('attack-date')).toHaveTextContent(/not rerun here yet/)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Rerun the attacks' })) })
  expect(e.runAdversarial).toHaveBeenCalledTimes(1)
  expect(screen.getByTestId('attack-date')).toHaveTextContent(/Run of/)
})

test('Log (EV3): the recorded log of the open conversation, then the metrics of all tools', async () => {
  const { default: Journal } = await import('../src/pages/Journal')
  const e = {
    ...base(),
    currentSession: () => 's1',
    journal: vi.fn(async () => [
      {
        id: 1, startedAt: '2026-11-01T10:00:00+00:00', modelMs: 1200, tokensSent: 900, outcome: 'final_answer', interface: 'web',
        tools: [
          { tool: 'read_file', arguments: '{"path": "a.py"}', durationMs: 12, ok: true, agent: 'main' },
          { tool: 'search_codebase', arguments: '{}', durationMs: 40, ok: false, agent: 'explorateur' },
        ],
      },
    ]),
    journalMetrics: vi.fn(async () => ({
      days: 7,
      tools: [{ tool: 'read_file', calls: 5, failures: 1, meanMs: 20, maxMs: 55 }],
      model: { turns: 3, meanMs: 1500, maxMs: 2400, notFinal: 0 },
    })),
  }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><Journal /></EngineProvider></MemoryRouter>,
  )
  expect(await screen.findByText('{"path": "a.py"}')).toBeInTheDocument()
  expect(e.journal).toHaveBeenCalledWith('s1')
  expect(screen.getByText('explorateur › search_codebase')).toBeInTheDocument()
  expect(screen.getByText(/model: 1 200 ms/)).toBeInTheDocument()
  expect(screen.getByTestId('metric-calls')).toHaveTextContent('2')
  expect(screen.getByTestId('metric-errors')).toHaveTextContent('1')
  fireEvent.click(screen.getByRole('tab', { name: 'All tools' }))
  expect(screen.getByTestId('metric-model-mean')).toHaveTextContent('1 500 ms')
  expect(screen.getByText('55 ms')).toBeInTheDocument()
  expect(e.journalMetrics).toHaveBeenCalledWith(7)
})
