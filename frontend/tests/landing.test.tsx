import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Landing from '../src/pages/Landing'
import { AppShell } from '../src/ui/AppShell'
import App from '../src/App'
import { EngineProvider, useEngine } from '../src/state/useEngine'

test("the landing page offers to launch the demo", async () => {
  render(<MemoryRouter><EngineProvider><Landing /></EngineProvider></MemoryRouter>)
  expect(screen.getByRole('link', { name: /start the demo/i })).toHaveAttribute('href', '/chat')
  expect(await screen.findByText('28', {}, { timeout: 3000 })).toBeInTheDocument()
})

test('AppShell always shows the simulated badge and the content', () => {
  render(<MemoryRouter><EngineProvider><AppShell><p>content</p></AppShell></EngineProvider></MemoryRouter>)
  expect(screen.getByText(/simulated engine/i)).toBeInTheDocument()
  expect(screen.getByText('content')).toBeInTheDocument()
})

test("the app shows the product name", () => {
  render(<App />)
  expect(screen.getAllByText(/CodeSens[ae]i/i).length).toBeGreaterThan(0)
})

test("the menu (drawer) opens, lists the pages and closes with Escape", () => {
  render(<MemoryRouter><EngineProvider><AppShell><p>content</p></AppShell></EngineProvider></MemoryRouter>)
  const toggle = screen.getByRole('button', { name: /open the menu/i })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getAllByRole('link', { name: /memory/i })[0]).toHaveAttribute('href', '/memoire')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByRole('button', { name: /open the menu/i })).toHaveAttribute('aria-expanded', 'false')
})

test('the hero introduces the product with a level-1 heading', () => {
  render(<MemoryRouter><EngineProvider><Landing /></EngineProvider></MemoryRouter>)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSens[ae]i.*thinks out loud/)
})

test("the first question asked on the landing page goes to the chat", () => {
  let seen: string[] = []
  function Probe() {
    seen = useEngine().state.timeline.flatMap((i) => (i.kind === 'user' ? [i.text] : []))
    return null
  }
  render(<MemoryRouter><EngineProvider><Landing /><Probe /></EngineProvider></MemoryRouter>)
  fireEvent.change(screen.getByRole('textbox', { name: /first question/i }), { target: { value: 'Explain the project' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(seen).toEqual(['Explain the project'])
})
