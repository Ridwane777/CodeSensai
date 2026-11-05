import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { shareLink } from '../src/export/shareLink'
import { toJson } from '../src/export/toJson'
import { toMarkdown } from '../src/export/toMarkdown'
import Export from '../src/pages/Export'
import { initialState, reduce, type Action, type UiState } from '../src/state/store'
import { EngineProvider } from '../src/state/useEngine'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'

const run = (actions: Action[]): UiState => actions.reduce(reduce, initialState)
const convo = run([
  { type: 'user_message', id: 'm1', text: 'Bonjour' },
  { type: 'turn_start', turnId: 't1', agent: 'sensei' },
  { type: 'thought', turnId: 't1', stepId: 's1', text: 'Je réfléchis' },
  { type: 'token', turnId: 't1', text: 'Salut !' },
  { type: 'done', turnId: 't1', interrupted: false },
  { type: 'artifact_patch', section: 'Décisions', markdown: '- une décision' },
])

test("export d'une conversation vide : JSON valide, sans exception", () => {
  const parsed = JSON.parse(toJson(initialState))
  expect(parsed.messages).toEqual([])
  expect(parsed.artifact).toEqual({})
})

test('le JSON contient messages, étapes de raisonnement et artefact', () => {
  const parsed = JSON.parse(toJson(convo))
  expect(parsed.messages).toHaveLength(2)
  expect(parsed.messages[0]).toMatchObject({ role: 'user', text: 'Bonjour' })
  expect(parsed.messages[1]).toMatchObject({ role: 'assistant', text: 'Salut !' })
  expect(parsed.messages[1].steps[0].thought).toBe('Je réfléchis')
  expect(parsed.artifact.Décisions).toBe('- une décision')
})

test("le Markdown d'une conversation vide reste lisible", () => {
  expect(toMarkdown(initialState)).toContain('Aucun message')
})

test("le Markdown contient les tours et l'artefact", () => {
  const md = toMarkdown(convo)
  expect(md).toContain('**Vous** : Bonjour')
  expect(md).toContain('**CodeSensei** : Salut !')
  expect(md).toContain('## Décisions')
  expect(md).toContain('- une décision')
})

test('le lien de partage est stable, distinct selon le contenu, et sur un domaine factice', () => {
  expect(shareLink(convo)).toBe(shareLink(convo))
  expect(shareLink(convo)).not.toBe(shareLink(initialState))
  expect(shareLink(convo)).toMatch(/^https:\/\/codesensei\.example\/s\/[0-9a-f]{8}$/)
})

describe('page Export', () => {
  const renderPage = () =>
    render(<MemoryRouter><EngineProvider engine={new MockEngine({ route })}><Export /></EngineProvider></MemoryRouter>)

  test('annonce que le lien est simulé et propose les trois formats', () => {
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Export' })).toBeInTheDocument()
    expect(screen.getByText(/lien simulé/i)).toBeInTheDocument()
    for (const n of [/json/i, /markdown/i, /pdf/i]) expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
  })

  test('exporter en JSON déclenche un téléchargement', () => {
    const create = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /json/i }))
    expect(create).toHaveBeenCalledTimes(1)
  })

  test('exporter en PDF ouvre la vue impression', () => {
    const print = vi.fn()
    window.print = print
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /pdf/i }))
    expect(print).toHaveBeenCalled()
  })
})

test('avec le serveur réel, la page Export crée un vrai lien à la demande', async () => {
  const engine = new MockEngine({ route }) as unknown as import('../src/contract/engine').Engine
  const share = vi.fn(async () => ({ url: 'http://127.0.0.1:8000/share/abc', token: 'abc', expiresAt: '2026-11-05T10:00:00+00:00' }))
  Object.assign(engine, { share })
  render(
    <EngineProvider engine={engine}>
      <MemoryRouter><Export /></MemoryRouter>
    </EngineProvider>,
  )
  expect(screen.queryByText(/Lien simulé/)).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Lien de partage')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Créer un lien de partage/ }))
  expect(await screen.findByDisplayValue('http://127.0.0.1:8000/share/abc')).toBeInTheDocument()
  expect(screen.getByText(/2026-11-05/)).toBeInTheDocument()
  expect(share).toHaveBeenCalledTimes(1)
})

test('avec le serveur réel, la page Export révoque le lien et télécharge l’export du serveur', async () => {
  const engine = new MockEngine({ route }) as unknown as import('../src/contract/engine').Engine
  const share = vi.fn(async () => ({ url: 'http://127.0.0.1:8000/share/abc', token: 'abc', expiresAt: '2026-11-05T10:00:00+00:00' }))
  const revokeShare = vi.fn(async () => true)
  const exportSession = vi.fn(async () => '# Conversation')
  Object.assign(engine, { share, revokeShare, exportSession })
  const createObjectURL = vi.fn(() => 'blob:x')
  Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
  render(
    <EngineProvider engine={engine}>
      <MemoryRouter><Export /></MemoryRouter>
    </EngineProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /Créer un lien de partage/ }))
  await screen.findByDisplayValue('http://127.0.0.1:8000/share/abc')
  fireEvent.click(screen.getByRole('button', { name: /Révoquer le lien/ }))
  expect(await screen.findByText(/Lien révoqué/)).toBeInTheDocument()
  expect(revokeShare).toHaveBeenCalledWith('abc')
  expect(screen.queryByLabelText('Lien de partage')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Conversation du serveur \(Markdown\)/ }))
  await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalled())
  expect(exportSession).toHaveBeenCalledWith('md')
})
