/** Salutation selon l'heure locale. */
export function greeting(now: Date = new Date()): string {
  const h = now.getHours()
  if (h >= 5 && h < 12) return 'Bonjour'
  if (h >= 12 && h < 18) return 'Bon après-midi'
  if (h >= 18 && h < 23) return 'Bonsoir'
  return 'Bonne nuit'
}
