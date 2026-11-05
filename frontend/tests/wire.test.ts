import { describeConfirm, WireAdapter } from '../src/engine/wire'

function adapter() {
  let t = 1000
  const a = new WireAdapter('t1', 'sensei', () => t)
  return { a, tick: (ms: number) => (t += ms) }
}

test('début de tour et texte', () => {
  const { a } = adapter()
  expect(a.start()).toEqual({ type: 'turn_start', turnId: 't1', agent: 'sensei' })
  expect(a.push({ type: 'token', text: 'Bonjour' })).toEqual([{ type: 'token', turnId: 't1', text: 'Bonjour' }])
})

test("une pensée ouvre une étape, l'appel d'outil s'y rattache, le retour mesure la durée", () => {
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

test('un second appel sans pensée ouvre sa propre étape', () => {
  const { a } = adapter()
  a.push({ type: 'tool_call', id: 'c1', name: 'read_file', arguments: {} })
  const [second] = a.push({ type: 'tool_call', id: 'c2', name: 'run_code', arguments: {} })
  expect(second).toMatchObject({ stepId: 's2' })
  expect(a.push({ type: 'tool_return', id: 'c2', ok: false, content: 'Erreur' })[0]).toMatchObject({ stepId: 's2', ok: false })
})

test('un retour sans appel connu ne casse rien', () => {
  const { a } = adapter()
  expect(a.push({ type: 'tool_return', id: 'zz', ok: true, content: 'r' })[0]).toMatchObject({ type: 'observation', stepId: 's1', ms: 0 })
})

test("la confirmation reprend le résumé de l'outil, ou les arguments en clair", () => {
  const { a } = adapter()
  const [withDiff] = a.push({ type: 'confirm_request', id: 'x', confirm_id: 'C1', tool: 'write_file', risk: 'write', summary: '--- a.py\n+++ a.py', arguments: { path: 'a.py' } })
  expect(withDiff).toEqual({
    type: 'confirm_request', requestId: 'C1', title: "L'agent veut utiliser « write_file » (risque : write)", detail: '--- a.py\n+++ a.py', risk: 'high',
  })
  const [plain] = a.push({ type: 'confirm_request', id: 'C2', tool: 'run_code', risk: 'execute', summary: 'run_code({"code": "print(1)"})', arguments: { code: 'print(1)' } })
  expect(plain).toMatchObject({ requestId: 'C2', detail: 'code = print(1)', risk: 'high' })
})

test('une confirmation sans identifiant est ignorée', () => {
  const { a } = adapter()
  expect(a.push({ type: 'confirm_request', tool: 'write_file' })).toEqual([])
})

test('describeConfirm sans argument ni résumé', () => {
  expect(describeConfirm('x', '', '', {})).toEqual({ title: "L'agent veut utiliser « x » (risque : inconnu)", detail: '(aucun détail)' })
})

test('les extensions du serveur passent : sources, cache, garde-fou', () => {
  const { a } = adapter()
  expect(a.push({ type: 'rag_sources', sources: [{ path: 'a.md', lines: '1-2', score: 0.8 }, 'cassé'] })).toEqual([
    { type: 'rag_sources', sources: [{ path: 'a.md', lines: '1-2', score: 0.8 }, { path: '', lines: '', score: 0 }] },
  ])
  expect(a.push({ type: 'cache_hit', similarity: 0.95, question: 'q' })).toEqual([{ type: 'cache_hit', similarity: 0.95 }])
  expect(a.push({ type: 'guardrail', kind: 'bizarre', message: 'bloqué' })).toEqual([{ type: 'guardrail', kind: 'unsafe', message: 'bloqué' }])
})

test("done : interruption, limite d'étapes, raison retenue", () => {
  const { a } = adapter()
  expect(a.push({ type: 'done', reason: 'interrupted' })).toEqual([{ type: 'done', turnId: 't1', interrupted: true }])
  const b = new WireAdapter('t2', 'sensei')
  expect(b.push({ type: 'done', reason: 'max_iterations' }).map((e) => e.type)).toEqual(['error', 'done'])
  expect(b.doneReason).toBe('max_iterations')
})

test('les données mal formées sont ignorées sans exception', () => {
  const { a } = adapter()
  expect(a.push(null)).toEqual([])
  expect(a.push('texte')).toEqual([])
  expect(a.push({ type: 'usage', prompt_tokens: 3 })).toEqual([])
  expect(a.push({ type: 'error' })).toEqual([{ type: 'error', message: 'Erreur inconnue' }])
  expect(a.push({ type: 'tool_call', id: 1, name: null, arguments: [1] })[0]).toMatchObject({ tool: '', args: {} })
})

test("le texte repris après un outil commence un nouveau paragraphe", () => {
  const { a } = adapter()
  a.push({ type: 'token', text: 'Je crée le fichier.' })
  a.push({ type: 'tool_call', id: 'c1', name: 'write_file', arguments: {} })
  a.push({ type: 'tool_return', id: 'c1', ok: true, content: 'ok' })
  expect(a.push({ type: 'token', text: "J'ai créé" })).toEqual([{ type: 'token', turnId: 't1', text: "\n\nJ'ai créé" }])
  expect(a.push({ type: 'token', text: ' le fichier.' })[0]).toMatchObject({ text: ' le fichier.' })
})

test("sans texte avant l'outil, pas de saut de paragraphe en tête", () => {
  const { a } = adapter()
  a.push({ type: 'tool_call', id: 'c1', name: 'read_file', arguments: {} })
  expect(a.push({ type: 'token', text: 'Voici' })[0]).toMatchObject({ text: 'Voici' })
  expect(a.push({ type: 'token', text: '' })).toEqual([])
})

test('une question du serveur devient un formulaire ; les champs mal formés sont écartés', () => {
  const { a } = adapter()
  const out = a.push({
    type: 'question', question_id: 'Q1', title: 'Précisions',
    fields: [
      { id: 'nom', kind: 'text', label: 'Nom', placeholder: 'ex. outils' },
      { id: 'style', kind: 'choice', label: 'Style', options: ['pytest', 'unittest'] },
      { id: 'docs', kind: 'toggle', label: 'Doc ?' },
      { id: 'seul', kind: 'choice', label: 'Un seul choix', options: ['x'] },
      { kind: 'text', label: 'sans id' },
    ],
  })
  expect(out).toEqual([{
    type: 'question', requestId: 'Q1', title: 'Précisions',
    fields: [
      { id: 'nom', kind: 'text', label: 'Nom', placeholder: 'ex. outils' },
      { id: 'style', kind: 'choice', label: 'Style', options: ['pytest', 'unittest'] },
      { id: 'docs', kind: 'toggle', label: 'Doc ?' },
    ],
  }])
  expect(a.push({ type: 'question', question_id: 'Q2', title: 'vide', fields: [] })).toEqual([])
})

test("un relais du serveur garde le nom de la persona pour l'agent principal", () => {
  const { a } = adapter()
  expect(a.push({ type: 'agent_handoff', from: 'main', to: 'explorateur' })).toEqual([
    { type: 'agent_handoff', from: 'sensei', to: 'explorateur', subAgent: true },
  ])
  expect(a.push({ type: 'agent_handoff', from: 'relecteur', to: 'main' })[0]).toMatchObject({ from: 'relecteur', to: 'sensei' })
  expect(a.push({ type: 'agent_handoff', from: 'main' })).toEqual([])
})

test("l'exemple few-shot joint (A7) est rattaché au tour", () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({ type: 'fewshot', question: 'Comment lancer les tests ?' })).toEqual([
    { type: 'fewshot', turnId: 't1', question: 'Comment lancer les tests ?' },
  ])
  expect(a.push({ type: 'fewshot' })).toEqual([])
})

test('les résultats de recherche web du serveur arrivent dans l’onglet Sources, liens http(s) seulement', () => {
  const a = new WireAdapter('t1', 'sensei')
  expect(a.push({
    type: 'web_results',
    results: [{ title: 'Python 3.15.2', url: 'https://www.python.org/' }, { title: 'piège', url: 'javascript:alert(1)' }],
  })).toEqual([{ type: 'web_results', results: [{ title: 'Python 3.15.2', url: 'https://www.python.org/' }] }])
  expect(a.push({ type: 'web_results', results: [] })).toEqual([])
})
