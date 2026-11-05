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
  fireEvent.click(screen.getByRole('button', { name: /envoyer/i }))
}

test("l'accueil salue et montre tout de suite le champ de saisie", () => {
  renderChat()
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/CodeSensei/)
  expect(screen.getByRole('textbox', { name: /message/i })).toBeInTheDocument()
})

test("l'envoi est désactivé tant que la saisie est vide", () => {
  renderChat()
  expect(screen.getByRole('button', { name: /envoyer/i })).toBeDisabled()
  fireEvent.change(screen.getByRole('textbox', { name: /message/i }), { target: { value: '   ' } })
  expect(screen.getByRole('button', { name: /envoyer/i })).toBeDisabled()
})

test("un message envoyé s'affiche puis la réponse arrive en streaming", () => {
  renderChat()
  type('Reprends où on en était')
  expect(screen.getByText('Reprends où on en était')).toBeInTheDocument()
  advance(300)
  expect(screen.queryByText(/Re-bonjour/)).not.toBeInTheDocument()
  advance(20000)
  expect(screen.getByText(/Re-bonjour/)).toBeInTheDocument()
})

test('cliquer une suggestion envoie son texte', () => {
  renderChat()
  fireEvent.click(screen.getByRole('button', { name: /chercher dans le code/i }))
  expect(screen.getByText(/session inconnue ne plante pas/i, { selector: 'p' })).toBeInTheDocument()
})

test('Arrêter coupe la génération et le signale', () => {
  renderChat()
  type('Reprends où on en était')
  advance(400)
  fireEvent.click(screen.getByRole('button', { name: /arrêter/i }))
  advance(20000)
  expect(screen.queryByRole('button', { name: /arrêter/i })).not.toBeInTheDocument()
  expect(screen.getByText(/interrompu/i)).toBeInTheDocument()
  expect(screen.queryByText(/Re-bonjour/)).not.toBeInTheDocument()
})

test('Échap dans le champ de saisie arrête aussi la génération', () => {
  renderChat()
  type('Reprends où on en était')
  advance(400)
  fireEvent.keyDown(screen.getByRole('textbox', { name: 'Message' }), { key: 'Escape' })
  advance(20000)
  expect(screen.getByText(/interrompu/i)).toBeInTheDocument()
  expect(screen.queryByText(/Re-bonjour/)).not.toBeInTheDocument()
})

test("modifier un message crée une branche et l'original reste consultable", () => {
  renderChat()
  type('Reprends où on en était')
  advance(20000)
  fireEvent.click(screen.getByRole('button', { name: /modifier le message/i }))
  fireEvent.change(screen.getByRole('textbox', { name: /nouveau texte/i }), { target: { value: 'Fais le bilan de la séance' } })
  fireEvent.click(screen.getByRole('button', { name: /envoyer la variante/i }))
  advance(20000)
  expect(screen.getByText('Fais le bilan de la séance')).toBeInTheDocument()
  expect(screen.queryByText('Reprends où on en était')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /branche principale/i }))
  expect(screen.getByText('Reprends où on en était')).toBeInTheDocument()
  expect(screen.queryByText('Fais le bilan de la séance')).not.toBeInTheDocument()
})

test('renderInline met en forme le gras et le code', () => {
  const { container } = render(<p>{renderInline('un **mot** et `code`')}</p>)
  expect(container.querySelector('strong')?.textContent).toBe('mot')
  expect(container.querySelector('code')?.textContent).toBe('code')
})

test('renderRich affiche les blocs de code du modèle, même pas encore fermés', () => {
  const { container } = render(<div>{renderRich('Voici :\n```python\ndef add(a, b):\n    return a + b\n```\nFin `x`.')}</div>)
  expect(container.querySelector('pre code')?.textContent).toBe('def add(a, b):\n    return a + b')
  expect(container.querySelector('pre code')?.getAttribute('data-lang')).toBe('python')
  expect(container.textContent).not.toContain('```')
  expect(container.querySelectorAll('pre')).toHaveLength(1)
  expect(container.querySelector('p code, div > code')?.textContent).toBe('x')
  const streaming = render(<div>{renderRich('Début\n```js\nconst a = 1')}</div>)
  expect(streaming.container.querySelector('pre code')?.textContent).toBe('const a = 1')
  const plain = render(<div>{renderRich('aucun code')}</div>)
  expect(plain.container.querySelector('pre')).toBeNull()
})

test("les appels d'outil écrits en texte par le modèle ne sont pas affichés", () => {
  const raw = '<function=write_file>\n<parameter=path>\na.txt\n</parameter>\n</function>\n</tool_call>\n\nPuis-je créer a.txt ?'
  expect(visibleAnswer(raw)).toBe('Puis-je créer a.txt ?')
  expect(visibleAnswer('Je lis.\n<function=read_file>\n<parameter=path>')).toBe('Je lis.\n')
  expect(visibleAnswer('Rien à masquer.')).toBe('Rien à masquer.')
  expect(visibleAnswer('<tool_call>\n<function=x>\n</function>\n</tool_call>')).toBe('')
})
