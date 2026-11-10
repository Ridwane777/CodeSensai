import { describeConfirm, WireAdapter } from '../src/engine/wire'

function adapter() {
  let t = 1000
  const a = new WireAdapter('t1', 'sensei', () => t)
  return { a, tick: (ms: number) => (t += ms) }
}

test('turn start and text', () => {
  const { a } = adapter()
  expect(a.start()).toEqual({ type: 'turn_start', turnId: 't1', agent: 'sensei' })
  expect(a.push({ type: 'token', text: 'Bonjour' })).toEqual([{ type: 'token', turnId: 't1', text: 'Bonjour' }])
})

test('a thought opens a step, the tool call attaches to it, the return measures the duration', () => {
  const { a, tick } = adapter()
  expect(a.push({ type: 'thought', text: 'Je lis.' })).toEqual([{ type: 'thought', turnId: 't1', stepId: 's1', text: 'Je lis.' }])
  expect(a.push({ type: 'tool_call', id: 'c1', name: 'read_file', arguments: { path: 'a.py' } })).toEqual([
    { type: 'action', turnId: 't1', stepId: 's1', tool: 'read_file', args: { path: 'a.py' } },
  ])
  tick(42)
  expect(a.push({ type: 'tool_return', id: 'c1', name: 'read_file', ok: true, content: 'x = 1' })).toEqual([
    { type: 'observation', turnId: 't1', stepId: 's1', text: 'x = 1', ms: 42, ok: true },
  ])
})

test('a second call without a thought opens its own step', () => {
  const { a } = adapter()
  a.push({ type: 'tool_call', id: 'c1', name: 'read_file', arguments: {} })
  const [second] = a.push({ type: 'tool_call', id: 'c2', name: 'run_code', arguments: {} })
  expect(second).toMatchObject({ stepId: 's2' })
  expect(a.push({ type: 'tool_return', id: 'c2', ok: false, content: 'Error' })[0]).toMatchObject({ stepId: 's2', ok: false })
})

test('a return without a known call breaks nothing', () => {
  const { a } = adapter()
  expect(a.push({ type: 'tool_return', id: 'zz', ok: true, content: 'r' })[0]).toMatchObject({ type: 'observation', stepId: 's1', ms: 0 })
})

test('the confirmation uses the tool summary, or the plain arguments', () => {
  const { a } = adapter()
  const [withDiff] = a.push({ type: 'confirm_request', id: 'x', confirm_id: 'C1', tool: 'write_file', risk: 'write', summary: '--- a.py\n+++ a.py', arguments: { path: 'a.py' } })
  expect(withDiff).toEqual({
    type: 'confirm_request', requestId: 'C1', title: 'The agent wants to use "write_file" (risk: write)', detail: '--- a.py\n+++ a.py', risk: 'high',
  })
  const [plain] = a.push({ type: 'confirm_request', id: 'C2', tool: 'run_code', risk: 'execute', summary: 'run_code({"code": "print(1)"})', arguments: { code: 'print(1)' } })
  expect(plain).toMatchObject({ requestId: 'C2', detail: 'code = print(1)', risk: 'high' })
})

test('a confirmation without an id is ignored', () => {
  const { a } = adapter()
  expect(a.push({ type: 'confirm_request', tool: 'write_file' })).toEqual([])
})

test('describeConfirm without arguments or summary', () => {
  expect(describeConfirm('x', '', '', {})).toEqual({ title: 'The agent wants to use "x" (risk: unknown)', detail: '(no details)' })
})

test('server extensions go through: sources, cache, guardrail', () => {
  const { a } = adapter()
  expect(a.push({ type: 'rag_sources', sources: [{ path: 'a.md', lines: '1-2', score: 0.8 }, 'broken'] })).toEqual([
    { type: 'rag_sources', sources: [{ path: 'a.md', lines: '1-2', score: 0.8 }, { path: '', lines: '', score: 0 }] },
  ])
  expect(a.push({ type: 'cache_hit', similarity: 0.95, question: 'q' })).toEqual([{ type: 'cache_hit', similarity: 0.95 }])
  expect(a.push({ type: 'guardrail', kind: 'bizarre', message: 'blocked' })).toEqual([{ type: 'guardrail', kind: 'unsafe', message: 'blocked' }])
})

test('done: interruption, step limit, reason kept', () => {
  const { a } = adapter()
  expect(a.push({ type: 'done', reason: 'interrupted' })).toEqual([{ type: 'done', turnId: 't1', interrupted: true }])
  const b = new WireAdapter('t2', 'sensei')
  expect(b.push({ type: 'done', reason: 'max_iterations' }).map((e) => e.type)).toEqual(['error', 'done'])
  expect(b.doneReason).toBe('max_iterations')
})

test('malformed data is ignored without an exception', () => {
  const { a } = adapter()
  expect(a.push(null)).toEqual([])
  expect(a.push('text')).toEqual([])
  expect(a.push({ type: 'usage', prompt_tokens: 3 })).toEqual([])
  expect(a.push({ type: 'error' })).toEqual([{ type: 'error', message: 'Unknown error' }])
  expect(a.push({ type: 'tool_call', id: 1, name: null, arguments: [1] })[0]).toMatchObject({ tool: '', args: {} })
})

test('text resumed after a tool starts a new paragraph', () => {
  const { a } = adapter()
  a.push({ type: 'token', text: 'I create the file.' })
  a.push({ type: 'tool_call', id: 'c1', name: 'write_file', arguments: {} })
  a.push({ type: 'tool_return', id: 'c1', ok: true, content: 'ok' })
  expect(a.push({ type: 'token', text: 'I created' })).toEqual([{ type: 'token', turnId: 't1', text: '\n\nI created' }])
  expect(a.push({ type: 'token', text: ' the file.' })[0]).toMatchObject({ text: ' the file.' })
})

test('without text before the tool, no leading paragraph break', () => {
  const { a } = adapter()
  a.push({ type: 'tool_call', id: 'c1', name: 'read_file', arguments: {} })
  expect(a.push({ type: 'token', text: 'Voici' })[0]).toMatchObject({ text: 'Voici' })
  expect(a.push({ type: 'token', text: '' })).toEqual([])
})

test('a server question becomes a form; malformed fields are dropped', () => {
  const { a } = adapter()
  const out = a.push({
    type: 'question', question_id: 'Q1', title: 'Details',
    fields: [
      { id: 'nom', kind: 'text', label: 'Nom', placeholder: 'ex. outils' },
      { id: 'style', kind: 'choice', label: 'Style', options: ['pytest', 'unittest'] },
      { id: 'docs', kind: 'toggle', label: 'Doc ?' },
      { id: 'seul', kind: 'choice', label: 'Un seul choix', options: ['x'] },
      { kind: 'text', label: 'no id' },
    ],
  })
  expect(out).toEqual([{
    type: 'question', requestId: 'Q1', title: 'Details',
    fields: [
      { id: 'nom', kind: 'text', label: 'Nom', placeholder: 'ex. outils' },
      { id: 'style', kind: 'choice', label: 'Style', options: ['pytest', 'unittest'] },
      { id: 'docs', kind: 'toggle', label: 'Doc ?' },
    ],
  }])
  expect(a.push({ type: 'question', question_id: 'Q2', title: 'vide', fields: [] })).toEqual([])
})

test('a server handoff keeps the persona name for the main agent', () => {
  const { a } = adapter()
  expect(a.push({ type: 'agent_handoff', from: 'main', to: 'explorateur' })).toEqual([
    { type: 'agent_handoff', from: 'sensei', to: 'explorateur', subAgent: true },
  ])
  expect(a.push({ type: 'agent_handoff', from: 'relecteur', to: 'main' })[0]).toMatchObject({ from: 'relecteur', to: 'sensei' })
  expect(a.push({ type: 'agent_handoff', from: 'main' })).toEqual([])
})

test('the attached few-shot example (A7) is linked to the turn', () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({ type: 'fewshot', question: 'How do I run the tests?' })).toEqual([
    { type: 'fewshot', turnId: 't1', question: 'How do I run the tests?' },
  ])
  expect(a.push({ type: 'fewshot' })).toEqual([])
})

test('server web search results reach the Sources tab, http(s) links only', () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({
    type: 'web_results',
    results: [{ title: 'Python 3.15.2', url: 'https://www.python.org/' }, { title: 'trap', url: 'javascript:alert(1)' }],
  })).toEqual([{ type: 'web_results', results: [{ title: 'Python 3.15.2', url: 'https://www.python.org/' }] }])
  expect(a.push({ type: 'web_results', results: [] })).toEqual([])
})
