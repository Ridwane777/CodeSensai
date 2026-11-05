export type FormField =
  | { id: string; kind: 'text'; label: string; placeholder?: string }
  | { id: string; kind: 'choice'; label: string; options: string[] }
  | { id: string; kind: 'toggle'; label: string }

export type EngineEvent =
  | { type: 'turn_start'; turnId: string; agent: string }
  | { type: 'token'; turnId: string; text: string }
  | { type: 'thought'; turnId: string; stepId: string; text: string }
  | { type: 'action'; turnId: string; stepId: string; tool: string; args: Record<string, unknown> }
  | { type: 'observation'; turnId: string; stepId: string; text: string; ms: number; ok: boolean }
  | { type: 'confirm_request'; requestId: string; title: string; detail: string; risk: 'low' | 'high' }
  | { type: 'question'; requestId: string; title: string; fields: FormField[] }
  | { type: 'usage'; used: number; budget: number; contextPct: number }
  | { type: 'compression'; savedTokens: number }
  | { type: 'artifact_patch'; section: string; markdown: string }
  | { type: 'rag_sources'; sources: { path: string; lines: string; score: number }[] }
  | { type: 'web_results'; results: { title: string; url: string }[] }
  | { type: 'guardrail'; kind: 'secret' | 'pii' | 'unsafe'; message: string }
  | { type: 'eval_score'; relevance: number; faithfulness: number }
  | { type: 'cache_hit'; similarity: number }
  /** `subAgent` : relais temporaire vers un sous-agent (A2) ; la persona choisie ne change pas. */
  | { type: 'agent_handoff'; from: string; to: string; subAgent?: boolean }
  /** A7 : l'exemple few-shot joint à la question de ce tour. */
  | { type: 'fewshot'; turnId: string; question: string }
  | { type: 'error'; message: string }
  | { type: 'done'; turnId: string; interrupted: boolean }

const TYPES = new Set<string>([
  'turn_start', 'token', 'thought', 'action', 'observation', 'confirm_request', 'question',
  'usage', 'compression', 'artifact_patch', 'rag_sources', 'web_results', 'guardrail',
  'eval_score', 'cache_hit', 'agent_handoff', 'fewshot', 'error', 'done',
])

export function isEngineEvent(x: unknown): x is EngineEvent {
  return typeof x === 'object' && x !== null && TYPES.has((x as { type?: string }).type ?? '')
}

export interface UserMessage {
  id: string
  text: string
}
