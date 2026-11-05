import { act, fireEvent, render, screen } from '@testing-library/react'
import type { Engine } from '../src/contract/engine'
import { MAX_MESSAGE_CHARS, readAttachments, withAttachments } from '../src/features/chat/attachments'
import { Composer } from '../src/features/chat/Composer'
import { EngineProvider } from '../src/state/useEngine'

const file = (name: string, text: string) => new File([text], name, { type: 'text/plain' })

test('seuls les fichiers texte sont lus ; le binaire et les formats inconnus sont refusés avec un message', async () => {
  const { ok, errors } = await readAttachments([file('a.py', 'print(1)\n'), file('b.pdf', '%PDF'), file('c.txt', 'x\u0000y')])
  expect(ok).toEqual([{ name: 'a.py', lang: 'python', text: 'print(1)\n' }])
  expect(errors).toHaveLength(2)
})

test('le message envoyé contient la question puis chaque fichier dans un bloc de code', () => {
  expect(withAttachments(' Explique ', [{ name: 'a.py', lang: 'python', text: 'print(1)\n' }])).toBe(
    'Explique\n\nFichier joint : a.py\n```python\nprint(1)\n```',
  )
})

function renderComposer() {
  const e = { send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(), answer: vi.fn(),
    switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}) }
  render(<EngineProvider engine={e as unknown as Engine}><Composer /></EngineProvider>)
  return e
}

test('joindre un fichier, le voir, puis envoyer : le contenu part avec le message', async () => {
  const e = renderComposer()
  await act(async () => {
    fireEvent.change(screen.getByLabelText('Fichiers à joindre'), { target: { files: [file('a.py', 'print(1)')] } })
  })
  expect(screen.getByText(/a\.py/)).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Explique' } })
  fireEvent.click(screen.getByRole('button', { name: 'Envoyer' }))
  expect(e.send).toHaveBeenCalledWith(expect.objectContaining({ text: expect.stringContaining('```python\nprint(1)\n```') }))
  expect(screen.queryByText(/a\.py/)).not.toBeInTheDocument()
})

test('un fichier glissé-déposé est joint ; un message trop long est bloqué avant le serveur', async () => {
  const e = renderComposer()
  const form = screen.getByRole('textbox', { name: 'Message' }).closest('form')!
  await act(async () => {
    fireEvent.drop(form, { dataTransfer: { files: [file('gros.txt', 'x'.repeat(MAX_MESSAGE_CHARS))] } })
  })
  expect(screen.getByText(/gros\.txt/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Envoyer' }))
  expect(e.send).not.toHaveBeenCalled()
  expect(screen.getByRole('status')).toHaveTextContent('trop long')
  fireEvent.click(screen.getByRole('button', { name: 'Retirer gros.txt' }))
  expect(screen.queryByText(/gros\.txt/)).not.toBeInTheDocument()
})
