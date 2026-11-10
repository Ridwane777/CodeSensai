/**
 * Translates the real server stream (Workstream A events, `to_wire`, plus the ADR-0024
 * extensions) into the UI display model (ADR-0035, web-api-alignment.md §4).
 *
 * One instance per turn. The Workstream A stream has no turn start and no step id: the
 * adapter creates them. Each `thought` opens a step; a `tool_call` attaches to it if the step
 * has no tool yet, otherwise it opens a new one; the `tool_return` finds its step by the call
 * id, and its duration is measured here.
 */
import type { EngineEvent, FormField } from '../contract/events'

const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v))
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const obj = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}

/** Fields of a server question (X4, ADR-0046); a malformed field is dropped. */
export function toFields(raw: unknown): FormField[] {
  if (!Array.isArray(raw)) return []
  const out: FormField[] = []
  for (const item of raw) {
    const f = obj(item)
    const id = str(f.id)
    const label = str(f.label)
    if (!id || !label) continue
    if (f.kind === 'choice') {
      const options = Array.isArray(f.options) ? f.options.map(str).filter(Boolean) : []
      if (options.length >= 2) out.push({ id, kind: 'choice', label, options })
    } else if (f.kind === 'toggle') out.push({ id, kind: 'toggle', label })
    else out.push({ id, kind: 'text', label, ...(f.placeholder ? { placeholder: str(f.placeholder) } : {}) })
  }
  return out
}

/** What the user must read before accepting, as in the CLI (`describe_request`). */
export function describeConfirm(tool: string, risk: string, summary: string, args: Record<string, unknown>) {
  const title = `The agent wants to use "${tool}" (risk: ${risk || 'unknown'})`
  const detail =
    summary && !summary.startsWith(`${tool}(`)
      ? summary
      : Object.entries(args)
          .map(([k, v]) => `${k} = ${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join('\n')
  return { title, detail: detail || '(no details)' }
}

export class WireAdapter {
  private steps = 0
  /** Step opened by a `thought` and still without a tool. */
  private openStep: string | null = null
  private calls = new Map<string, { stepId: string; started: number }>()
  /** The model speaks again after a tool: new paragraph, not a glued sentence. */
  private hadText = false
  private breakBeforeText = false
  /** Reason of the received `done`: the engine uses it to count saved messages. */
  doneReason: string | null = null

  constructor(
    readonly turnId: string,
    private agent: string,
    private now: () => number = () => Date.now(),
  ) {}

  start(): EngineEvent {
    return { type: 'turn_start', turnId: this.turnId, agent: this.agent }
  }

  private newStep(): string {
    this.steps += 1
    return `s${this.steps}`
  }

  push(raw: unknown): EngineEvent[] {
    const e = obj(raw)
    const turnId = this.turnId
    switch (e.type) {
      case 'token': {
        let text = str(e.text)
        if (!text) return []
        if (this.breakBeforeText && this.hadText) text = `\n\n${text.replace(/^\s+/, '')}`
        this.breakBeforeText = false
        this.hadText = true
        return [{ type: 'token', turnId, text }]
      }
      case 'thought': {
        const stepId = this.newStep()
        this.openStep = stepId
        return [{ type: 'thought', turnId, stepId, text: str(e.text) }]
      }
      case 'tool_call': {
        this.breakBeforeText = true
        const stepId = this.openStep ?? this.newStep()
        this.openStep = null
        this.calls.set(str(e.id), { stepId, started: this.now() })
        return [{ type: 'action', turnId, stepId, tool: str(e.name), args: obj(e.arguments) }]
      }
      case 'tool_return': {
        const call = this.calls.get(str(e.id))
        this.calls.delete(str(e.id))
        const stepId = call?.stepId ?? this.newStep()
        const ms = call ? Math.max(0, Math.round(this.now() - call.started)) : 0
        return [{ type: 'observation', turnId, stepId, text: str(e.content), ms, ok: e.ok === true }]
      }
      case 'confirm_request': {
        const tool = str(e.tool)
        const risk = str(e.risk)
        const { title, detail } = describeConfirm(tool, risk, str(e.summary), obj(e.arguments))
        const requestId = str(e.confirm_id ?? e.id)
        if (!requestId) return []
        return [{ type: 'confirm_request', requestId, title, detail, risk: risk === 'read' ? 'low' : 'high' }]
      }
      case 'question': {
        const requestId = str(e.question_id)
        const fields = toFields(e.fields)
        if (!requestId || fields.length === 0) return []
        return [{ type: 'question', requestId, title: str(e.title), fields }]
      }
      case 'web_results': {
        // web_search results reread by the server (US-T3-1): http(s) links only.
        const list = Array.isArray(e.results) ? e.results : []
        const results = list
          .map((r) => {
            const o = obj(r)
            return { title: str(o.title), url: str(o.url) }
          })
          .filter((r) => /^https?:\/\//.test(r.url))
        return results.length ? [{ type: 'web_results', results }] : []
      }
      case 'rag_sources': {
        const list = Array.isArray(e.sources) ? e.sources : []
        const sources = list.map((s) => {
          const o = obj(s)
          return { path: str(o.path), lines: str(o.lines), score: num(o.score) }
        })
        return [{ type: 'rag_sources', sources }]
      }
      case 'agent_handoff': {
        // "main" is the main agent: keep the displayed persona name.
        const name = (v: unknown) => (str(v) === 'main' ? this.agent : str(v))
        const from = name(e.from)
        const to = name(e.to)
        if (!from || !to) return []
        return [{ type: 'agent_handoff', from, to, subAgent: true }]
      }
      case 'usage': {
        // M2: ESTIMATED tokens sent to the model, against the num_ctx window.
        const used = num(e.used)
        const window = num(e.num_ctx)
        const budget = num(e.budget)
        if (!window || !budget) return []
        return [{ type: 'usage', used, budget, contextPct: Math.min(100, Math.round((used / window) * 100)) }]
      }
      case 'compression':
        return [{ type: 'compression', savedTokens: num(e.saved_tokens) }]
      case 'artifact_patch': {
        const section = str(e.section)
        return section ? [{ type: 'artifact_patch', section, markdown: str(e.markdown) }] : []
      }
      case 'subagent_step': {
        // A2: a sub-agent tool, shown as a turn step, prefixed by its role.
        const stepId = this.newStep()
        const tool = `${str(e.agent)} › ${str(e.tool)}`
        return [
          { type: 'action', turnId, stepId, tool, args: obj(e.arguments) },
          { type: 'observation', turnId, stepId, text: str(e.content), ms: num(e.duration_ms), ok: e.ok === true },
        ]
      }
      case 'fewshot': {
        const question = str(e.question)
        return question ? [{ type: 'fewshot', turnId, question }] : []
      }
      case 'cache_hit':
        return [{ type: 'cache_hit', similarity: num(e.similarity) }]
      case 'guardrail': {
        const kind = e.kind === 'secret' || e.kind === 'pii' ? e.kind : 'unsafe'
        return [{ type: 'guardrail', kind, message: str(e.message) }]
      }
      case 'error':
        return [{ type: 'error', message: str(e.message) || 'Unknown error' }]
      case 'done': {
        const reason = str(e.reason)
        this.doneReason = reason
        const out: EngineEvent[] = []
        if (reason === 'max_iterations')
          out.push({ type: 'error', message: 'Stopped: maximum number of steps reached without a final answer.' })
        out.push({ type: 'done', turnId, interrupted: reason === 'interrupted' })
        return out
      }
      default:
        return [] // unknown type: ignored, never an exception
    }
  }
}
