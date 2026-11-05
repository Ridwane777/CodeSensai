import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Engine, SessionSummary } from '../src/contract/engine'
import { ConversationList } from '../src/features/chat/ConversationList'
import { EngineProvider } from '../src/state/useEngine'

const LIST: SessionSummary[] = [
  { id: 'A', title: 'Lancer les tests', updatedAt: '2026-10-29T10:00:00+00:00', messageCount: 2 },
  { id: 'B', title: 'Renommer parse', updatedAt: '2026-10-28T10:00:00+00:00', messageCount: 4 },
]

function setup() {
  let current: string | null = 'A'
  const e = {
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
    listSessions: vi.fn(async () => LIST),
    openSession: vi.fn(async (id: string) => { current = id; return [] }),
    newConversation: vi.fn(() => { current = null; return true }),
    deleteSession: vi.fn(async () => true),
    currentSession: () => current,
  }
  render(<EngineProvider engine={e as unknown as Engine}><ConversationList /></EngineProvider>)
  return e
}

test('liste les conversations et marque celle qui est ouverte', async () => {
  setup()
  expect(await screen.findByText('Lancer les tests')).toHaveAttribute('aria-current', 'true')
  expect(screen.getByText('Renommer parse')).not.toHaveAttribute('aria-current')
})

test('rouvrir, et commencer une nouvelle conversation', async () => {
  const e = setup()
  fireEvent.click(await screen.findByText('Renommer parse'))
  expect(e.openSession).toHaveBeenCalledWith('B')
  fireEvent.click(screen.getByText('+ Nouvelle conversation'))
  expect(e.newConversation).toHaveBeenCalled()
})

test('supprimer demande une confirmation dans la ligne, et « Non » ne supprime rien', async () => {
  const e = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Supprimer Renommer parse' }))
  fireEvent.click(screen.getByText('Non'))
  expect(e.deleteSession).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Supprimer Renommer parse' }))
  await act(async () => { fireEvent.click(screen.getByText('Oui')) })
  expect(e.deleteSession).toHaveBeenCalledWith('B')
  expect(screen.queryByText('Renommer parse')).not.toBeInTheDocument()
})

test('sans serveur réel, pas de barre latérale', () => {
  const e = { send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}) }
  const { container } = render(<EngineProvider engine={e as unknown as Engine}><ConversationList /></EngineProvider>)
  expect(container).toBeEmptyDOMElement()
})
