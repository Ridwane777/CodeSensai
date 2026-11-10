import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { shareLink } from '../src/export/shareLink'
import { toJson } from '../src/export/toJson'
import { toMarkdown } from '../src/export/toMarkdown'
import Export from '../src/pages/Export'
import { initialState, reduce, type Action, type UiState } from '../src/state/store'
import { EngineProvider } from '../src/state/useEngine'
import { MockEngine } from '../src/engine/mockEngine'
import { route } from '../src/engine/router'

const run = (actions: Action[]): UiState => actions.reduce(reduce, initialState)
const convo = run([
  { type: 'user_message', id: 'm1', text: 'Hello' },
  { type: 'turn_start', turnId: 't1', agent: 'sensei' },
  { type: 'thought', turnId: 't1', stepId: 's1', text: 'Thinking' },
  { type: 'token', turnId: 't1', text: 'Hi!' },
  { type: 'done', turnId: 't1', interrupted: false },
  { type: 'artifact_patch', section: 'Decisions', markdown: '- a decision' },
])

test("exporting an empty conversation: valid JSON, no exception", () => {
  const parsed = JSON.parse(toJson(initialState))
  expect(parsed.messages).toEqual([])
  expect(parsed.artifact).toEqual({})
})

test('the JSON holds messages, reasoning steps and artifact', () => {
  const parsed = JSON.parse(toJson(convo))
  expect(parsed.messages).toHaveLength(2)
  expect(parsed.messages[0]).toMatchObject({ role: 'user', text: 'Hello' })
  expect(parsed.messages[1]).toMatchObject({ role: 'assistant', text: 'Hi!' })
  expect(parsed.messages[1].steps[0].thought).toBe('Thinking')
  expect(parsed.artifact.Decisions).toBe('- a decision')
})

test("the Markdown of an empty conversation stays readable", () => {
  expect(toMarkdown(initialState)).toContain('Aucun message')
})

test("the Markdown holds the turns and the artifact", () => {
  const md = toMarkdown(convo)
  expect(md).toContain('**Vous** : Hello')
  expect(md).toMatch(/\*\*CodeSens[ae]i\*\* : Hi!/)
  expect(md).toContain('## Decisions')
  expect(md).toContain('- a decision')
})

test('the share link is stable, differs by content, and uses a fake domain', () => {
  expect(shareLink(convo)).toBe(shareLink(convo))
  expect(shareLink(convo)).not.toBe(shareLink(initialState))
  expect(shareLink(convo)).toMatch(/^https:\/\/codesensei\.example\/s\/[0-9a-f]{8}$/)
})

describe('Export page', () => {
  const renderPage = () =>
    render(<MemoryRouter><EngineProvider engine={new MockEngine({ route })}><Export /></EngineProvider></MemoryRouter>)

  test('says the link is simulated and offers the three formats', () => {
    renderPage()
    expect(screen.getByRole('heading', { level: 1, name: 'Export' })).toBeInTheDocument()
    expect(screen.getByText(/simulated link/i)).toBeInTheDocument()
    for (const n of [/json/i, /markdown/i, /pdf/i]) expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
  })

  test('exporting to JSON triggers a download', () => {
    const create = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /json/i }))
    expect(create).toHaveBeenCalledTimes(1)
  })

  test('exporting to PDF opens the print view', () => {
    const print = vi.fn()
    window.print = print
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /pdf/i }))
    expect(print).toHaveBeenCalled()
  })
})

test('with the real server, the Export page creates a real link on demand', async () => {
  const engine = new MockEngine({ route }) as unknown as import('../src/contract/engine').Engine
  const share = vi.fn(async () => ({ url: 'http://127.0.0.1:8000/share/abc', token: 'abc', expiresAt: '2026-11-05T10:00:00+00:00' }))
  Object.assign(engine, { share })
  render(
    <EngineProvider engine={engine}>
      <MemoryRouter><Export /></MemoryRouter>
    </EngineProvider>,
  )
  expect(screen.queryByText(/Simulated link/)).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Share link')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Create a share link/ }))
  expect(await screen.findByDisplayValue('http://127.0.0.1:8000/share/abc')).toBeInTheDocument()
  expect(screen.getByText(/2026-11-05/)).toBeInTheDocument()
  expect(share).toHaveBeenCalledTimes(1)
})

test('with the real server, the Export page revokes the link and downloads the server export', async () => {
  const engine = new MockEngine({ route }) as unknown as import('../src/contract/engine').Engine
  const share = vi.fn(async () => ({ url: 'http://127.0.0.1:8000/share/abc', token: 'abc', expiresAt: '2026-11-05T10:00:00+00:00' }))
  const revokeShare = vi.fn(async () => true)
  const exportSession = vi.fn(async () => '# Conversation')
  Object.assign(engine, { share, revokeShare, exportSession })
  const createObjectURL = vi.fn(() => 'blob:x')
  Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
  render(
    <EngineProvider engine={engine}>
      <MemoryRouter><Export /></MemoryRouter>
    </EngineProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /Create a share link/ }))
  await screen.findByDisplayValue('http://127.0.0.1:8000/share/abc')
  fireEvent.click(screen.getByRole('button', { name: /Revoke the link/ }))
  expect(await screen.findByText(/Link revoked/)).toBeInTheDocument()
  expect(revokeShare).toHaveBeenCalledWith('abc')
  expect(screen.queryByLabelText('Share link')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /Server conversation \(Markdown\)/ }))
  await vi.waitFor(() => expect(createObjectURL).toHaveBeenCalled())
  expect(exportSession).toHaveBeenCalledWith('md')
})
