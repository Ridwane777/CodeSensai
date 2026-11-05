import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Landing from '../src/pages/Landing'
import { AppShell } from '../src/ui/AppShell'
import App from '../src/App'
import { EngineProvider, useEngine } from '../src/state/useEngine'

test("la page d'accueil propose de lancer la démo", async () => {
  render(<MemoryRouter><EngineProvider><Landing /></EngineProvider></MemoryRouter>)
  expect(screen.getByRole('link', { name: /lancer la démo/i })).toHaveAttribute('href', '/chat')
  expect(await screen.findByText('28', {}, { timeout: 3000 })).toBeInTheDocument()
})

test('AppShell affiche toujours le badge simulé et le contenu', () => {
  render(<MemoryRouter><EngineProvider><AppShell><p>contenu</p></AppShell></EngineProvider></MemoryRouter>)
  expect(screen.getByText(/moteur simulé/i)).toBeInTheDocument()
  expect(screen.getByText('contenu')).toBeInTheDocument()
})

test("l'application affiche le nom du produit", () => {
  render(<App />)
  expect(screen.getAllByText(/CodeSensei/i).length).toBeGreaterThan(0)
})

test("le menu (tiroir) s'ouvre, liste les pages et se ferme avec Échap", () => {
  render(<MemoryRouter><EngineProvider><AppShell><p>contenu</p></AppShell></EngineProvider></MemoryRouter>)
  const toggle = screen.getByRole('button', { name: /ouvrir le menu/i })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getAllByRole('link', { name: /mémoire/i })[0]).toHaveAttribute('href', '/memoire')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('button', { name: /ouvrir le menu/i })).toHaveAttribute('aria-expanded', 'false')
})

test('la hero présente le produit avec un titre de niveau 1', () => {
  render(<MemoryRouter><EngineProvider><Landing /></EngineProvider></MemoryRouter>)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSensei.*pense à voix haute/)
})

test("la première question posée sur l'accueil part dans le chat", () => {
  let seen: string[] = []
  function Probe() {
    seen = useEngine().state.timeline.flatMap((i) => (i.kind === 'user' ? [i.text] : []))
    return null
  }
  render(<MemoryRouter><EngineProvider><Landing /><Probe /></EngineProvider></MemoryRouter>)
  fireEvent.change(screen.getByRole('textbox', { name: /première question/i }), { target: { value: 'Explique le projet' } })
  fireEvent.click(screen.getByRole('button', { name: 'Envoyer' }))
  expect(seen).toEqual(['Explique le projet'])
})
