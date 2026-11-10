export const PERSONA_LABEL: Record<string, string> = {
  sensei: 'CodeSensai',
  reviewer: 'Reviewer',
}

/** The real server sub-agents (A2, ADR-0038): shown, but not selectable. */
export const SUBAGENT_LABEL: Record<string, string> = {
  explorateur: 'Explorer',
  developpeur: 'Developer',
  relecteur: 'Reviewer',
  'sous-agent': 'Sub-agent',
}

/** Real server persona names (A5), kept as soon as it sends them: without them,
 * the header of an answer in progress showed the id ("assistant"). */
const REAL_LABEL: Record<string, string> = {}

export function rememberPersonaNames(list: { id: string; name: string }[]): void {
  for (const p of list) if (p.name) REAL_LABEL[p.id] = p.name
}

export const personaLabel = (id: string) => REAL_LABEL[id] ?? PERSONA_LABEL[id] ?? SUBAGENT_LABEL[id] ?? id
