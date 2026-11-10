import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach } from 'vitest'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'
import Chat from '../src/pages/Chat'
import { EngineProvider } from '../src/state/useEngine'
import { renderInline, renderRich, visibleAnswer } from '../src/features/chat/inline'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function renderChat() {
  render(
    <MemoryRouter>
      <EngineProvider engine={new MockEngine({ route })}>
        <Chat />
      </EngineProvider>
    </MemoryRouter>,
  )
}

const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms) })
const type = (text: string) => {
  fireEvent.change(screen.getByRole('textbox', { name: /message/i }), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: /send/i }))
}

test("the welcome greets and shows the input right away", () => {
  renderChat()
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSensai/)
  expect(screen.getByRole('textbox', { name: /message/i })).toBeInTheDocument()
})

test("sending is disabled while the input is empty", () => {
  renderChat()
  expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: /message/i }), { target: { value: '   ' } })
  expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
})

test("a sent message shows, then the answer streams in", () => {
  renderChat()
  type('Resume where we left off')
  expect(screen.getByText('Resume where we left off')).toBeInTheDocument()
  advance(300)
  expect(screen.queryByText(/Welcome back/)).not.toBeInTheDocument()
  advance(20000)
  expect(screen.getByText(/Welcome back/)).toBeInTheDocument()
})

test('clicking a suggestion sends its text', () => {
  renderChat()
  fireEvent.click(screen.getByRole('button', { name: /search the code/i }))
  expect(screen.getByText(/unknown session does not crash/i, { selector: 'p' })).toBeInTheDocument()
})

test('Stop cuts the generation and says so', () => {
  renderChat()
  type('Resume where we left off')
  advance(400)
  fireEvent.click(screen.getByRole('button', { name: /stop the answer/i }))
  advance(20000)
  expect(screen.queryByRole('button', { name: /stop the answer/i })).not.toBeInTheDocument()
  expect(screen.getByText(/interrupted/i)).toBeInTheDocument()
  expect(screen.queryByText(/Welcome back/)).not.toBeInTheDocument()
})

test('Escape in the input also stops the generation', () => {
  renderChat()
  type('Resume where we left off')
  advance(400)
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Message' }), { key: 'Escape' })
  advance(20000)
  expect(screen.getByText(/interrupted/i)).toBeInTheDocument()
  expect(screen.queryByText(/Welcome back/)).not.toBeInTheDocument()
})

test("editing a message creates a branch and the original stays viewable", () => {
  renderChat()
  type('Resume where we left off')
  advance(20000)
  fireEvent.click(screen.getByRole('button', { name: /edit the message/i }))
  fireEvent.change(screen.getByRole('textbox', { name: /new message text/i }), { target: { value: 'Give me a recap of the session' } })
  fireEvent.click(screen.getByRole('button', { name: /send the variant/i }))
  advance(20000)
  expect(screen.getByText('Give me a recap of the session')).toBeInTheDocument()
  expect(screen.queryByText('Resume where we left off')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /branche principale/i }))
  expect(screen.getByText('Resume where we left off')).toBeInTheDocument()
  expect(screen.queryByText('Give me a recap of the session')).not.toBeInTheDocument()
})

test('renderInline formats bold and code', () => {
  const { container } = render(<p>{renderInline('a **word** and `code`')}</p>)
  expect(container.querySelector('strong')?.textContent).toBe('word')
  expect(container.querySelector('code')?.textContent).toBe('code')
})

test('renderRich shows model code blocks, even unclosed ones', () => {
  const { container } = render(<div>{renderRich('Voici :\n```python\ndef add(a, b):\n    return a + b\n```\nFin `x`.')}</div>)
  expect(container.querySelector('pre code')?.textContent).toBe('def add(a, b):\n    return a + b')
  expect(container.querySelector('pre code')?.getAttribute('data-lang')).toBe('python')
  expect(container.textContent).not.toContain('```')
  expect(container.querySelectorAll('pre')).toHaveLength(1)
  expect(container.querySelector('p code, div > code')?.textContent).toBe('x')
  const streaming = render(<div>{renderRich('Start\n```js\nconst a = 1')}</div>)
  expect(streaming.container.querySelector('pre code')?.textContent).toBe('const a = 1')
  const plain = render(<div>{renderRich('aucun code')}</div>)
  expect(plain.container.querySelector('pre')).toBeNull()
})

test("tool calls written as text by the model are hidden", () => {
  const raw = '<function=write_file>\n<parameter=path>\na.txt\n</parameter>\n</function>\n</tool_call>\n\nMay I create a.txt?'
  expect(visibleAnswer(raw)).toBe('May I create a.txt?')
  expect(visibleAnswer('Je lis.\n<function=read_file>\n<parameter=path>')).toBe('Je lis.\n')
  expect(visibleAnswer('Nothing to hide.')).toBe('Nothing to hide.')
  expect(visibleAnswer('<tool_call>\n<function=x>\n</function>\n</tool_call>')).toBe('')
})
