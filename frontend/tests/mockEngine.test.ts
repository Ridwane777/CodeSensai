import { afterEach, beforeEach } from 'vitest'
import { MockEngine } from '../src/engine/mockEngine'
import type { Scenario } from '../src/engine/scenarios/types'
import type { EngineEvent } from '../src/contract/events'

const scenario: Scenario = {
  id: 's',
  steps: [
    { delay: 10, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 10, event: { type: 'token', turnId: 't1', text: 'Salut' } },
    { delay: 10, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup() {
  const e = new MockEngine({ route: () => scenario })
  const got: EngineEvent[] = []
  e.subscribe((ev) => got.push(ev))
  return { e, got }
}

test("rejoue les étapes dans l'ordre avec leurs délais", () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'bonjour' })
  expect(got).toHaveLength(0)
  vi.advanceTimersByTime(30)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'token', 'done'])
})

test('saisie vide : aucun événement', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: '   ' })
  vi.advanceTimersByTime(1000)
  expect(got).toHaveLength(0)
})

test("désabonnement : plus d'événements", () => {
  const e = new MockEngine({ route: () => scenario })
  const got: EngineEvent[] = []
  const off = e.subscribe((ev) => got.push(ev))
  e.send({ id: 'm1', text: 'x' })
  off()
  vi.advanceTimersByTime(1000)
  expect(got).toHaveLength(0)
})

test('deux envois successifs produisent des identifiants de tour distincts', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  vi.advanceTimersByTime(30)
  e.send({ id: 'm2', text: 'b' })
  vi.advanceTimersByTime(30)
  const starts = got.filter((x) => x.type === 'turn_start') as { turnId: string }[]
  expect(new Set(starts.map((s) => s.turnId)).size).toBe(2)
})
