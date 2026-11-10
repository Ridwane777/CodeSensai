import { route, SUGGESTIONS } from '../src/engine/router'
import type { Step } from '../src/engine/scenarios/types'

// Inputs stay French on purpose: the demo router matches French keywords.
test('routes by keyword', () => {
  expect(route("Où vérifie-t-on qu'une session inconnue ne plante pas ?").id).toBe('search')
  expect(route('supprime le dossier build').id).toBe('risky')
})

test('ignores case and accents', () => {
  expect(route('SUPPRIMÉ').id).toBe('risky')
})

test('unknown text: fallback scenario', () => {
  expect(route('blabla zzz').id).toBe('fallback')
})

test('each suggestion leads to its announced scenario', () => {
  for (const s of SUGGESTIONS) expect(route(s.text).id).toBe(s.scenario)
})

test('the 9 steps of the walkthrough each have a suggestion', () => {
  expect(SUGGESTIONS.map((s) => s.scenario)).toEqual([
    'resume', 'search', 'fix', 'risky', 'secret', 'form', 'web', 'budget', 'wrapup',
  ])
})

test('every scenario starts with turn_start and ends with done (or waits for an answer first)', () => {
  for (const s of [...SUGGESTIONS.map((x) => route(x.text)), route('zzz')]) {
    const first = s.steps[0]
    const last = s.steps.at(-1)
    expect('event' in first && first.event.type).toBe('turn_start')
    expect(last && 'event' in last && last.event.type).toBe('done')
  }
})

test("each waitFor has a requestId emitted just before", () => {
  for (const s of SUGGESTIONS.map((x) => route(x.text))) {
    s.steps.forEach((st: Step, i: number) => {
      if (!('waitFor' in st)) return
      const prev = s.steps[i - 1]
      expect('event' in prev && 'requestId' in prev.event && prev.event.requestId).toBe(st.requestId)
    })
  }
})
