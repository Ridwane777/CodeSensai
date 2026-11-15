import { afterEach, beforeEach } from 'vitest'
import { MockEngine } from '../src/engine/mockEngine'
import type { Scenario } from '../src/engine/scenarios/types'
import type { EngineEvent } from '../src/contract/events'
import type { Engine } from '../src/contract/engine'

const scenario: Scenario = {
  id: 's',
  steps: [
    { delay: 10, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 10, event: { type: 'token', turnId: 't1', text: 'Hi' } },
    { delay: 10, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

const gated: Scenario = {
  id: 'g',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'confirm_request', requestId: 'c1', title: 'Delete?', detail: 'build/', risk: 'high' } },
    { delay: 5, waitFor: 'confirm', requestId: 'c1' },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'done' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

const rid = (got: EngineEvent[]) =>
  [...got].reverse().map((x) => ('requestId' in x ? x.requestId : null)).find((x): x is string => x !== null) ?? 'none'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup(s: Scenario = scenario) {
  const e = new MockEngine({ route: () => s })
  const got: EngineEvent[] = []
  e.subscribe((ev) => got.push(ev))
  return { e, got }
}

test('MockEngine honors the Engine contract', () => {
  const e: Engine = new MockEngine({ route: () => scenario })
  expect(typeof e.subscribe).toBe('function')
})

test('interrupt cuts the stream and emits done interrupted', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'bonjour' })
  vi.advanceTimersByTime(15)
  e.interrupt()
  vi.advanceTimersByTime(1000)
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: true })
  expect(got.filter((x) => x.type === 'token')).toHaveLength(0)
})

test('interrupt without generation: no effect', () => {
  const { e, got } = setup()
  expect(() => e.interrupt()).not.toThrow()
  expect(got).toHaveLength(0)
})

test("editing an unknown message: error and history intact", () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  expect(e.editMessage('zzz', 'b')).toBeNull()
  expect(got.some((x) => x.type === 'error')).toBe(true)
  expect(e.history()).toHaveLength(1)
})

test("editing a message creates a branch and keeps the original", () => {
  const { e } = setup()
  e.send({ id: 'm1', text: 'a' })
  expect(e.editMessage('m1', 'a2')).toBe('b1')
  expect(e.history().map((m) => m.text)).toEqual(['a', 'a2'])
  expect(e.history().map((m) => m.branch)).toEqual(['main', 'b1'])
})

test('answer to an unknown card: ignored', () => {
  const { e, got } = setup()
  e.confirm('inconnu', true)
  vi.advanceTimersByTime(100)
  expect(got).toHaveLength(0)
})

test('playback waits for confirmation then resumes', () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'supprime' })
  vi.advanceTimersByTime(100)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'confirm_request'])
  e.confirm(rid(got), true)
  vi.advanceTimersByTime(100)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'confirm_request', 'token', 'done'])
})

test('an already resolved confirmation is ignored', () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'supprime' })
  vi.advanceTimersByTime(100)
  e.confirm(rid(got), true)
  vi.advanceTimersByTime(100)
  const n = got.length
  e.confirm(rid(got), false)
  vi.advanceTimersByTime(100)
  expect(got).toHaveLength(n)
})

test('a new send during a generation interrupts the previous one', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  vi.advanceTimersByTime(15)
  e.send({ id: 'm2', text: 'b' })
  vi.advanceTimersByTime(100)
  const dones = got.filter((x) => x.type === 'done') as { interrupted: boolean }[]
  expect(dones.map((d) => d.interrupted)).toEqual([true, false])
})

test("switching agents emits a handoff without touching history", () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  e.switchPersona('reviewer')
  expect(got.at(-1)).toEqual({ type: 'agent_handoff', from: 'sensei', to: 'reviewer' })
  expect(e.history()).toHaveLength(1)
})

test('interrupting before the first event cancels playback quietly', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  e.interrupt()
  vi.advanceTimersByTime(1000)
  expect(got).toHaveLength(0)
})

const branching: Scenario = {
  id: 'b',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'confirm_request', requestId: 'c1', title: 'Delete?', detail: 'build/', risk: 'high' } },
    {
      delay: 5,
      waitFor: 'confirm',
      requestId: 'c1',
      deny: [
        { delay: 5, event: { type: 'token', turnId: 't1', text: 'denied' } },
        { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
      ],
    },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'deleted' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test('a denial follows the scenario deny branch', () => {
  const { e, got } = setup(branching)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.confirm(rid(got), false)
  vi.advanceTimersByTime(100)
  const tokens = got.filter((x) => x.type === 'token').map((x) => (x as { text: string }).text)
  expect(tokens).toEqual(['denied'])
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: false })
})

test('an approval follows the normal path', () => {
  const { e, got } = setup(branching)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.confirm(rid(got), true)
  vi.advanceTimersByTime(100)
  const tokens = got.filter((x) => x.type === 'token').map((x) => (x as { text: string }).text)
  expect(tokens).toEqual(['deleted'])
})

const asking: Scenario = {
  id: 'a',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'question', requestId: 'q1', title: 'Target', fields: [{ id: 'env', kind: 'text', label: 'Env' }] } },
    { delay: 5, waitFor: 'answer', requestId: 'q1' },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'Target: {{env}} / {{unknown}}' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test('form answers are injected into the text, unknown keys stay readable', () => {
  const { e, got } = setup(asking)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.answer(rid(got), { env: 'staging' })
  vi.advanceTimersByTime(100)
  const tok = got.find((x) => x.type === 'token') as { text: string }
  expect(tok.text).toBe('Target: staging / -')
})

const askingArgs: Scenario = {
  id: 'aa',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'question', requestId: 'q1', title: 'Target', fields: [{ id: 'env', kind: 'text', label: 'Env' }] } },
    { delay: 5, waitFor: 'answer', requestId: 'q1' },
    { delay: 5, event: { type: 'action', turnId: 't1', stepId: 's1', tool: 'deploy.plan', args: { env: '{{env}}', tests: '{{tests}}', n: 3 } } },
    { delay: 5, event: { type: 'observation', turnId: 't1', stepId: 's1', text: 'target {{env}}', ms: 1, ok: true } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test("form answers are also injected into action arguments and observations", () => {
  const { e, got } = setup(askingArgs)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.answer(rid(got), { env: 'staging', tests: true })
  vi.advanceTimersByTime(100)
  const action = got.find((x) => x.type === 'action') as { args: Record<string, unknown> }
  expect(action.args).toEqual({ env: 'staging', tests: 'true', n: 3 })
  const o = got.find((x) => x.type === 'observation') as { text: string }
  expect(o.text).toBe('target staging')
})


test("two runs of the same scenario produce distinct request ids", () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.send({ id: 'm2', text: 'y' })
  vi.advanceTimersByTime(100)
  const ids = got.filter((x) => x.type === 'confirm_request').map((x) => (x as { requestId: string }).requestId)
  expect(ids).toHaveLength(2)
  expect(new Set(ids).size).toBe(2)
})

test("a confirmation from the first run does not unblock the second", () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  const first = rid(got)
  e.send({ id: 'm2', text: 'y' })
  vi.advanceTimersByTime(100)
  e.confirm(first, true)
  vi.advanceTimersByTime(100)
  expect(got.filter((x) => x.type === 'token')).toHaveLength(0)
})

const plain = (agent = 'sensei'): Scenario => ({
  id: 'p',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
})

test("after an agent switch, later turns are attributed to the new agent", () => {
  const { e, got } = setup(plain())
  e.switchPersona('reviewer')
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  expect(got.find((x) => x.type === 'turn_start')).toMatchObject({ agent: 'reviewer' })
})

const handoff: Scenario = {
  id: 'h',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'agent_handoff', from: 'sensei', to: 'reviewer' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test("a scripted handoff to the already active agent is not repeated", () => {
  const { e, got } = setup(handoff)
  e.switchPersona('reviewer')
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  expect(got.filter((x) => x.type === 'agent_handoff')).toHaveLength(1)
})

test("a scripted handoff updates the engine's active agent", () => {
  const { e, got } = setup(handoff)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.switchPersona('sensei')
  expect(got.at(-1)).toEqual({ type: 'agent_handoff', from: 'reviewer', to: 'sensei' })
})
