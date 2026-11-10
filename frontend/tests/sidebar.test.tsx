import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { Engine, SessionSummary } from '../src/contract/engine'
import { EngineProvider } from '../src/state/useEngine'
import { AppShell } from '../src/ui/AppShell'

const LIST: SessionSummary[] = [
  { id: 'A', title: 'Run the tests', updatedAt: '2026-10-29T10:00:00+00:00', messageCount: 2 },
]

function baseEngine() {
  return {
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
  }
}

function realEngine() {
  return {
    ...baseEngine(),
    listSessions: vi.fn(async () => LIST),
    openSession: vi.fn(async () => []),
    newConversation: vi.fn(() => true),
    deleteSession: vi.fn(async () => true),
    currentSession: () => null,
  }
}

function setup(engine: object, at = '/memoire') {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <EngineProvider engine={engine as unknown as Engine}>
        <AppShell>
          <Routes>
            <Route path="/chat" element={<p>chat page</p>} />
            <Route path="*" element={<p>other page</p>} />
          </Routes>
        </AppShell>
      </EngineProvider>
    </MemoryRouter>,
  )
}

// The fixed bar (large screens) is always in the DOM: query it first.
const mainNav = () => screen.getAllByRole('navigation', { name: 'Main navigation' })[0]

test('lists the pages, Home first, and marks the active page', () => {
  setup(baseEngine())
  const links = within(mainNav()).getAllByRole('link')
  expect(links[0]).toHaveTextContent('Home')
  expect(within(mainNav()).getByRole('link', { name: 'Memory' })).toHaveAttribute('aria-current', 'page')
  expect(within(mainNav()).getByRole('link', { name: 'Chat' })).not.toHaveAttribute('aria-current')
})

test('the drawer opens with the button and closes with the button, the backdrop and Escape', () => {
  setup(baseEngine())
  const toggle = screen.getByRole('button', { name: /open the menu/i })
  const id = toggle.getAttribute('aria-controls')!
  expect(document.getElementById(id)).toBeNull()

  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(document.getElementById(id)).not.toBeNull()
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'false')

  fireEvent.click(toggle)
  fireEvent.click(screen.getByTestId('sidebar-backdrop'))
  expect(toggle).toHaveAttribute('aria-expanded', 'false')

  fireEvent.click(toggle)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
})

test('clicking a drawer link closes it', () => {
  setup(baseEngine())
  const toggle = screen.getByRole('button', { name: /open the menu/i })
  fireEvent.click(toggle)
  const drawer = document.getElementById(toggle.getAttribute('aria-controls')!)!
  fireEvent.click(within(drawer).getByRole('link', { name: 'Chat' }))
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('chat page')).toBeInTheDocument()
})

test('without a real server, no conversations', () => {
  setup(baseEngine())
  expect(screen.queryByRole('navigation', { name: 'Conversations' })).not.toBeInTheDocument()
  expect(screen.queryByText('+ Nouvelle conversation')).not.toBeInTheDocument()
})

test('with the real server, opening a conversation leads to the chat', async () => {
  const e = realEngine()
  setup(e)
  expect(screen.getByText('other page')).toBeInTheDocument()
  fireEvent.click((await screen.findAllByText('Run the tests'))[0])
  expect(e.openSession).toHaveBeenCalledWith('A')
  expect(screen.getByText('chat page')).toBeInTheDocument()
})

test('"+ Nouvelle conversation" also leads to the chat', async () => {
  const e = realEngine()
  setup(e)
  fireEvent.click((await screen.findAllByText('+ Nouvelle conversation'))[0])
  expect(e.newConversation).toHaveBeenCalled()
  expect(screen.getByText('chat page')).toBeInTheDocument()
})
