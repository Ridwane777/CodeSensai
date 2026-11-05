import { fireEvent, render, screen } from '@testing-library/react'
import { renderInline, renderRich } from '../src/features/chat/markdown'

test('titres, listes à puces et numérotées, citations et paragraphes', () => {
  const { container } = render(<div>{renderRich('## Plan\n- un\n- deux\n\n1. a\n2. b\n> attention\n\nFin.')}</div>)
  expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument()
  expect(container.querySelectorAll('ul li')).toHaveLength(2)
  expect(container.querySelectorAll('ol li')).toHaveLength(2)
  expect(container.querySelector('blockquote')?.textContent).toBe('attention')
  expect(container.textContent).toContain('Fin.')
})

test('un lien http(s) est cliquable et ouvre un nouvel onglet ; un lien javascript: reste du texte', () => {
  const { container } = render(<p>{renderInline('[doc](https://docs.pytest.org) et [piège](javascript:alert(1))')}</p>)
  const links = container.querySelectorAll('a')
  expect(links).toHaveLength(1)
  expect(links[0].getAttribute('href')).toBe('https://docs.pytest.org')
  expect(links[0].getAttribute('rel')).toContain('noopener')
  expect(container.textContent).toContain('piège')
})

test("l'italique ne prend pas les puces ni les multiplications", () => {
  const { container } = render(<p>{renderInline('un *mot* et 2*3*4')}</p>)
  expect(container.querySelectorAll('em')).toHaveLength(1)
  expect(container.querySelector('em')?.textContent).toBe('mot')
})

test('un bloc de code Python est coloré et le bouton Copier copie le code brut', async () => {
  const writeText = vi.fn(async () => {})
  Object.assign(navigator, { clipboard: { writeText } })
  const { container } = render(<div>{renderRich('```python\ndef f():\n    return 1\n```')}</div>)
  expect(container.querySelector('pre code span')).not.toBeNull()
  expect(container.querySelector('pre code')?.textContent).toBe('def f():\n    return 1')
  fireEvent.click(screen.getByRole('button', { name: 'Copier le code' }))
  expect(writeText).toHaveBeenCalledWith('def f():\n    return 1')
  expect(await screen.findByText('✓ Copié')).toBeInTheDocument()
})

test('le HTML écrit par le modèle reste du texte', () => {
  const { container } = render(<div>{renderRich('<img src=x onerror=alert(1)> **gras**')}</div>)
  expect(container.querySelector('img')).toBeNull()
  expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
})
