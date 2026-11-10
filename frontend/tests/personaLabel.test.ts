import { personaLabel, rememberPersonaNames } from '../src/ui/personas'

test("A5: a server persona is shown by its name, not its id", () => {
  // Real trial run on 2026-11-01: "assistant" shown at the top of the streaming answer.
  expect(personaLabel('assistant')).toBe('assistant')
  rememberPersonaNames([{ id: 'assistant', name: 'CodeSensai' }])
  expect(personaLabel('assistant')).toBe('CodeSensai')
  expect(personaLabel('explorateur')).toBe('Explorer')
})
