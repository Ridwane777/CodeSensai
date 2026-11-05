export const PERSONA_LABEL: Record<string, string> = {
  sensei: 'CodeSensei',
  reviewer: 'Relecteur',
}

/** Les sous-agents du serveur réel (A2, ADR-0038) : affichés, mais pas sélectionnables. */
export const SUBAGENT_LABEL: Record<string, string> = {
  explorateur: 'Explorateur',
  developpeur: 'Développeur',
  relecteur: 'Relecteur',
  'sous-agent': 'Sous-agent',
}

/** Noms des personas du serveur réel (A5), retenus dès qu'il les envoie : sans eux,
 * l'en-tête d'une réponse en cours affichait l'identifiant (« assistant »). */
const REAL_LABEL: Record<string, string> = {}

export function rememberPersonaNames(list: { id: string; name: string }[]): void {
  for (const p of list) if (p.name) REAL_LABEL[p.id] = p.name
}

export const personaLabel = (id: string) => REAL_LABEL[id] ?? PERSONA_LABEL[id] ?? SUBAGENT_LABEL[id] ?? id
