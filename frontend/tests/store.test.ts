import { initialState, reduce, visibleTimeline, type UiState, type Action } from '../src/state/store'

const run = (actions: Action[], from: UiState = initialState): UiState => actions.reduce(reduce, from)
const start: Action = { type: 'turn_start', turnId: 't1', agent: 'sensei' }

test('les tokens se concatènent dans le tour courant', () => {
  const s = run([start, { type: 'token', turnId: 't1', text: 'Sa' }, { type: 'token', turnId: 't1', text: 'lut' }])
  const turn = s.timeline.find((i) => i.kind === 'turn')
  expect(turn && turn.kind === 'turn' && turn.turn.text).toBe('Salut')
  expect(s.thinking).toBe(true)
})

test('thought, action et observation du même stepId forment une seule étape', () => {
  const s = run([
    start,
    { type: 'thought', turnId: 't1', stepId: 's1', text: 'Je cherche' },
    { type: 'action', turnId: 't1', stepId: 's1', tool: 'rag.search', args: { q: 'x' } },
    { type: 'observation', turnId: 't1', stepId: 's1', text: '5 passages', ms: 340, ok: true },
  ])
  const turn = s.timeline.find((i) => i.kind === 'turn')
  const steps = turn && turn.kind === 'turn' ? turn.turn.steps : []
  expect(steps).toHaveLength(1)
  expect(steps[0]).toMatchObject({ thought: 'Je cherche', tool: 'rag.search', observation: '5 passages', ms: 340, ok: true })
})

test("une action puis son observation produisent une seule ligne de journal", () => {
  const s = run([
    start,
    { type: 'action', turnId: 't1', stepId: 's1', tool: 'sandbox.run', args: {} },
    { type: 'observation', turnId: 't1', stepId: 's1', text: 'ok', ms: 410, ok: false },
  ])
  expect(s.logs).toHaveLength(1)
  expect(s.logs[0]).toMatchObject({ tool: 'sandbox.run', ms: 410, ok: false })
})

test('done arrête la réflexion et note une interruption', () => {
  const s = run([start, { type: 'done', turnId: 't1', interrupted: true }])
  expect(s.thinking).toBe(false)
  const turn = s.timeline.find((i) => i.kind === 'turn')
  expect(turn && turn.kind === 'turn' && turn.turn.interrupted).toBe(true)
})

test('une demande de confirmation reste en attente puis est résolue', () => {
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

test("résoudre une demande inconnue ne change rien", () => {
  const s = reduce(initialState, { type: 'resolve', requestId: 'nope', status: 'approved' })
  expect(s.timeline).toEqual([])
})

test("usage remplace la jauge, error n'efface pas la conversation", () => {
  const s = run([
    { type: 'user_message', id: 'm1', text: 'a' },
    { type: 'usage', used: 10, budget: 100, contextPct: 10 },
    { type: 'error', message: 'oups' },
  ])
  expect(s.usage).toEqual({ used: 10, budget: 100, contextPct: 10 })
  expect(s.error).toBe('oups')
  expect(s.timeline).toHaveLength(1)
})

test("un patch d'artefact ne touche que sa section", () => {
  const s = run([
    { type: 'artifact_patch', section: 'Décisions', markdown: 'a' },
    { type: 'artifact_patch', section: 'Tests', markdown: 'b' },
    { type: 'artifact_patch', section: 'Décisions', markdown: 'a2' },
  ])
  expect(s.artifact).toEqual({ Décisions: 'a2', Tests: 'b' })
  expect(s.lastPatched).toBe('Décisions')
})

test("le passage de relais change l'agent actif", () => {
  const s = run([{ type: 'agent_handoff', from: 'sensei', to: 'reviewer' }])
  expect(s.persona).toBe('reviewer')
})

test("un relais vers un sous-agent s'affiche sans changer l'agent choisi", () => {
  const s = run([{ type: 'agent_handoff', from: 'sensei', to: 'explorateur', subAgent: true }])
  expect(s.persona).toBe('sensei')
  expect(s.timeline.at(-1)).toMatchObject({ kind: 'handoff', from: 'sensei', to: 'explorateur' })
})

test("une branche montre l'historique avant la bifurcation puis ses propres messages", () => {
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

test("bifurquer depuis un message inconnu ne change rien", () => {
  const s = reduce(initialState, { type: 'fork', branch: 'b1', fromId: 'zzz', id: 'x', text: 'y' })
  expect(s).toEqual(initialState)
})


test("une interruption périme les cartes en attente, qui ne peuvent plus être résolues", () => {
  let s = run([
    start,
    { type: 'confirm_request', requestId: 'c1', title: 'Supprimer ?', detail: 'build/', risk: 'high' },
    { type: 'question', requestId: 'q1', title: 'Cible', fields: [] },
    { type: 'done', turnId: 't1', interrupted: true },
  ])
  const kinds = s.timeline.flatMap((i) => (i.kind === 'confirm' || i.kind === 'question' ? [i.status] : []))
  expect(kinds).toEqual(['expired', 'expired'])
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'approved' })
  const c = s.timeline.find((i) => i.kind === 'confirm')
  expect(c && c.kind === 'confirm' && c.status).toBe('expired')
})

test("une demande déjà résolue ne change plus d'état", () => {
  let s = run([start, { type: 'confirm_request', requestId: 'c1', title: 't', detail: 'd', risk: 'low' }])
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'approved' })
  s = reduce(s, { type: 'resolve', requestId: 'c1', status: 'denied' })
  const c = s.timeline.find((i) => i.kind === 'confirm')
  expect(c && c.kind === 'confirm' && c.status).toBe('approved')
})

const texts = (st: UiState, b: string) => visibleTimeline(st, b).map((i) => (i.kind === 'user' ? i.text : i.kind))

test("éditer un ancien message depuis une variante n'affiche pas l'original", () => {
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

test("les éléments d'un tour restent dans la branche qui l'a lancé même si on change de vue", () => {
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

test("#44 : une conversation rouverte remplace l'affichage par son historique", () => {
  const s = run([
    { type: 'user_message', id: 'm1', text: 'avant' },
    { type: 'load_history', messages: [{ id: 'h0', role: 'user', text: 'q1' }, { id: 'h1', role: 'assistant', text: 'r1' }] },
  ])
  expect(s.timeline.map((i) => i.kind)).toEqual(['user', 'turn'])
  expect(s.timeline[0]).toMatchObject({ kind: 'user', id: 'h0', text: 'q1', branch: 'main' })
  expect(s.timeline[1]).toMatchObject({ kind: 'turn', turn: { text: 'r1', done: true } })
})

test("A7 : la question de l'exemple joint est gardée sur le tour", () => {
  const s = run([
    { type: 'turn_start', turnId: 't1', agent: 'sensei' },
    { type: 'fewshot', turnId: 't1', question: 'Comment lancer les tests ?' },
  ])
  expect(s.timeline.at(-1)).toMatchObject({ kind: 'turn', turn: { fewshot: 'Comment lancer les tests ?' } })
})
