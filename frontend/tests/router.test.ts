import { route, SUGGESTIONS } from '../src/engine/router'
import type { Step } from '../src/engine/scenarios/types'

test('route par mot-clé', () => {
  expect(route("Où vérifie-t-on qu'une session inconnue ne plante pas ?").id).toBe('search')
  expect(route('supprime le dossier build').id).toBe('risky')
})

test('ignore la casse et les accents', () => {
  expect(route('SUPPRIMÉ').id).toBe('risky')
})

test('texte inconnu : scénario de repli', () => {
  expect(route('blabla zzz').id).toBe('fallback')
})

test('chaque suggestion mène au scénario annoncé', () => {
  for (const s of SUGGESTIONS) expect(route(s.text).id).toBe(s.scenario)
})

test('les 9 étapes du fil rouge ont une suggestion', () => {
  expect(SUGGESTIONS.map((s) => s.scenario)).toEqual([
    'resume', 'search', 'fix', 'risky', 'secret', 'form', 'web', 'budget', 'wrapup',
  ])
})

test('tout scénario commence par turn_start et finit par done (ou attend une réponse avant)', () => {
  for (const s of [...SUGGESTIONS.map((x) => route(x.text)), route('zzz')]) {
    const first = s.steps[0]
    const last = s.steps.at(-1)
    expect('event' in first && first.event.type).toBe('turn_start')
    expect(last && 'event' in last && last.event.type).toBe('done')
  }
})

test("les waitFor ont un requestId émis juste avant", () => {
  for (const s of SUGGESTIONS.map((x) => route(x.text))) {
    s.steps.forEach((st: Step, i: number) => {
      if (!('waitFor' in st)) return
      const prev = s.steps[i - 1]
      expect('event' in prev && 'requestId' in prev.event && prev.event.requestId).toBe(st.requestId)
    })
  }
})
