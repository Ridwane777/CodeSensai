import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { Orb } from '../src/ui/Orb'
import { PillButton } from '../src/ui/PillButton'
import { SimBadge } from '../src/ui/SimBadge'
import { ThemeToggle } from '../src/ui/ThemeToggle'

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  try { localStorage.clear() } catch { /* storage unavailable */ }
})

test('the badge says the engine is simulated', () => {
  render(<SimBadge />)
  expect(screen.getByText(/simulated engine/i)).toBeInTheDocument()
})

test('ThemeToggle toggles data-theme and back', async () => {
  render(<ThemeToggle />)
  const btn = screen.getByRole('button', { name: /theme/i })
  await userEvent.click(btn)
  expect(document.documentElement.dataset.theme).toBe('dark')
  await userEvent.click(btn)
  expect(document.documentElement.dataset.theme).toBe('light')
})

test('Orb signals when it is thinking', () => {
  const { container, rerender } = render(<Orb thinking />)
  expect(container.firstChild).toHaveAttribute('data-thinking', 'true')
  rerender(<Orb thinking={false} />)
  expect(container.firstChild).toHaveAttribute('data-thinking', 'false')
})

test('PillButton with `to` is an accessible link', () => {
  render(
    <MemoryRouter>
      <PillButton to="/chat">Launch the demo</PillButton>
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: /launch the demo/i })).toHaveAttribute('href', '/chat')
})

test('disabled PillButton does not fire onClick', async () => {
  const onClick = vi.fn()
  render(<PillButton disabled onClick={onClick}>Send</PillButton>)
  await userEvent.click(screen.getByRole('button', { name: /send/i }))
  expect(onClick).not.toHaveBeenCalled()
})
