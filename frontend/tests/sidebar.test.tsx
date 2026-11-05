import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { Engine, SessionSummary } from '../src/contract/engine'
import { EngineProvider } from '../src/state/useEngine'
import { AppShell } from '../src/ui/AppShell'

const LIST: SessionSummary[] = [
  { id: 'A', title: 'Lancer les tests', updatedAt: '2026-10-29T10:00:00+00:00', messageCount: 2 },
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
            <Route path="/chat" element={<p>page chat</p>} />
            <Route path="*" element={<p>autre page</p>} />
          </Routes>
        </AppShell>
      </EngineProvider>
    </MemoryRouter>,
  )
}

// La barre fixe (grand écran) est toujours dans le DOM : on l'interroge en premier.
const mainNav = () => screen.getAllByRole('navigation', { name: 'Navigation principale' })[0]

test('liste les pages, Accueil en premier, et marque la page active', () => {
  setup(baseEngine())
  const links = within(mainNav()).getAllByRole('link')
  expect(links[0]).toHaveTextContent('Accueil')
  expect(within(mainNav()).getByRole('link', { name: 'Mémoire' })).toHaveAttribute('aria-current', 'page')
  expect(within(mainNav()).getByRole('link', { name: 'Chat' })).not.toHaveAttribute('aria-current')
})

test('le tiroir s’ouvre au bouton et se ferme au bouton, au fond et avec Échap', () => {
  setup(baseEngine())
  const toggle = screen.getByRole('button', { name: /ouvrir le menu/i })
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

test('un clic sur un lien du tiroir le ferme', () => {
  setup(baseEngine())
  const toggle = screen.getByRole('button', { name: /ouvrir le menu/i })
  fireEvent.click(toggle)
  const drawer = document.getElementById(toggle.getAttribute('aria-controls')!)!
  fireEvent.click(within(drawer).getByRole('link', { name: 'Chat' }))
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('page chat')).toBeInTheDocument()
})

test('sans serveur réel, pas de conversations', () => {
  setup(baseEngine())
  expect(screen.queryByRole('navigation', { name: 'Conversations' })).not.toBeInTheDocument()
  expect(screen.queryByText('+ Nouvelle conversation')).not.toBeInTheDocument()
})

test('avec le serveur réel, ouvrir une conversation mène au chat', async () => {
  const e = realEngine()
  setup(e)
  expect(screen.getByText('autre page')).toBeInTheDocument()
  fireEvent.click((await screen.findAllByText('Lancer les tests'))[0])
  expect(e.openSession).toHaveBeenCalledWith('A')
  expect(screen.getByText('page chat')).toBeInTheDocument()
})

test('« + Nouvelle conversation » mène aussi au chat', async () => {
  const e = realEngine()
  setup(e)
  fireEvent.click((await screen.findAllByText('+ Nouvelle conversation'))[0])
  expect(e.newConversation).toHaveBeenCalled()
  expect(screen.getByText('page chat')).toBeInTheDocument()
})
