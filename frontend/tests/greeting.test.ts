import { greeting } from '../src/features/chat/greeting'

const at = (h: number) => new Date(2026, 9, 13, h, 0, 0)

test.each([
  [6, 'Good morning'],
  [11, 'Good morning'],
  [12, 'Good afternoon'],
  [17, 'Good afternoon'],
  [18, 'Good evening'],
  [22, 'Good evening'],
  [23, 'Good night'],
  [3, 'Good night'],
])('at %ih, the greeting is "%s"', (h, expected) => {
  expect(greeting(at(h))).toBe(expected)
})
