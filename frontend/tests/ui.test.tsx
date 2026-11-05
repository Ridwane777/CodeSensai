import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Orb } from '../src/ui/Orb'
import { PillButton } from '../src/ui/PillButton'
import { SimBadge } from '../src/ui/SimBadge'
import { ThemeToggle } from '../src/ui/ThemeToggle'

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  try { localStorage.clear() } catch { /* stockage indisponible */ }
})

test('le badge indique que le moteur est simulé', () => {
  render(<SimBadge />)
  expect(screen.getByText(/moteur simulé/i)).toBeInTheDocument()
})

test('ThemeToggle bascule data-theme puis revient', async () => {
  render(<ThemeToggle />)
  const btn = screen.getByRole('button', { name: /thème/i })
  await userEvent.click(btn)
  expect(document.documentElement.dataset.theme).toBe('dark')
  await userEvent.click(btn)
  expect(document.documentElement.dataset.theme).toBe('light')
})

test('Orb signale quand il réfléchit', () => {
  const { container, rerender } = render(<Orb thinking />)
  expect(container.firstChild).toHaveAttribute('data-thinking', 'true')
  rerender(<Orb thinking={false} />)
  expect(container.firstChild).toHaveAttribute('data-thinking', 'false')
})

test('PillButton avec `to` est un lien accessible', () => {
  render(
    <MemoryRouter>
      <PillButton to="/chat">Lancer la démo</PillButton>
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: /lancer la démo/i })).toHaveAttribute('href', '/chat')
})

test('PillButton désactivé ne déclenche pas onClick', async () => {
  const onClick = vi.fn()
  render(<PillButton disabled onClick={onClick}>Envoyer</PillButton>)
  await userEvent.click(screen.getByRole('button', { name: /envoyer/i }))
  expect(onClick).not.toHaveBeenCalled()
})
