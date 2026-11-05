/**
 * Traduit le flux du serveur réel (événements du lot A, `to_wire`, plus les extensions de
 * l'ADR-0024) vers le modèle d'affichage de l'interface (ADR-0035, web-api-alignement.md §4).
 *
 * Une instance par tour. Le flux du lot A n'a ni début de tour ni identifiant d'étape :
 * l'adaptateur les crée. Chaque `thought` ouvre une étape ; un `tool_call` s'y rattache si
 * l'étape n'a pas encore d'outil, sinon il en ouvre une ; le `tool_return` retrouve son
 * étape par l'identifiant de l'appel, et sa durée est mesurée ici.
 */
import type { EngineEvent, FormField } from '../contract/events'

const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v))
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const obj = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}

/** Champs d'une question du serveur (X4, ADR-0046) ; un champ mal formé est écarté. */
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

/** Ce que l'utilisateur doit lire avant d'accepter, comme dans le CLI (`describe_request`). */
export function describeConfirm(tool: string, risk: string, summary: string, args: Record<string, unknown>) {
  const title = `L'agent veut utiliser « ${tool} » (risque : ${risk || 'inconnu'})`
  const detail =
    summary && !summary.startsWith(`${tool}(`)
      ? summary
      : Object.entries(args)
          .map(([k, v]) => `${k} = ${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join('\n')
  return { title, detail: detail || '(aucun détail)' }
}

export class WireAdapter {
  private steps = 0
  /** Étape ouverte par un `thought` et encore sans outil. */
  private openStep: string | null = null
  private calls = new Map<string, { stepId: string; started: number }>()
  /** Le modèle reprend la parole après un outil : nouveau paragraphe, pas une phrase collée. */
  private hadText = false
  private breakBeforeText = false
  /** Raison du `done` reçu : le moteur s'en sert pour compter les messages enregistrés. */
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
        // Résultats de web_search relus par le serveur (US-T3-1) : liens http(s) seulement.
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
        // « main » est l'agent principal : on garde le nom de la persona affichée.
        const name = (v: unknown) => (str(v) === 'main' ? this.agent : str(v))
        const from = name(e.from)
        const to = name(e.to)
        if (!from || !to) return []
        return [{ type: 'agent_handoff', from, to, subAgent: true }]
      }
      case 'usage': {
        // M2 : tokens ESTIMÉS de ce qui part au modèle, face à la fenêtre num_ctx.
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
        // A2 : un outil du sous-agent, montré comme une étape du tour, préfixée par son rôle.
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
        return [{ type: 'error', message: str(e.message) || 'Erreur inconnue' }]
      case 'done': {
        const reason = str(e.reason)
        this.doneReason = reason
        const out: EngineEvent[] = []
        if (reason === 'max_iterations')
          out.push({ type: 'error', message: "Arrêt : nombre maximal d'étapes atteint sans réponse finale." })
        out.push({ type: 'done', turnId, interrupted: reason === 'interrupted' })
        return out
      }
      default:
        return [] // type inconnu : ignoré, jamais une exception
    }
  }
}
