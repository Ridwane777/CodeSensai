import { fireEvent, render, screen } from '@testing-library/react'
import { renderInline, renderRich } from '../src/features/chat/markdown'

test('headings, bulleted and numbered lists, quotes and paragraphs', () => {
  const { container } = render(<div>{renderRich('## Plan\n- one\n- two\n\n1. a\n2. b\n> warning\n\nEnd.')}</div>)
  expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument()
  expect(container.querySelectorAll('ul li')).toHaveLength(2)
  expect(container.querySelectorAll('ol li')).toHaveLength(2)
  expect(container.querySelector('blockquote')?.textContent).toBe('warning')
  expect(container.textContent).toContain('End.')
})

test('an http(s) link is clickable and opens a new tab; a javascript: link stays text', () => {
  const { container } = render(<p>{renderInline('[doc](https://docs.pytest.org) and [trap](javascript:alert(1))')}</p>)
  const links = container.querySelectorAll('a')
  expect(links).toHaveLength(1)
  expect(links[0].getAttribute('href')).toBe('https://docs.pytest.org')
  expect(links[0].getAttribute('rel')).toContain('noopener')
  expect(container.textContent).toContain('trap')
})

test("italics do not catch bullets or multiplications", () => {
  const { container } = render(<p>{renderInline('a *word* and 2*3*4')}</p>)
  expect(container.querySelectorAll('em')).toHaveLength(1)
  expect(container.querySelector('em')?.textContent).toBe('word')
})

test('a Python code block is highlighted and the Copy button copies the raw code', async () => {
  const writeText = vi.fn(async () => {})
  Object.assign(navigator, { clipboard: { writeText } })
  const { container } = render(<div>{renderRich('```python\ndef f():\n    return 1\n```')}</div>)
  expect(container.querySelector('pre code span')).not.toBeNull()
  expect(container.querySelector('pre code')?.textContent).toBe('def f():\n    return 1')
  fireEvent.click(screen.getByRole('button', { name: 'Copy code' }))
  expect(writeText).toHaveBeenCalledWith('def f():\n    return 1')
  expect(await screen.findByText('✓ Copied')).toBeInTheDocument()
})

test('HTML written by the model stays text', () => {
  const { container } = render(<div>{renderRich('<img src=x onerror=alert(1)> **bold**')}</div>)
  expect(container.querySelector('img')).toBeNull()
  expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
})
