import { afterEach, beforeEach } from 'vitest'
import { MockEngine } from '../src/engine/mockEngine'
import type { Scenario } from '../src/engine/scenarios/types'
import type { EngineEvent } from '../src/contract/events'
import type { Engine } from '../src/contract/engine'

const scenario: Scenario = {
  id: 's',
  steps: [
    { delay: 10, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 10, event: { type: 'token', turnId: 't1', text: 'Salut' } },
    { delay: 10, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

const gated: Scenario = {
  id: 'g',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'confirm_request', requestId: 'c1', title: 'Supprimer ?', detail: 'build/', risk: 'high' } },
    { delay: 5, waitFor: 'confirm', requestId: 'c1' },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'fait' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

const rid = (got: EngineEvent[]) =>
  [...got].reverse().map((x) => ('requestId' in x ? x.requestId : null)).find((x): x is string => x !== null) ?? 'aucun'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

function setup(s: Scenario = scenario) {
  const e = new MockEngine({ route: () => s })
  const got: EngineEvent[] = []
  e.subscribe((ev) => got.push(ev))
  return { e, got }
}

test('MockEngine respecte le contrat Engine', () => {
  const e: Engine = new MockEngine({ route: () => scenario })
  expect(typeof e.subscribe).toBe('function')
})

test('interrupt coupe le flux et émet done interrupted', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'bonjour' })
  vi.advanceTimersByTime(15)
  e.interrupt()
  vi.advanceTimersByTime(1000)
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: true })
  expect(got.filter((x) => x.type === 'token')).toHaveLength(0)
})

test('interrupt sans génération : sans effet', () => {
  const { e, got } = setup()
  expect(() => e.interrupt()).not.toThrow()
  expect(got).toHaveLength(0)
})

test("éditer un message inconnu : error et historique intact", () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  expect(e.editMessage('zzz', 'b')).toBeNull()
  expect(got.some((x) => x.type === 'error')).toBe(true)
  expect(e.history()).toHaveLength(1)
})

test("éditer un message crée une branche et garde l'original", () => {
  const { e } = setup()
  e.send({ id: 'm1', text: 'a' })
  expect(e.editMessage('m1', 'a2')).toBe('b1')
  expect(e.history().map((m) => m.text)).toEqual(['a', 'a2'])
  expect(e.history().map((m) => m.branch)).toEqual(['main', 'b1'])
})

test('réponse à une carte inconnue : ignorée', () => {
  const { e, got } = setup()
  e.confirm('inconnu', true)
  vi.advanceTimersByTime(100)
  expect(got).toHaveLength(0)
})

test('la lecture attend la confirmation puis reprend', () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'supprime' })
  vi.advanceTimersByTime(100)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'confirm_request'])
  e.confirm(rid(got), true)
  vi.advanceTimersByTime(100)
  expect(got.map((x) => x.type)).toEqual(['turn_start', 'confirm_request', 'token', 'done'])
})

test('une confirmation déjà résolue est ignorée', () => {
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

test('un nouvel envoi pendant une génération interrompt la précédente', () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  vi.advanceTimersByTime(15)
  e.send({ id: 'm2', text: 'b' })
  vi.advanceTimersByTime(100)
  const dones = got.filter((x) => x.type === 'done') as { interrupted: boolean }[]
  expect(dones.map((d) => d.interrupted)).toEqual([true, false])
})

test("changer d'agent émet un passage de relais sans toucher à l'historique", () => {
  const { e, got } = setup()
  e.send({ id: 'm1', text: 'a' })
  e.switchPersona('reviewer')
  expect(got.at(-1)).toEqual({ type: 'agent_handoff', from: 'sensei', to: 'reviewer' })
  expect(e.history()).toHaveLength(1)
})

test('interrompre avant le premier événement annule la lecture sans bruit', () => {
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
    { delay: 5, event: { type: 'confirm_request', requestId: 'c1', title: 'Supprimer ?', detail: 'build/', risk: 'high' } },
    {
      delay: 5,
      waitFor: 'confirm',
      requestId: 'c1',
      deny: [
        { delay: 5, event: { type: 'token', turnId: 't1', text: 'refusé' } },
        { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
      ],
    },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'supprimé' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test('un refus suit la branche deny du scénario', () => {
  const { e, got } = setup(branching)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.confirm(rid(got), false)
  vi.advanceTimersByTime(100)
  const tokens = got.filter((x) => x.type === 'token').map((x) => (x as { text: string }).text)
  expect(tokens).toEqual(['refusé'])
  expect(got.at(-1)).toMatchObject({ type: 'done', interrupted: false })
})

test('une approbation suit la suite normale', () => {
  const { e, got } = setup(branching)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.confirm(rid(got), true)
  vi.advanceTimersByTime(100)
  const tokens = got.filter((x) => x.type === 'token').map((x) => (x as { text: string }).text)
  expect(tokens).toEqual(['supprimé'])
})

const asking: Scenario = {
  id: 'a',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'question', requestId: 'q1', title: 'Cible', fields: [{ id: 'env', kind: 'text', label: 'Env' }] } },
    { delay: 5, waitFor: 'answer', requestId: 'q1' },
    { delay: 5, event: { type: 'token', turnId: 't1', text: 'Cible : {{env}} / {{inconnu}}' } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test('les réponses du formulaire sont reprises dans le texte, les clés inconnues restent lisibles', () => {
  const { e, got } = setup(asking)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.answer(rid(got), { env: 'staging' })
  vi.advanceTimersByTime(100)
  const tok = got.find((x) => x.type === 'token') as { text: string }
  expect(tok.text).toBe('Cible : staging / —')
})

const askingArgs: Scenario = {
  id: 'aa',
  steps: [
    { delay: 5, event: { type: 'turn_start', turnId: 't1', agent: 'sensei' } },
    { delay: 5, event: { type: 'question', requestId: 'q1', title: 'Cible', fields: [{ id: 'env', kind: 'text', label: 'Env' }] } },
    { delay: 5, waitFor: 'answer', requestId: 'q1' },
    { delay: 5, event: { type: 'action', turnId: 't1', stepId: 's1', tool: 'deploy.plan', args: { env: '{{env}}', tests: '{{tests}}', n: 3 } } },
    { delay: 5, event: { type: 'observation', turnId: 't1', stepId: 's1', text: 'cible {{env}}', ms: 1, ok: true } },
    { delay: 5, event: { type: 'done', turnId: 't1', interrupted: false } },
  ],
}

test("les réponses du formulaire sont aussi reprises dans les arguments d'action et les observations", () => {
  const { e, got } = setup(askingArgs)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.answer(rid(got), { env: 'staging', tests: true })
  vi.advanceTimersByTime(100)
  const action = got.find((x) => x.type === 'action') as { args: Record<string, unknown> }
  expect(action.args).toEqual({ env: 'staging', tests: 'true', n: 3 })
  const o = got.find((x) => x.type === 'observation') as { text: string }
  expect(o.text).toBe('cible staging')
})


test("deux exécutions du même scénario produisent des identifiants de requête distincts", () => {
  const { e, got } = setup(gated)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.send({ id: 'm2', text: 'y' })
  vi.advanceTimersByTime(100)
  const ids = got.filter((x) => x.type === 'confirm_request').map((x) => (x as { requestId: string }).requestId)
  expect(ids).toHaveLength(2)
  expect(new Set(ids).size).toBe(2)
})

test("une confirmation de la première exécution ne débloque pas la seconde", () => {
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

test("après un changement d'agent, les tours suivants sont attribués au nouvel agent", () => {
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

test("un relais scénarisé vers l'agent déjà actif n'est pas répété", () => {
  const { e, got } = setup(handoff)
  e.switchPersona('reviewer')
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  expect(got.filter((x) => x.type === 'agent_handoff')).toHaveLength(1)
})

test("un relais scénarisé met à jour l'agent actif du moteur", () => {
  const { e, got } = setup(handoff)
  e.send({ id: 'm1', text: 'x' })
  vi.advanceTimersByTime(100)
  e.switchPersona('sensei')
  expect(got.at(-1)).toEqual({ type: 'agent_handoff', from: 'reviewer', to: 'sensei' })
})
