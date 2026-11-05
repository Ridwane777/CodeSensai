import { personaLabel, rememberPersonaNames } from '../src/ui/personas'

test("A5 : une persona du serveur s'affiche par son nom, pas son identifiant", () => {
  // Essai réel du 2026-11-01 : « assistant » en tête de la réponse en cours.
  expect(personaLabel('assistant')).toBe('assistant')
  rememberPersonaNames([{ id: 'assistant', name: 'Sensai' }])
  expect(personaLabel('assistant')).toBe('Sensai')
  expect(personaLabel('explorateur')).toBe('Explorateur')
})
