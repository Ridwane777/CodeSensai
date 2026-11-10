import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Engine } from '../src/contract/engine'
import { MAX_MESSAGE_CHARS, readAttachments, withAttachments } from '../src/features/chat/attachments'
import { Composer } from '../src/features/chat/Composer'
import { EngineProvider } from '../src/state/useEngine'

const file = (name: string, text: string) => new File([text], name, { type: 'text/plain' })

test('only text files are read; binary and unknown formats are rejected with a message', async () => {
  const { ok, errors } = await readAttachments([file('a.py', 'print(1)\n'), file('b.pdf', '%PDF'), file('c.txt', 'x\u0000y')])
  expect(ok).toEqual([{ name: 'a.py', lang: 'python', text: 'print(1)\n' }])
  expect(errors).toHaveLength(2)
})

test('the sent message holds the question, then each file in a code block', () => {
  expect(withAttachments(' Explain ', [{ name: 'a.py', lang: 'python', text: 'print(1)\n' }])).toBe(
    'Explain\n\nFichier joint : a.py\n```python\nprint(1)\n```',
  )
})

function renderComposer() {
  const e = { send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}) }
  render(<EngineProvider engine={e as unknown as Engine}><Composer /></EngineProvider>)
  return e
}

test('attach a file, see it, then send: the content goes with the message', async () => {
  const e = renderComposer()
  await act(async () => {
    fireEvent.change(screen.getByLabelText('Files to attach'), { target: { files: [file('a.py', 'print(1)')] } })
  })
  expect(screen.getByText(/a\.py/)).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Explain' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(e.send).toHaveBeenCalledWith(expect.objectContaining({ text: expect.stringContaining('```python\nprint(1)\n```') }))
  expect(screen.queryByText(/a\.py/)).not.toBeInTheDocument()
})

test('a dropped file is attached; a too-long message is blocked before the server', async () => {
  const e = renderComposer()
  const form = screen.getByRole('textbox', { name: 'Message' }).closest('form')!
  await act(async () => {
    fireEvent.drop(form, { dataTransfer: { files: [file('big.txt', 'x'.repeat(MAX_MESSAGE_CHARS))] } })
  })
  expect(screen.getByText(/big\.txt/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  expect(e.send).not.toHaveBeenCalled()
  expect(screen.getByRole('status')).toHaveTextContent('too long')
  fireEvent.click(screen.getByRole('button', { name: 'Remove big.txt' }))
  expect(screen.queryByText(/big\.txt/)).not.toBeInTheDocument()
})
