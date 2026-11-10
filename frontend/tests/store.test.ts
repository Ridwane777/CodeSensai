import { initialState, reduce, visibleTimeline, type UiState, type Action } from '../src/state/store'

const run = (actions: Action[], from: UiState = initialState): UiState => actions.reduce(reduce, from)
const start: Action = { type: 'turn_start', turnId: 't1', agent: 'sensei' }

test('tokens are concatenated into the current turn', () => {
  const s = run([start, { type: 'token', turnId: 't1', text: 'Sa' }, { type: 'token', turnId: 't1', text: 'lut' }])
  const turn = s.timeline.find((i) => i.kind === 'turn')
  expect(turn && turn.kind === 'turn' && turn.turn.text).toBe('Salut')
  expect(s.thinking).toBe(true)
})

test('thought, action and observation with the same stepId form a single step', () => {
  const s = run([
    start,
    { type: 'thought', turnId: 't1', stepId: 's1', text: 'Searching' },
    { type: 'action', turnId: 't1', stepId: 's1', tool: 'rag.search', args: { q: 'x' } },
    { type: 'observation', turnId: 't1', stepId: 's1', text: '5 passages', ms: 340, ok: true },
  ])
  const turn = s.timeline.find((i) => i.kind === 'turn')
  const steps = turn && turn.kind === 'turn' ? turn.turn.steps : []
  expect(steps).toHaveLength(1)
  expect(steps[0]).toMatchObject({ thought: 'Searching', tool: 'rag.search', observation: '5 passages', ms: 340, ok: true })
})

test("an action then its observation produce a single log line", () => {
  const s = run([
    start,
    { type: 'action', turnId: 't1', stepId: 's1', tool: 'sandbox.run', args: {} },
    { type: 'observation', turnId: 't1', stepId: 's1', text: 'ok', ms: 410, ok: false },
  ])
  expect(s.logs).toHaveLength(1)
  expect(s.logs[0]).toMatchObject({ tool: 'sandbox.run', ms: 410, ok: false })
})

test('done stops thinking and records an interruption', () => {
  const s = run([start, { type: 'done', turnId: 't1', interrupted: true }])
  expect(s.thinking).toBe(false)
  const turn = s.timeline.find((i) => i.kind === 'turn')
  expect(turn && turn.kind === 'turn' && turn.turn.interrupted).toBe(true)
})

test('a confirmation request stays pending then is resolved', () => {
  const asked = run([
    start,
    { type: 'confirm_request', requestId: 'c1', title: 'Supprimer ?', detail: 'build/', risk: 'high' },
  ])
  const c = asked.timeline.find((i) => i.kind === 'confirm')
  expect(c && c.kind === 'confirm' && c.status).toBe('pending')
  const done = reduce(asked, { type: 'resolve', requestId: 'c1', status: 'approved' })
  const c2 = done.timeline.find((i) => i.kind === 'confirm')
  expect(c2 && c2.kind === 'confirm' && c2.status).toBe('approved')
})

test("resolving an unknown request changes nothing", () => {
  const s = reduce(initialState, { type: 'resolve', requestId: 'nope', status: 'approved' })
  expect(s.timeline).toEqual([])
})

test("usage replaces the gauge, error does not clear the conversation", () => {
  const s = run([
    { type: 'user_message', id: 'm1', text: 'a' },
    { type: 'usage', used: 10, budget: 100, contextPct: 10 },
    { type: 'error', message: 'oups' },
  ])
  expect(s.usage).toEqual({ used: 10, budget: 100, contextPct: 10 })
  expect(s.error).toBe('oups')
  expect(s.timeline).toHaveLength(1)
})

test("an artifact patch only touches its section", () => {
  const s = run([
    { type: 'artifact_patch', section: 'Decisions', markdown: 'a' },
    { type: 'artifact_patch', section: 'Tests', markdown: 'b' },
    { type: 'artifact_patch', section: 'Decisions', markdown: 'a2' },
  ])
  expect(s.artifact).toEqual({ Decisions: 'a2', Tests: 'b' })
  expect(s.lastPatched).toBe('Decisions')
})

test("the handoff changes the active agent", () => {
  const s = run([{ type: 'agent_handoff', from: 'sensei', to: 'reviewer' }])
  expect(s.persona).toBe('reviewer')
})

test("a handoff to a sub-agent is shown without changing the chosen agent", () => {
  const s = run([{ type: 'agent_handoff', from: 'sensei', to: 'explorateur', subAgent: true }])
  expect(s.persona).toBe('sensei')
  expect(s.timeline.at(-1)).toMatchObject({ kind: 'handoff', from: 'sensei', to: 'explorateur' })
})

test("a branch shows the history before the fork then its own messages", () => {
  let s = run([
    { type: 'user_message', id: 'm1', text: 'a' },
    { type: 'turn_start', turnId: 't1', agent: 'sensei' },
    { type: 'done', turnId: 't1', interrupted: false },
    { type: 'user_message', id: 'm2', text: 'b' },
  ])
  s = reduce(s, { type: 'fork', branch: 'b1', fromId: 'm2', id: 'm2-b1', text: 'b2' })
  s = reduce(s, { type: 'turn_start', turnId: 't2', agent: 'sensei' })
  const texts = (st: UiState, b: string) =>
    visibleTimeline(st, b).map((i) => (i.kind === 'user' ? i.text : i.kind))
  expect(texts(s, 'main')).toEqual(['a', 'turn', 'b'])
  expect(texts(s, 'b1')).toEqual(['a', 'turn', 'b2', 'turn'])
})

test("forking from an unknown message changes nothing", () => {
  const s = reduce(initialState, { type: 'fork', branch: 'b1', fromId: 'zzz', id: 'x', text: 'y' })
  expect(s).toEqual(initialState)
})


test("an interruption expires pending cards, which can no longer be resolved", () => {
  let s = run([
    start,
    { type: 'confirm_request', requestId: 'c1', title: 'Supprimer ?', detail: 'build/', risk: 'high' },
    { type: 'question', requestId: 'q1', title: 'Target', fields: [] },
    { type: 'done', turnId: 't1', interrupted: true },
  ])
  const kinds = s.timeline.flatMap((i) => (i.kind === 'confirm' || i.kind === 'question' ? [i.status] : []))
  expect(kinds).toEqual(['expired', 'expired'])
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'approved' })
  const c = s.timeline.find((i) => i.kind === 'confirm')
  expect(c && c.kind === 'confirm' && c.status).toBe('expired')
})

test("an already resolved request no longer changes state", () => {
  let s = run([start, { type: 'confirm_request', requestId: 'c1', title: 't', detail: 'd', risk: 'low' }])
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'approved' })
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'denied' })
  const c = s.timeline.find((i) => i.kind === 'confirm')
  expect(c && c.kind === 'confirm' && c.status).toBe('approved')
})

const texts = (st: UiState, b: string) => visibleTimeline(st, b).map((i) => (i.kind === 'user' ? i.text : i.kind))

test("editing an old message from a variant does not show the original", () => {
  let s = run([
    { type: 'user_message', id: 'm1', text: 'a' },
    { type: 'turn_start', turnId: 't1', agent: 'sensei' },
    { type: 'done', turnId: 't1', interrupted: false },
    { type: 'user_message', id: 'm2', text: 'b' },
  ])
  s = reduce(s, { type: 'fork', branch: 'b1', fromId: 'm2', id: 'm2-b1', text: 'b2' })
  s = reduce(s, { type: 'fork', branch: 'b2', fromId: 'm1', id: 'm1-b2', text: 'a2' })
  expect(texts(s, 'b2')).toEqual(['a2'])
  expect(texts(s, 'b1')).toEqual(['a', 'turn', 'b2'])
  expect(texts(s, 'main')).toEqual(['a', 'turn', 'b'])
})

test("a turn's items stay in the branch that started it even when switching view", () => {
  let s = run([{ type: 'user_message', id: 'm1', text: 'a' }])
  s = reduce(s, { type: 'fork', branch: 'b1', fromId: 'm1', id: 'm1-b1', text: 'a2' })
  s = reduce(s, { type: 'switch_branch', branch: 'main' })
  s = run([
    { type: 'turn_start', turnId: 't2', agent: 'sensei' },
    { type: 'confirm_request', requestId: 'c9', title: 't', detail: 'd', risk: 'low' },
    { type: 'guardrail', kind: 'secret', message: 'm' },
  ], s)
  expect(texts(s, 'b1')).toEqual(['a2', 'turn', 'confirm', 'guardrail'])
  expect(texts(s, 'main')).toEqual(['a'])
})

test("#44: a reopened conversation replaces the display with its history", () => {
  const s = run([
    { type: 'user_message', id: 'm1', text: 'avant' },
    { type: 'load_history', messages: [{ id: 'h0', role: 'user', text: 'q1' }, { id: 'h1', role: 'assistant', text: 'r1' }] },
  ])
  expect(s.timeline.map((i) => i.kind)).toEqual(['user', 'turn'])
  expect(s.timeline[0]).toMatchObject({ kind: 'user', id: 'h0', text: 'q1', branch: 'main' })
  expect(s.timeline[1]).toMatchObject({ kind: 'turn', turn: { text: 'r1', done: true } })
})

test("A7: the attached example's question is kept on the turn", () => {
  const s = run([
    { type: 'turn_start', turnId: 't1', agent: 'sensei' },
    { type: 'fewshot', turnId: 't1', question: 'How do I run the tests?' },
  ])
  expect(s.timeline.at(-1)).toMatchObject({ kind: 'turn', turn: { fewshot: 'How do I run the tests?' } })
})
