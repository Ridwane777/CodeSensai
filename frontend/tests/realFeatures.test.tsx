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

test('wire : usage, compression, artefact et étape de sous-agent viennent du serveur', () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({ type: 'usage', used: 2048, budget: 6192, num_ctx: 8192, estimated: true })).toEqual([
    { type: 'usage', used: 2048, budget: 6192, contextPct: 25 },
  ])
  expect(a.push({ type: 'compression', saved_tokens: 900 })).toEqual([{ type: 'compression', savedTokens: 900 }])
  expect(a.push({ type: 'artifact_patch', section: 'Décisions', markdown: '- SQLite' })).toEqual([
    { type: 'artifact_patch', section: 'Décisions', markdown: '- SQLite' },
  ])
  const step = a.push({ type: 'subagent_step', agent: 'explorateur', tool: 'read_file', arguments: { path: 'a.py' }, ok: true, content: 'x', duration_ms: 37 })
  expect(step.map((e) => e.type)).toEqual(['action', 'observation'])
  expect(step[0]).toMatchObject({ tool: 'explorateur › read_file', args: { path: 'a.py' } })
  expect(step[1]).toMatchObject({ ms: 37, ok: true })
  expect(a.push({ type: 'usage', used: 1 })).toEqual([]) // incomplet : ignoré
})

test('le vrai document d’état remplit le panneau Artefact au chargement', async () => {
  const e = { ...base(), getState: vi.fn(async () => ({ Décisions: '- SQLite', Vide: '' })) }
  let seen: Record<string, string> = {}
  function Probe() {
    seen = useEngine().state.artifact
    return null
  }
  render(<EngineProvider engine={e as unknown as Engine}><Probe /></EngineProvider>)
  await vi.waitFor(() => expect(seen).toEqual({ Décisions: '- SQLite' }))
})

test('Qualité : « Évaluer la dernière réponse » ajoute la vraie note, sans les exemples fixes', async () => {
  const e = { ...base(), evaluate: vi.fn(async () => ({ relevance: 4, coherence: 5, faithfulness: 0.5, passages: 2 })) }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><Quality /></EngineProvider></MemoryRouter>,
  )
  expect(screen.getByText(/Aucune réponse évaluée/)).toBeInTheDocument()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Évaluer la dernière réponse' })) })
  expect(e.evaluate).toHaveBeenCalled()
  expect(screen.getByText('Réponse évaluée n°1')).toBeInTheDocument()
})

test('Planification : les vraies tâches, ajout, pause et retrait', async () => {
  let tasks: ScheduledTask[] = [
    { id: 'veille', prompt: 'Résume les TODO', intervalS: 86400, enabled: true, lastRunAt: null, lastStatus: null, nextDue: null },
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
  expect(await screen.findByText('Résume les TODO')).toBeInTheDocument()
  expect(screen.getByText(/chaque jour · jamais exécutée/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/Ce que l'agent doit faire/), { target: { value: 'Bilan des tests échoués' } })
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Planifier' })) })
  expect(e.addTask).toHaveBeenCalledWith('bilan-des-tests-echoues', 'Bilan des tests échoués', '1d')
  expect(await screen.findByText('Bilan des tests échoués')).toBeInTheDocument()
  await act(async () => { fireEvent.click(screen.getByRole('switch', { name: 'Activer veille' })) })
  expect(e.setTaskEnabled).toHaveBeenCalledWith('veille', false)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retirer veille' })) })
  expect(screen.queryByText('Résume les TODO')).not.toBeInTheDocument()
})

test("l'identifiant d'une tâche respecte le format de sensai-schedule", () => {
  expect(taskIdFrom('  Bilan : tests échoués !! ')).toBe('bilan-tests-echoues')
  expect(taskIdFrom('???')).toBe('tache')
  expect(taskIdFrom('a'.repeat(60))).toHaveLength(40)
})

test('A7 : la page Prompts montre les vrais exemples few-shot', async () => {
  const { default: Prompts } = await import('../src/pages/Prompts')
  const e = {
    ...base(),
    getFewshot: vi.fn(async () => ({ configured: true, file: 'exemples.jsonl', minScore: 0.6, questions: ['Comment lancer les tests ?'], error: null })),
  }
  render(<MemoryRouter><EngineProvider engine={e as unknown as Engine}><DemoDataProvider><Prompts /></DemoDataProvider></EngineProvider></MemoryRouter>)
  expect(await screen.findByText('Comment lancer les tests ?')).toBeInTheDocument()
  expect(screen.getByText(/seuil 0.6/)).toBeInTheDocument()
  expect(screen.queryByText(/variante est notée/)).not.toBeInTheDocument()
})

const RUN = {
  cases: [
    { id: 'EV4-INJ-01', category: 'INJ', attempt: 'injection coupée par des espaces', expected: 'SIGNALÉ', observed: 'SIGNALÉ', verdict: 'OK', detail: '' },
    { id: 'EV4-INJ-05', category: 'INJ', attempt: 'o cyrillique', expected: 'ÉCART CONNU (sûr : SIGNALÉ)', observed: 'PASSE', verdict: 'ÉCART CONNU', detail: '' },
  ],
  summary: { total: 2, ok: 1, knownGaps: 1, regressions: 0, fixed: 0, skipped: 0 },
}

test('Qualité (EV4) : les vrais résultats du corpus, et « Relancer les attaques » appelle le moteur', async () => {
  const e = {
    ...base(),
    adversarialResults: vi.fn(async () => ({ ...RUN, ranAt: null, source: 'committed' as const })),
    runAdversarial: vi.fn(async () => ({ ...RUN, ranAt: '2026-11-01T10:00:00+00:00', source: 'run' as const })),
  }
  render(
    <MemoryRouter><EngineProvider engine={e as unknown as Engine}><Quality /></EngineProvider></MemoryRouter>,
  )
  expect(await screen.findByText('EV4-INJ-05')).toBeInTheDocument()
  expect(screen.getByText('o cyrillique')).toBeInTheDocument()
  expect(screen.queryByText(/Exemple simulé/)).not.toBeInTheDocument()
  expect(screen.getByTestId('attack-summary')).toHaveTextContent('2 cas · 1 OK · 1 écarts connus · 0 régressions')
  expect(screen.getByTestId('attack-date')).toHaveTextContent(/pas encore relancés/)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Relancer les attaques' })) })
  expect(e.runAdversarial).toHaveBeenCalledTimes(1)
  expect(screen.getByTestId('attack-date')).toHaveTextContent(/Passage du/)
})

test('Journal (EV3) : le journal enregistré de la conversation ouverte, puis les métriques de tous les outils', async () => {
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
  expect(screen.getByText(/modèle : 1 200 ms/)).toBeInTheDocument()
  expect(screen.getByTestId('metric-calls')).toHaveTextContent('2')
  expect(screen.getByTestId('metric-errors')).toHaveTextContent('1')
  fireEvent.click(screen.getByRole('tab', { name: 'Tous les outils' }))
  expect(screen.getByTestId('metric-model-mean')).toHaveTextContent('1 500 ms')
  expect(screen.getByText('55 ms')).toBeInTheDocument()
  expect(e.journalMetrics).toHaveBeenCalledWith(7)
})
