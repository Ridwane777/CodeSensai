import { visibleTimeline, type UiState } from '../state/store'
import { personaLabel } from '../ui/personas'

export function toMarkdown(state: UiState): string {
  const out: string[] = ['# CodeSensai session', '']
  const items = visibleTimeline(state, state.activeBranch)
  const lines = items.flatMap((i) => {
    if (i.kind === 'user') return [`**Vous** : ${i.text}`, '']
    if (i.kind !== 'turn') return []
    const steps = i.turn.steps.map(
      (s) => `- ${s.tool ?? 'thought'}${s.observation ? ` → ${s.observation}` : ''}${s.thought ? ` (${s.thought})` : ''}`,
    )
    return [`**${personaLabel(i.turn.agent)}** : ${i.turn.text}`, ...(steps.length ? ['', ...steps] : []), '']
  })
  out.push(...(lines.length ? lines : ['Aucun message.', '']))
  for (const [name, md] of Object.entries(state.artifact)) out.push(`## ${name}`, '', md, '')
  return out.join('\n').trimEnd() + '\n'
}
