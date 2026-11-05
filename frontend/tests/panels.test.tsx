import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach } from 'vitest'
import type { Engine } from '../src/contract/engine'
import { ArtifactPanel } from '../src/features/chat/ArtifactPanel'
import { PersonaSwitcher } from '../src/features/chat/PersonaSwitcher'
import { SourcesPanel } from '../src/features/chat/SourcesPanel'
import { StatusBar } from '../src/features/chat/StatusBar'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'
import Chat from '../src/pages/Chat'
import { EngineProvider } from '../src/state/useEngine'

test("l'artefact met en évidence la section modifiée et garde les autres", () => {
  render(<ArtifactPanel sections={{ Décisions: '- a', Tests: '- b' }} lastPatched="Tests" />)
  expect(screen.getByRole('heading', { name: 'Décisions' }).closest('section')).toHaveAttribute('data-fresh', 'false')
  expect(screen.getByRole('heading', { name: 'Tests' }).closest('section')).toHaveAttribute('data-fresh', 'true')
})

test("l'artefact vide explique à quoi il sert", () => {
  render(<ArtifactPanel sections={{}} lastPatched={null} />)
  expect(screen.getByText(/aucun document/i)).toBeInTheDocument()
})

test('les sources affichent chemin, lignes et score arrondi, et les liens web sont sûrs', () => {
  render(
    <SourcesPanel
      sources={[{ path: 'src/sensai/cli.py', lines: '112-116', score: 0.834 }]}
      web={[{ title: 'pytest', url: 'https://docs.pytest.org/' }]}
    />,
  )
  expect(screen.getByText('src/sensai/cli.py:112-116')).toBeInTheDocument()
  expect(screen.getByText('83 %')).toBeInTheDocument()
  const link = screen.getByRole('link', { name: /pytest/i })
  expect(link).toHaveAttribute('target', '_blank')
  expect(link.getAttribute('rel')).toContain('noopener')
})

test('la barre affiche les tokens et passe en alerte au-delà de 80 %', () => {
  const { rerender } = render(<StatusBar usage={{ used: 1240, budget: 8192, contextPct: 15 }} saved={0} />)
  expect(screen.getByText(/1 240 \/ 8 192 tokens/)).toBeInTheDocument()
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '15')
  expect(screen.getByRole('progressbar')).toHaveAttribute('data-alert', 'false')
  rerender(<StatusBar usage={{ used: 6900, budget: 8192, contextPct: 84 }} saved={1840} />)
  expect(screen.getByRole('progressbar')).toHaveAttribute('data-alert', 'true')
  expect(screen.getByText(/1 840 tokens économisés/)).toBeInTheDocument()
})

test("le sélecteur d'agent appelle le moteur", () => {
  const e = { send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(), switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}) }
  render(<EngineProvider engine={e as unknown as Engine}><PersonaSwitcher persona="sensei" /></EngineProvider>)
  fireEvent.change(screen.getByLabelText(/agent actif/i), { target: { value: 'reviewer' } })
  expect(e.switchPersona).toHaveBeenCalledWith('reviewer')
})

describe('page de chat avec panneaux', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())
  const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms) })
  const renderChat = () =>
    render(<MemoryRouter><EngineProvider engine={new MockEngine({ route })}><Chat /></EngineProvider></MemoryRouter>)

  test("changer d'agent en cours de session garde la conversation", () => {
    renderChat()
    fireEvent.click(screen.getByRole('button', { name: /reprendre la session/i }))
    advance(20000)
    fireEvent.change(screen.getByLabelText(/agent actif/i), { target: { value: 'reviewer' } })
    expect(screen.getByText(/Re-bonjour/)).toBeInTheDocument()
    expect(screen.getByText(/Passage de relais/)).toBeInTheDocument()
  })

  test("le scénario d'écriture remplit l'onglet Artefact", () => {
    renderChat()
    fireEvent.click(screen.getByRole('button', { name: /écrire et tester/i }))
    advance(30000)
    fireEvent.click(screen.getByRole('button', { name: /afficher le panneau/i }))
    fireEvent.click(screen.getByRole('tab', { name: /artefact/i }))
    expect(screen.getByRole('heading', { name: 'Tests' })).toBeInTheDocument()
  })

  test("la recherche remplit l'onglet Sources", () => {
    renderChat()
    fireEvent.click(screen.getByRole('button', { name: /chercher dans le code/i }))
    advance(30000)
    fireEvent.click(screen.getByRole('button', { name: /afficher le panneau/i }))
    fireEvent.click(screen.getByRole('tab', { name: /sources/i }))
    expect(screen.getByText('src/sensai/cli.py:112-116')).toBeInTheDocument()
  })
})
