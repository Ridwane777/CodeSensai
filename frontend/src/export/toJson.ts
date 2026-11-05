import { visibleTimeline, type ReasoningStep, type UiState } from '../state/store'

type ExportedMessage =
  | { role: 'user'; id: string; text: string }
  | { role: 'assistant'; agent: string; text: string; steps: ReasoningStep[]; interrupted: boolean }

export function toJson(state: UiState): string {
  const messages = visibleTimeline(state, state.activeBranch).flatMap((i): ExportedMessage[] => {
    if (i.kind === 'user') return [{ role: 'user', id: i.id, text: i.text }]
    if (i.kind === 'turn')
      return [{ role: 'assistant', agent: i.turn.agent, text: i.turn.text, steps: i.turn.steps, interrupted: i.turn.interrupted }]
    return []
  })
  return JSON.stringify({ version: 1, branch: state.activeBranch, messages, artifact: state.artifact }, null, 2)
}
