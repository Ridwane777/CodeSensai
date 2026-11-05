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
  [Memory, 'Mémoire'],
  [Agents, 'Agents'],
  [Quality, 'Qualité'],
  [Prompts, 'Prompts'],
  [Journal, 'Journal'],
  [Planning, 'Planification'],
])('chaque page se rend avec son titre', (Page, title) => {
  wrap(<Page />)
  expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument()
})

describe('reducer de données de démo', () => {
  test('ignore une préférence vide ou en double', () => {
    let s = demoReducer(initialDemo, { type: 'add_pref', text: '  ' })
    expect(s.prefs).toEqual(initialDemo.prefs)
    s = demoReducer(s, { type: 'add_pref', text: initialDemo.prefs[0] })
    expect(s.prefs).toHaveLength(initialDemo.prefs.length)
  })
  test('ignore une version de prompt inconnue', () => {
    const s = demoReducer(initialDemo, { type: 'use_prompt', name: 'system', version: 'v99' })
    expect(s.promptActive.system).toBe('v1')
  })
  test('ignore une tâche sans titre', () => {
    const s = demoReducer(initialDemo, { type: 'add_task', title: ' ', every: 'chaque jour' })
    expect(s.tasks).toEqual(initialDemo.tasks)
  })
})

test('mémoire : ajouter, ignorer le vide, tout oublier', () => {
  wrap(<Memory />)
  const input = screen.getByLabelText(/nouvelle préférence/i)
  fireEvent.change(input, { target: { value: 'commente en anglais' } })
  fireEvent.click(screen.getByRole('button', { name: /^ajouter$/i }))
  expect(screen.getByText('commente en anglais')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^ajouter$/i })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /tout oublier/i }))
  expect(screen.queryByText('commente en anglais')).not.toBeInTheDocument()
  expect(screen.getByText(/aucune préférence/i)).toBeInTheDocument()
})

test('prompts : voir un diff, mettre en service puis revenir en arrière', () => {
  wrap(<Prompts />)
  expect(screen.getByTestId('active-system')).toHaveTextContent('v1')
  fireEvent.click(screen.getByRole('button', { name: /v2/i }))
  expect(screen.getAllByText(/^\+ /).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: /mettre en service/i }))
  expect(screen.getByTestId('active-system')).toHaveTextContent('v2')
  fireEvent.click(screen.getByRole('button', { name: /v1/i }))
  fireEvent.click(screen.getByRole('button', { name: /mettre en service/i }))
  expect(screen.getByTestId('active-system')).toHaveTextContent('v1')
})

test('planification : créer, ignorer le titre vide, désactiver', () => {
  wrap(<Planning />)
  fireEvent.click(screen.getByRole('button', { name: /planifier/i }))
  expect(screen.queryByText('Veille des dépendances')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText(/titre de la tâche/i), { target: { value: 'Veille des dépendances' } })
  fireEvent.change(screen.getByLabelText(/fréquence/i), { target: { value: 'chaque lundi' } })
  fireEvent.click(screen.getByRole('button', { name: /planifier/i }))
  const row = screen.getByText('Veille des dépendances').closest('li') as HTMLElement
  expect(row).toHaveTextContent('chaque lundi')
  fireEvent.click(within(row).getByRole('switch'))
  expect(within(row).getByRole('switch')).toHaveAttribute('aria-checked', 'false')
})

describe('pages alimentées par la session', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function Driver({ text }: { text: string }) {
    const { send } = useEngine()
    return <button onClick={() => send(text)}>go</button>
  }

  test('journal vide puis alimenté par les appels réels de la session', () => {
    wrap(<><Driver text="Écris une fonction qui calcule la latence moyenne du journal" /><Journal /></>)
    expect(screen.getByText(/aucun appel/i)).toBeInTheDocument()
    fireEvent.click(screen.getByText('go'))
    act(() => { vi.advanceTimersByTime(30000) })
    expect(screen.getAllByText('sandbox.run')).toHaveLength(2)
    expect(screen.getByTestId('metric-calls')).toHaveTextContent('2')
    expect(screen.getByTestId('metric-latency')).toHaveTextContent('395 ms')
    expect(screen.getByTestId('metric-errors')).toHaveTextContent('50 %')
  })

  test('agents : activer un agent crée un relais visible', () => {
    wrap(<Agents />)
    fireEvent.click(screen.getByRole('button', { name: /activer relecteur/i }))
    expect(screen.getByText(/CodeSensei → Relecteur/)).toBeInTheDocument()
  })

  test('qualité : liste les tests adverses, dont une faiblesse assumée', () => {
    wrap(<Quality />)
    expect(screen.getAllByText(/bloqué/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/faiblesse/i).length).toBeGreaterThan(0)
  })

  test('qualité : la sortie structurée renvoie à /structured dans le terminal, sans faux exemple', () => {
    wrap(<Quality />)
    expect(screen.queryByRole('heading', { name: /sortie structurée/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/accepté par le schéma/i)).not.toBeInTheDocument()
    expect(screen.getByTestId('structured-note')).toHaveTextContent('/structured')
    expect(screen.getByTestId('structured-note')).toHaveTextContent('ADR-0039')
  })

  test('qualité : sans serveur, les tests adverses sont étiquetés comme exemple simulé', () => {
    wrap(<Quality />)
    expect(screen.getByText(/Exemple simulé pour la démo/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Relancer les attaques' })).not.toBeInTheDocument()
  })
})

test('#44 : avec le serveur réel, la page Mémoire liste les vraies conversations et en rouvre une', async () => {
  const { Routes, Route } = await import('react-router-dom')
  const engine = new MockEngine({ route })
  const openSession = vi.fn(async () => [{ id: 'h0', role: 'user' as const, text: 'q1' }])
  Object.assign(engine, {
    listSessions: vi.fn(async () => [{ id: 'OLD', title: 'Hier', updatedAt: '2026-10-28T18:00:00+00:00', messageCount: 4 }]),
    openSession,
  })
  render(
    <MemoryRouter initialEntries={['/memoire']}>
      <DemoDataProvider>
        <EngineProvider engine={engine}>
          <Routes>
            <Route path="/memoire" element={<Memory />} />
            <Route path="/chat" element={<p>page du chat</p>} />
          </Routes>
        </EngineProvider>
      </DemoDataProvider>
    </MemoryRouter>,
  )
  expect(await screen.findByText('Hier')).toBeInTheDocument()
  expect(screen.getByText(/4 messages · 2026-10-28 18:00/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Rouvrir Hier' }))
  expect(await screen.findByText('page du chat')).toBeInTheDocument()
  expect(openSession).toHaveBeenCalledWith('OLD')
})

test('avec le serveur réel, la page Mémoire montre et modifie le vrai profil et les vrais faits', async () => {
  const engine = new MockEngine({ route })
  let prefs = ['utilise pytest']
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
  expect(await screen.findByText('utilise pytest')).toBeInTheDocument()
  expect(await screen.findByText('version : 7')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Nouvelle préférence'), { target: { value: 'commente en anglais' } })
  fireEvent.click(screen.getByRole('button', { name: 'Ajouter' }))
  expect(await screen.findByText('commente en anglais')).toBeInTheDocument()
  expect(addPreference).toHaveBeenCalledWith('commente en anglais')
  fireEvent.click(screen.getByRole('button', { name: 'Tout oublier' }))
  expect(await screen.findByText('Aucune préférence enregistrée.')).toBeInTheDocument()
})

test('Mémoire : « Oublier » retire les faits d\'une entité (serveur réel)', async () => {
  const engine = new MockEngine({ route })
  const forgetFact = vi.fn(async () => true)
  Object.assign(engine, {
    getProfile: vi.fn(async () => ({ name: '', instructions: '', preferences: [] })),
    getFacts: vi.fn(async () => [{ entity: 'mot_de_test', attribute: 'mot', value: 'zebre' }]),
    forgetFact,
  })
  render(<MemoryRouter><EngineProvider engine={engine}><DemoDataProvider><Memory /></DemoDataProvider></EngineProvider></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Oublier mot_de_test' }))
  expect(forgetFact).toHaveBeenCalledWith('mot_de_test')
  await vi.waitFor(() => expect(screen.queryByText('mot : zebre')).not.toBeInTheDocument())
})
