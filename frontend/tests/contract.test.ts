import { isEngineEvent } from '../src/contract/events'

test("accepte un événement valide", () => {
  expect(isEngineEvent({ type: 'token', turnId: 't1', text: 'a' })).toBe(true)
})

test('refuse un type inconnu et un non-objet', () => {
  expect(isEngineEvent({ type: 'nope' })).toBe(false)
  expect(isEngineEvent(null)).toBe(false)
  expect(isEngineEvent('token')).toBe(false)
})
