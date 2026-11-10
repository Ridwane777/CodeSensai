import { fireEvent, render, screen } from '@testing-library/react'
import { activity, ThinkingIndicator } from '../src/features/chat/ThinkingIndicator'
import type { Engine } from '../src/contract/engine'
import { ConfirmCard, ConfirmDetail, GuardrailCard, NoticeChip, QuestionCard } from '../src/features/chat/ActionCards'
import { ReasoningRibbon } from '../src/features/chat/ReasoningRibbon'
import type { ConfirmItem, GuardrailItem, QuestionItem } from '../src/state/store'
import { EngineProvider } from '../src/state/useEngine'

function fakeEngine() {
  const e = {
    send: vi.fn(), interrupt: vi.fn(), editMessage: vi.fn(() => null), confirm: vi.fn(),
    answer: vi.fn(), switchPersona: vi.fn(), subscribe: vi.fn(() => () => {}),
  }
  return { e, engine: e as unknown as Engine }
}

const confirm = (status: ConfirmItem['status']): ConfirmItem => ({
  kind: 'confirm', requestId: 'c1', title: 'Delete build/?', detail: '12 files', risk: 'high', status, branch: 'main',
})
test("an expired confirmation has no buttons and says why", () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('expired')} /></EngineProvider>)
  expect(screen.getByText(/expired/i)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

const question = (status: QuestionItem['status'], values?: Record<string, unknown>): QuestionItem => ({
  kind: 'question', requestId: 'q1', title: 'Prepare the deployment', status, values, branch: 'main',
  fields: [
    { id: 'env', kind: 'choice', label: 'Environment', options: ['staging', 'production'] },
    { id: 'tag', kind: 'text', label: 'Version' },
    { id: 'tests', kind: 'toggle', label: 'Run the tests' },
  ],
})

test('Allow and Deny call the engine with the right decision', () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('pending')} /></EngineProvider>)
  fireEvent.click(screen.getByRole('button', { name: /allow/i }))
  expect(e.confirm).toHaveBeenCalledWith('c1', true)
})

test('deny sends false', () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('pending')} /></EngineProvider>)
  fireEvent.click(screen.getByRole('button', { name: /deny/i }))
  expect(e.confirm).toHaveBeenCalledWith('c1', false)
})

test('a resolved confirmation shows the decision, without buttons', () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><ConfirmCard item={confirm('denied')} /></EngineProvider>)
  expect(screen.getByText(/denied/i)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test("the form blocks sending while a text field is empty, then sends the values", () => {
  const { e, engine } = fakeEngine()
  render(<EngineProvider engine={engine}><QuestionCard item={question('pending')} /></EngineProvider>)
  const submit = screen.getByRole('button', { name: /send my answers/i })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Version'), { target: { value: 'v0.3.0' } })
  fireEvent.click(screen.getByLabelText('Run the tests'))
  expect(submit).toBeEnabled()
  fireEvent.click(submit)
  expect(e.answer).toHaveBeenCalledWith('q1', { env: 'staging', tag: 'v0.3.0', tests: true })
})

test('an answered form shows a summary', () => {
  const { engine } = fakeEngine()
  render(<EngineProvider engine={engine}><QuestionCard item={question('answered', { env: 'staging', tag: 'v1', tests: false })} /></EngineProvider>)
  expect(screen.getByText(/staging/)).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

test('the guardrail names the kind of block', () => {
  const item: GuardrailItem = { kind: 'guardrail', gKind: 'secret', message: 'masked value', branch: 'main' }
  render(<GuardrailCard item={item} />)
  expect(screen.getByText(/secret masked/i)).toBeInTheDocument()
  expect(screen.getByText('masked value')).toBeInTheDocument()
})

test('the chips summarize compression, cache and evaluation', () => {
  render(<>
    <NoticeChip item={{ kind: 'compression', savedTokens: 1840, branch: 'main' }} />
    <NoticeChip item={{ kind: 'cache', similarity: 0.94, branch: 'main' }} />
    <NoticeChip item={{ kind: 'eval', relevance: 0.91, faithfulness: 0.88, branch: 'main' }} />
    <NoticeChip item={{ kind: 'handoff', from: 'sensei', to: 'reviewer', branch: 'main' }} />
  </>)
  expect(screen.getByText(/1 840 tokens freed/)).toBeInTheDocument()
  expect(screen.getByText(/94 %/)).toBeInTheDocument()
  expect(screen.getByText(/relevance 91 %/i)).toBeInTheDocument()
  expect(screen.getByText(/CodeSensai → Reviewer/)).toBeInTheDocument()
})

const steps = [
  { id: 's1', thought: 'I search', tool: 'rag.search', args: { q: 'x' }, observation: '5 passages', ms: 340, ok: true },
  { id: 's2', thought: 'I run', tool: 'sandbox.run', args: {}, observation: 'ZeroDivisionError', ms: 410, ok: false },
]

test('the reasoning shows steps, durations and failures in order', () => {
  render(<ReasoningRibbon steps={steps} active={false} />)
  const items = screen.getAllByRole('listitem')
  expect(items).toHaveLength(2)
  expect(items[0]).toHaveTextContent('I search')
  expect(items[0]).toHaveTextContent('340 ms')
  expect(items[1]).toHaveTextContent(/failed/i)
})

test('the reasoning collapses and expands', () => {
  render(<ReasoningRibbon steps={steps} active={false} />)
  const toggle = screen.getByRole('button', { name: /reasoning/i })
  fireEvent.click(toggle)
  expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
})

test("with no step, the reasoning renders nothing", () => {
  const { container } = render(<ReasoningRibbon steps={[]} active={false} />)
  expect(container).toBeEmptyDOMElement()
})

test("the write_file approval request shows the colored diff", () => {
  render(<ConfirmDetail text={'REPLACE /p/a.py (20 bytes). Changes:\n\n--- before\n+++ after\n@@ -1 +1 @@\n-x = 1\n+x = 2\n y = 3'} />)
  expect(screen.getByText(/REPLACE \/p\/a\.py/)).toBeInTheDocument()
  expect(screen.getByText('-x = 1').className).toContain('text-danger')
  expect(screen.getByText('+x = 2').className).toContain('text-ok')
  expect(screen.getByText('@@ -1 +1 @@').className).toContain('text-accent')
  expect(screen.getByText('+++ after').className).toContain('text-muted')
})

test('a detail without a diff stays plain text', () => {
  render(<ConfirmDetail text={'Delete build/ (12 files)'} />)
  expect(screen.queryByLabelText('Proposed changes')).not.toBeInTheDocument()
  expect(screen.getByText('Delete build/ (12 files)')).toBeInTheDocument()
})

test('an MCP tool has a badge, an internal tool does not', () => {
  render(
    <ReasoningRibbon
      steps={[
        { id: 's1', tool: 'mcp_time_get_current_time', args: {}, observation: '12:00', ok: true, ms: 5 },
        { id: 's2', tool: 'read_file', args: { path: 'a.py' }, observation: 'ok', ok: true, ms: 3 },
      ]}
      active={false}
    />,
  )
  const items = screen.getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('MCP')
  expect(items[1]).not.toHaveTextContent('MCP')
})

test('a handoff to a server sub-agent shows its role', () => {
  render(<NoticeChip item={{ kind: 'handoff', from: 'sensei', to: 'explorateur', branch: 'main' }} />)
  expect(screen.getByText(/CodeSensai → Explorer/)).toBeInTheDocument()
})

test('the reasoning stays open during the turn, then collapses at the end', () => {
  const { rerender } = render(<ReasoningRibbon steps={steps} active />)
  expect(screen.getAllByRole('listitem')).toHaveLength(2)
  rerender(<ReasoningRibbon steps={steps} active={false} took={12} />)
  expect(screen.queryByRole('listitem')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /reasoning · 2 steps · 12 s/i })).toHaveAttribute('aria-expanded', 'false')
})

test("the indicator says what the agent is doing: thinking, tool, writing", () => {
  const turn = { id: 't', agent: 'sensei', text: '', steps: [], done: false, interrupted: false }
  expect(activity(turn)).toBe('Thinking')
  expect(activity({ ...turn, steps: [{ id: 's', tool: 'read_file' }] })).toBe('Using read_file')
  expect(activity({ ...turn, text: 'Here' })).toBe('Writing')
  render(<ThinkingIndicator label="Thinking" since={Date.now()} />)
  expect(screen.getByRole('status', { name: /thinking in progress/i })).toBeInTheDocument()
})
