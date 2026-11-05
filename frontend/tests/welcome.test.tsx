import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'
import { Welcome } from '../src/features/chat/Welcome'
import Landing from '../src/pages/Landing'
import { EngineProvider } from '../src/state/useEngine'

const wrap = (ui: React.ReactElement) =>
  render(
    <MemoryRouter>
      <EngineProvider engine={new MockEngine({ route })}>{ui}</EngineProvider>
    </MemoryRouter>,
  )

test("l'accueil salue selon l'heure et se présente", () => {
  wrap(<Welcome now={new Date(2026, 9, 13, 20, 0)} />)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Bonsoir/)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSensei/)
})

test("l'accueil propose tout de suite le champ de saisie, sans bouton d'activation", () => {
  wrap(<Welcome now={new Date()} />)
  expect(screen.getByRole('textbox', { name: /message/i })).toHaveFocus()
  expect(screen.queryByRole('button', { name: /activer la conversation/i })).not.toBeInTheDocument()
})

test("l'accueil indique que le moteur est simulé et propose des départs rapides", () => {
  wrap(<Welcome now={new Date()} />)
  expect(screen.getByText(/moteur simulé/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /chercher dans le code/i })).toBeInTheDocument()
})

test("les chiffres de la landing arrivent à leur valeur finale", async () => {
  wrap(<Landing />)
  expect(await screen.findByText('28', {}, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /lancer la démo/i })).toHaveAttribute('href', '/chat')
})
