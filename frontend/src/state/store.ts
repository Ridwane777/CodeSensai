import type { EngineEvent, FormField } from '../contract/events'

export interface ReasoningStep {
  id: string
  thought?: string
  tool?: string
  args?: Record<string, unknown>
  observation?: string
  ms?: number
  ok?: boolean
}

export interface Turn {
  id: string
  agent: string
  text: string
  steps: ReasoningStep[]
  done: boolean
  interrupted: boolean
  /** A7 : la question de l'exemple few-shot joint, s'il y en a eu un. */
  fewshot?: string
}

type Item =
  | { kind: 'user'; id: string; text: string }
  | { kind: 'turn'; turn: Turn }
  | { kind: 'confirm'; requestId: string; title: string; detail: string; risk: 'low' | 'high'; status: 'pending' | 'approved' | 'denied' | 'expired' }
  | { kind: 'question'; requestId: string; title: string; fields: FormField[]; status: 'pending' | 'answered' | 'expired'; values?: Record<string, unknown> }
  | { kind: 'guardrail'; gKind: 'secret' | 'pii' | 'unsafe'; message: string }
  | { kind: 'handoff'; from: string; to: string }
  | { kind: 'compression'; savedTokens: number }
  | { kind: 'cache'; similarity: number }
  | { kind: 'eval'; relevance: number; faithfulness: number }

export type TimelineItem = Item & { branch: string }

export interface LogLine {
  id: string
  tool: string
  args: Record<string, unknown>
  ms?: number
  ok?: boolean
}

export interface Usage {
  used: number
  budget: number
  contextPct: number
}

export interface UiState {
  timeline: TimelineItem[]
  usage: Usage
  artifact: Record<string, string>
  lastPatched: string | null
  sources: { path: string; lines: string; score: number }[]
  web: { title: string; url: string }[]
  logs: LogLine[]
  thinking: boolean
  error: string | null
  persona: string
  /** Version du prompt système essayée dans cette conversation (A4, ADR-0055) ; null : l'active. */
  promptTrial: string | null
  activeBranch: string
  /** Branche du tour en cours : les éléments produits par le moteur y sont rangés, même si l'utilisateur change de vue. */
  runBranch: string
  branches: Record<string, { parent: string; forkIndex: number }>
}

export type Action =
  | EngineEvent
  | { type: 'user_message'; id: string; text: string }
  | { type: 'resolve'; requestId: string; status: 'approved' | 'denied' | 'answered'; values?: Record<string, unknown> }
  | { type: 'fork'; branch: string; fromId: string; id: string; text: string }
  | { type: 'switch_branch'; branch: string }
  | { type: 'clear_error' }
  /** Persona de la conversation lue ou changée sur le serveur réel (A5) : aucun relais affiché. */
  | { type: 'set_persona'; persona: string }
  | { type: 'set_prompt_trial'; version: string | null }
  /** Conversation rouverte (#44) : l'affichage repart de son historique. */
  | { type: 'load_history'; messages: { id: string; role: 'user' | 'assistant'; text: string }[] }

export const initialState: UiState = {
  timeline: [],
  usage: { used: 0, budget: 8192, contextPct: 0 },
  artifact: {},
  lastPatched: null,
  sources: [],
  web: [],
  logs: [],
  thinking: false,
  error: null,
  persona: 'sensei',
  promptTrial: null,
  activeBranch: 'main',
  runBranch: 'main',
  branches: {},
}

const push = (s: UiState, item: Item, branch: string = s.runBranch): UiState => ({
  ...s,
  timeline: [...s.timeline, { ...item, branch } as TimelineItem],
})

function mapTurn(s: UiState, turnId: string, fn: (t: Turn) => Turn): UiState {
  return {
    ...s,
    timeline: s.timeline.map((i) => (i.kind === 'turn' && i.turn.id === turnId ? { ...i, turn: fn(i.turn) } : i)),
  }
}

function upsertStep(t: Turn, id: string, patch: Partial<ReasoningStep>): Turn {
  const exists = t.steps.some((st) => st.id === id)
  const steps = exists
    ? t.steps.map((st) => (st.id === id ? { ...st, ...patch } : st))
    : [...t.steps, { id, ...patch }]
  return { ...t, steps }
}

export function reduce(s: UiState, a: Action): UiState {
  switch (a.type) {
    case 'user_message':
      return push({ ...s, error: null, runBranch: s.activeBranch }, { kind: 'user', id: a.id, text: a.text }, s.activeBranch)
    case 'turn_start':
      return push(
        { ...s, thinking: true },
        { kind: 'turn', turn: { id: a.turnId, agent: a.agent, text: '', steps: [], done: false, interrupted: false } },
      )
    case 'token':
      return mapTurn(s, a.turnId, (t) => ({ ...t, text: t.text + a.text }))
    case 'thought':
      return mapTurn(s, a.turnId, (t) => upsertStep(t, a.stepId, { thought: a.text }))
    case 'action': {
      const next = mapTurn(s, a.turnId, (t) => upsertStep(t, a.stepId, { tool: a.tool, args: a.args }))
      return { ...next, logs: [...next.logs, { id: `${a.turnId}/${a.stepId}`, tool: a.tool, args: a.args }] }
    }
    case 'observation': {
      const next = mapTurn(s, a.turnId, (t) =>
        upsertStep(t, a.stepId, { observation: a.text, ms: a.ms, ok: a.ok }),
      )
      const id = `${a.turnId}/${a.stepId}`
      return { ...next, logs: next.logs.map((l) => (l.id === id ? { ...l, ms: a.ms, ok: a.ok } : l)) }
    }
    case 'confirm_request':
      return push(s, { kind: 'confirm', requestId: a.requestId, title: a.title, detail: a.detail, risk: a.risk, status: 'pending' })
    case 'question':
      return push(s, { kind: 'question', requestId: a.requestId, title: a.title, fields: a.fields, status: 'pending' })
    case 'resolve':
      return {
        ...s,
        timeline: s.timeline.map((i) => {
          if (i.kind === 'confirm' && i.requestId === a.requestId && i.status === 'pending' && a.status !== 'answered')
            return { ...i, status: a.status }
          if (i.kind === 'question' && i.requestId === a.requestId && i.status === 'pending' && a.status === 'answered')
            return { ...i, status: 'answered', values: a.values }
          return i
        }),
      }
    case 'usage':
      return { ...s, usage: { used: a.used, budget: a.budget, contextPct: a.contextPct } }
    case 'compression':
      return push(s, { kind: 'compression', savedTokens: a.savedTokens })
    case 'artifact_patch':
      return { ...s, artifact: { ...s.artifact, [a.section]: a.markdown }, lastPatched: a.section }
    case 'rag_sources':
      return { ...s, sources: a.sources }
    case 'web_results':
      return { ...s, web: a.results }
    case 'guardrail':
      return push(s, { kind: 'guardrail', gKind: a.kind, message: a.message })
    case 'eval_score':
      return push(s, { kind: 'eval', relevance: a.relevance, faithfulness: a.faithfulness })
    case 'fewshot':
      return mapTurn(s, a.turnId, (t) => ({ ...t, fewshot: a.question }))
    case 'cache_hit':
      return push(s, { kind: 'cache', similarity: a.similarity })
    case 'agent_handoff':
      return push(a.subAgent ? s : { ...s, persona: a.to }, { kind: 'handoff', from: a.from, to: a.to })
    case 'error':
      return { ...s, error: a.message }
    case 'set_persona':
      return { ...s, persona: a.persona }
    case 'set_prompt_trial':
      return { ...s, promptTrial: a.version }
    case 'load_history': {
      let next: UiState = { ...initialState, persona: s.persona }
      for (const m of a.messages) {
        next =
          m.role === 'user'
            ? push(next, { kind: 'user', id: m.id, text: m.text }, 'main')
            : push(next, { kind: 'turn', turn: { id: `${m.id}-r`, agent: s.persona, text: m.text, steps: [], done: true, interrupted: false } }, 'main')
      }
      return next
    }
    case 'clear_error':
      return { ...s, error: null }
    case 'done': {
      const ended = mapTurn({ ...s, thinking: false }, a.turnId, (t) => ({ ...t, done: true, interrupted: a.interrupted }))
      // Une fois le tour fini, plus personne n'attend de réponse : les cartes encore ouvertes sont périmées.
      return {
        ...ended,
        timeline: ended.timeline.map((i) =>
          (i.kind === 'confirm' || i.kind === 'question') && i.status === 'pending' ? { ...i, status: 'expired' } : i,
        ),
      }
    }
    case 'fork': {
      const idx = s.timeline.findIndex((i) => i.kind === 'user' && i.id === a.fromId)
      if (idx < 0) return s
      const base: UiState = {
        ...s,
        branches: { ...s.branches, [a.branch]: { parent: s.activeBranch, forkIndex: idx } },
        activeBranch: a.branch,
        runBranch: a.branch,
      }
      return push(base, { kind: 'user', id: a.id, text: a.text }, a.branch)
    }
    case 'switch_branch':
      return s.branches[a.branch] || a.branch === 'main' ? { ...s, activeBranch: a.branch } : s
  }
}

/** Ce que l'utilisateur voit pour une branche : l'historique de ses ancêtres jusqu'à la bifurcation, puis ses propres éléments. */
export function visibleTimeline(s: UiState, branch: string): TimelineItem[] {
  const chain: TimelineItem[][] = []
  let cur: string | undefined = branch
  let limit = Infinity
  while (cur) {
    const mine = s.timeline.filter((item, idx) => item.branch === cur && idx < limit)
    chain.unshift(mine)
    const info: { parent: string; forkIndex: number } | undefined = s.branches[cur]
    if (!info) break
    limit = Math.min(limit, info.forkIndex)
    cur = info.parent
  }
  return chain.flat()
}

export type ConfirmItem = Extract<TimelineItem, { kind: 'confirm' }>
export type QuestionItem = Extract<TimelineItem, { kind: 'question' }>
export type GuardrailItem = Extract<TimelineItem, { kind: 'guardrail' }>
