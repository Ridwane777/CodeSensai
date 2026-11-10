import { isEngineEvent } from '../src/contract/events'

test("accepts a valid event", () => {
  expect(isEngineEvent({ type: 'token', turnId: 't1', text: 'a' })).toBe(true)
})

test('rejects an unknown type and a non-object', () => {
  expect(isEngineEvent({ type: 'nope' })).toBe(false)
  expect(isEngineEvent(null)).toBe(false)
  expect(isEngineEvent('token')).toBe(false)
})
