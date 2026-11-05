import { greeting } from '../src/features/chat/greeting'

const at = (h: number) => new Date(2026, 9, 13, h, 0, 0)

test.each([
  [6, 'Bonjour'],
  [11, 'Bonjour'],
  [12, 'Bon après-midi'],
  [17, 'Bon après-midi'],
  [18, 'Bonsoir'],
  [22, 'Bonsoir'],
  [23, 'Bonne nuit'],
  [3, 'Bonne nuit'],
])('à %ih, la salutation est « %s »', (h, expected) => {
  expect(greeting(at(h))).toBe(expected)
})
