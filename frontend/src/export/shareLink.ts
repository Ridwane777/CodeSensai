import type { UiState } from '../state/store'
import { toJson } from './toJson'

/** Lien simulé : domaine factice (.example, réservé), aucune page publique n'est créée. */
export function shareLink(state: UiState): string {
  let h = 0x811c9dc5
  for (const c of toJson(state)) h = Math.imul(h ^ c.charCodeAt(0), 0x01000193) >>> 0
  return `https://codesensei.example/s/${h.toString(16).padStart(8, '0')}`
}
