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

test("the welcome screen greets by time of day and introduces itself", () => {
  wrap(<Welcome now={new Date(2026, 9, 13, 20, 0)} />)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Good evening/)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSensai/)
})

test("the welcome screen shows the input right away, with no activation button", () => {
  wrap(<Welcome now={new Date()} />)
  expect(screen.getByRole('textbox', { name: /message/i })).toHaveFocus()
  expect(screen.queryByRole('button', { name: /enable the conversation/i })).not.toBeInTheDocument()
})

test("the welcome screen says the engine is simulated and offers quick starts", () => {
  wrap(<Welcome now={new Date()} />)
  expect(screen.getByText(/simulated engine/i)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /search the code/i })).toBeInTheDocument()
})

test("the landing figures reach their final value", async () => {
  wrap(<Landing />)
  expect(await screen.findByText('28', {}, { timeout: 3000 })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /start the demo/i })).toHaveAttribute('href', '/chat')
})
