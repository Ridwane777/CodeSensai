import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Engine, SessionSummary } from '../src/contract/engine'
import { ConversationList } from '../src/features/chat/ConversationList'
import { EngineProvider } from '../src/state/useEngine'

const LIST: SessionSummary[] = [
  { id: 'A', title: 'Run the tests', updatedAt: '2026-10-29T10:00:00+00:00', messageCount: 2 },
  { id: 'B', title: 'Rename parse', updatedAt: '2026-10-28T10:00:00+00:00', messageCount: 4 },
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

test('lists conversations and marks the open one', async () => {
  setup()
  expect(await screen.findByText('Run the tests')).toHaveAttribute('aria-current', 'true')
  expect(screen.getByText('Rename parse')).not.toHaveAttribute('aria-current')
})

test('reopen, and start a new conversation', async () => {
  const e = setup()
  fireEvent.click(await screen.findByText('Rename parse'))
  expect(e.openSession).toHaveBeenCalledWith('B')
  fireEvent.click(screen.getByText('+ Nouvelle conversation'))
  expect(e.newConversation).toHaveBeenCalled()
})

test('delete asks for inline confirmation, and "No" deletes nothing', async () => {
  const e = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Rename parse' }))
  fireEvent.click(screen.getByText('No'))
  expect(e.deleteSession).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete Rename parse' }))
  await act(async () => { fireEvent.click(screen.getByText('Yes')) })
  expect(e.deleteSession).toHaveBeenCalledWith('B')
  expect(screen.queryByText('Rename parse')).not.toBeInTheDocument()
})

test('without a real server, no sidebar', () => {
  const e = { send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}) }
  const { container } = render(<EngineProvider engine={e as unknown as Engine}><ConversationList /></EngineProvider>)
  expect(container).toBeEmptyDOMElement()
})
