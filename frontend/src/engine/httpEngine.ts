/**
 * Real engine: talks to the `sensai-web` server (ADR-0035), same interface as MockEngine.
 *
 * - A turn = `POST /api/sessions/{id}/messages`, which answers with an SSE stream read with `fetch`
 *   (ADR-0022); the Workstream A stream is translated by `WireAdapter`.
 * - Every request carries `Authorization: Bearer <token>` (ADR-0023).
 * - A branch (editing a message, X2) is a new server-side session, created by
 *   `POST /fork` with the history up to the edited message (ADR-0024).
 * - Never throws: a failure becomes an `error` event, and the turn ends with `done`.
 */
import type {
  AdversarialRun,
  BranchId,
  Engine,
  Evaluation,
  FewshotInfo,
  JournalMetrics,
  JournalTurn,
  PastMessage,
  PersonaInfo,
  ProjectFact,
  PromptEntry,
  PromptTrial,
  ScheduledTask,
  SessionSummary,
  SharedLink,
  UserProfile,
} from '../contract/engine'
import type { EngineEvent, UserMessage } from '../contract/events'
import { rememberPersonaNames } from '../ui/personas'
import { WireAdapter } from './wire'

/** Reassembles `data: {...}` events split arbitrarily across received chunks. */
export class SseParser {
  private buffer = ''

  push(chunk: string): Record<string, unknown>[] {
    this.buffer += chunk.replace(/\r\n/g, '\n')
    const parts = this.buffer.split('\n\n')
    this.buffer = parts.pop() ?? ''
    const events: Record<string, unknown>[] = []
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (!line.startsWith('data:')) continue
        try {
          const parsed: unknown = JSON.parse(line.slice(5).trim())
          if (parsed && typeof parsed === 'object' && typeof (parsed as { type?: unknown }).type === 'string')
            events.push(parsed as Record<string, unknown>)
        } catch {
          /* invalid line: ignored */
        }
      }
    }
    return events
  }
}

export interface HttpEngineOptions {
  token: string
  /** '': same origin (the UI served by sensai-web). */
  baseUrl?: string
  fetchFn?: typeof fetch
  now?: () => number
  /** Called when the server rejects the token: the UI asks for it again. */
  onUnauthorized?: () => void
  /** Time given to the server to finish an interrupted turn before cutting the stream. */
  interruptGraceMs?: number
}

interface Branch {
  sessionId: string | null
  /** Messages already saved server-side in this branch. */
  persisted: number
}

interface Turn {
  adapter: WireAdapter
  ended: boolean
  controller: AbortController
}

type Listener = (e: EngineEvent) => void

function toPersona(p: Record<string, unknown>): PersonaInfo {
  return {
    id: String(p.id),
    name: String(p.name),
    role: String(p.role ?? ''),
    tone: String(p.tone ?? ''),
    scope: String(p.scope ?? ''),
    toolsDisabled: Array.isArray(p.tools_disabled) ? p.tools_disabled.map(String) : [],
    isDefault: Boolean(p.default),
  }
}

const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const nOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' ? (v as Record<string, unknown>) : {})
const list = (v: unknown): Record<string, unknown>[] => (Array.isArray(v) ? v.map(rec) : [])

function toAdversarial(b: Record<string, unknown>): AdversarialRun {
  const s = rec(b.summary)
  return {
    cases: list(b.cases).map((c) => ({
      id: String(c.id ?? ''),
      category: String(c.category ?? ''),
      attempt: String(c.attempt ?? ''),
      expected: String(c.expected ?? ''),
      observed: String(c.observed ?? ''),
      verdict: String(c.verdict ?? ''),
      detail: String(c.detail ?? ''),
    })),
    summary: { total: n(s.total), ok: n(s.ok), knownGaps: n(s.known_gaps), regressions: n(s.regressions), fixed: n(s.fixed), skipped: n(s.skipped) },
    ranAt: typeof b.ran_at === 'string' ? b.ran_at : null,
    source: b.source === 'run' || b.source === 'committed' ? b.source : 'none',
  }
}

function toJournalTurn(t: Record<string, unknown>): JournalTurn {
  return {
    id: n(t.id),
    startedAt: String(t.started_at ?? ''),
    modelMs: nOrNull(t.model_ms),
    tokensSent: nOrNull(t.tokens_sent),
    outcome: String(t.outcome ?? ''),
    interface: String(t.interface ?? ''),
    tools: list(t.tools).map((c) => ({
      tool: String(c.tool ?? ''),
      arguments: String(c.arguments ?? ''),
      durationMs: n(c.duration_ms),
      ok: c.ok === true,
      agent: String(c.agent ?? 'main'),
    })),
  }
}

function toMetrics(b: Record<string, unknown>): JournalMetrics {
  const m = rec(b.model)
  return {
    days: n(b.days),
    tools: list(b.tools).map((t) => ({ tool: String(t.tool ?? ''), calls: n(t.calls), failures: n(t.failures), meanMs: n(t.mean_ms), maxMs: n(t.max_ms) })),
    model: { turns: n(m.turns), meanMs: nOrNull(m.mean_ms), maxMs: nOrNull(m.max_ms), notFinal: n(m.not_final) },
  }
}

function toTask(t: Record<string, unknown>): ScheduledTask {
  const s = (v: unknown) => (typeof v === 'string' ? v : null)
  return {
    id: String(t.id ?? ''),
    prompt: String(t.prompt ?? ''),
    intervalS: Number(t.interval_s ?? 0),
    enabled: t.enabled !== false,
    lastRunAt: s(t.last_run_at),
    lastStatus: s(t.last_status),
    nextDue: s(t.next_due),
  }
}

export class HttpEngine implements Engine {
  readonly regenerates = true
  private listeners = new Set<Listener>()
  private branches = new Map<string, Branch>([['main', { sessionId: null, persisted: 0 }]])
  private branch = 'main'
  private branchCount = 0
  /** UI message -> its branch and its position in the server history. */
  private positions = new Map<string, { branch: string; at: number }>()
  private current: Turn | null = null
  private turns = 0
  private persona = 'sensei'
  private lastQuestion: string | null = null
  private readonly baseUrl: string
  private readonly fetchFn: typeof fetch
  private readonly now: () => number
  private readonly grace: number

  constructor(private opts: HttpEngineOptions) {
    this.baseUrl = opts.baseUrl ?? ''
    this.fetchFn = opts.fetchFn ?? ((...args) => fetch(...args))
    this.now = opts.now ?? (() => Date.now())
    this.grace = opts.interruptGraceMs ?? 3000
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  private emit(e: EngineEvent) {
    for (const l of [...this.listeners]) l(e)
  }

  private fail(message: string) {
    this.emit({ type: 'error', message })
  }

  /** A request that never throws: null if the network or the token failed (already reported). */
  private async request(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response | null> {
    let res: Response
    try {
      res = await this.fetchFn(`${this.baseUrl}${path}`, {
        method,
        headers: { Authorization: `Bearer ${this.opts.token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      })
    } catch (err) {
      if ((err as { name?: string }).name !== 'AbortError')
        this.fail(`Server unreachable: ${(err as Error).message}`)
      return null
    }
    if (res.status === 401) {
      this.fail('Token rejected by the server: paste the token printed when sensai-web started.')
      this.opts.onUnauthorized?.()
      return null
    }
    return res
  }

  private async failFrom(res: Response) {
    let message = `Unexpected server response (${res.status})`
    try {
      const body = (await res.json()) as { error?: string; details?: string }
      if (body.error) message = body.details ? `${body.error} - ${body.details}` : body.error
    } catch {
      /* unreadable body: generic message */
    }
    this.fail(message)
  }

  private async sessionOf(name: string): Promise<string | null> {
    const branch = this.branches.get(name)
    if (!branch) return null
    if (branch.sessionId) return branch.sessionId
    const res = await this.request('POST', '/api/sessions')
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    branch.sessionId = ((await res.json()) as { session_id: string }).session_id
    return branch.sessionId
  }

  // --- A turn ------------------------------------------------------------------------------

  send(msg: UserMessage): void {
    const text = msg.text.trim()
    if (!text) return
    if (this.current) {
      this.fail('A turn is already running: wait for the answer or interrupt it.')
      return
    }
    let question = text
    let skipCache = false
    if (text === '/again') {
      if (!this.lastQuestion) {
        this.fail('No question to ask again.')
        return
      }
      question = this.lastQuestion
      skipCache = true
    }
    this.positions.set(msg.id, { branch: this.branch, at: this.branches.get(this.branch)?.persisted ?? 0 })
    void this.run(this.branch, question, skipCache)
  }

  private end(turn: Turn, interrupted: boolean) {
    if (turn.ended) return
    turn.ended = true
    this.emit({ type: 'done', turnId: turn.adapter.turnId, interrupted })
  }

  private async run(branchName: string, text: string, skipCache: boolean) {
    this.turns += 1
    const adapter = new WireAdapter(`t${this.turns}`, this.persona, this.now)
    const turn: Turn = { adapter, ended: false, controller: new AbortController() }
    this.current = turn
    this.emit(adapter.start())
    try {
      const sessionId = await this.sessionOf(branchName)
      if (!sessionId) return
      const res = await this.request(
        'POST',
        `/api/sessions/${sessionId}/messages`,
        { content: text, skip_cache: skipCache },
        turn.controller.signal,
      )
      if (!res) return
      if (!res.ok || !res.body) {
        await this.failFrom(res)
        return
      }
      const parser = new SseParser()
      const decoder = new TextDecoder()
      const reader = res.body.getReader()
      // The server sends `done`, then saves the conversation and releases the session before closing
      // the stream: the turn only ends on close, otherwise the conversation list reloads too early
      // and a message sent right away gets 409 "turn in progress".
      let doneInterrupted: boolean | null = null
      try {
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          for (const raw of parser.push(decoder.decode(value, { stream: true }))) {
            for (const ev of adapter.push(raw)) {
              if (ev.type === 'done') doneInterrupted = ev.interrupted
              else if (!turn.ended) this.emit(ev)
            }
          }
        }
      } catch (err) {
        if ((err as { name?: string }).name !== 'AbortError' && !turn.ended) this.fail('Stream interrupted by the server.')
      }
      if (adapter.doneReason === null && !turn.ended && !turn.controller.signal.aborted)
        this.fail('The server closed the stream before the turn ended.')
      if (adapter.doneReason === 'final_answer') {
        const branch = this.branches.get(branchName)
        if (branch) branch.persisted += 2
        this.lastQuestion = text
      }
      if (doneInterrupted !== null) this.end(turn, doneInterrupted)
    } finally {
      this.end(turn, turn.controller.signal.aborted)
      if (this.current === turn) this.current = null
    }
  }

  interrupt(): void {
    const turn = this.current
    if (!turn) return
    const sessionId = this.branches.get(this.branch)?.sessionId
    // Control calls never use the stream signal, otherwise they would start already aborted.
    if (sessionId) void this.request('POST', `/api/sessions/${sessionId}/interrupt`)
    // The server ends the turn with `done interrupted`; if it does not answer, cut the stream.
    setTimeout(() => {
      if (this.current === turn && !turn.ended) {
        turn.controller.abort()
        this.end(turn, true)
      }
    }, this.grace)
  }

  confirm(requestId: string, approved: boolean): void {
    const sessionId = this.branches.get(this.branch)?.sessionId
    if (!sessionId) return
    void (async () => {
      const res = await this.request('POST', `/api/sessions/${sessionId}/confirm`, { confirm_id: requestId, approved })
      if (res && res.status === 404) this.fail('This request expired: the action was not run.')
      else if (res && !res.ok) await this.failFrom(res)
    })()
  }

  answer(requestId: string, values: Record<string, unknown>): void {
    const sessionId = this.branches.get(this.branch)?.sessionId
    if (!sessionId) return
    void (async () => {
      const res = await this.request('POST', `/api/sessions/${sessionId}/answer`, { question_id: requestId, values })
      if (res && res.status === 404) this.fail('This question expired: the agent went on without your answer.')
      else if (res && !res.ok) await this.failFrom(res)
    })()
  }

  // --- Sharing (X3) -------------------------------------------------------------------------

  /** Publishes the conversation of the displayed branch; null if nothing to share or on failure (reported). */
  async share(): Promise<SharedLink | null> {
    const sessionId = this.branches.get(this.branch)?.sessionId
    if (!sessionId) {
      this.fail('Nothing to share: the conversation has no messages yet.')
      return null
    }
    const res = await this.request('POST', `/api/sessions/${sessionId}/share`)
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    const body = (await res.json()) as { url: string; token: string; expires_at: string }
    const origin = this.baseUrl || (typeof window !== 'undefined' ? window.location.origin : '')
    return { url: `${origin}${body.url}`, token: body.token, expiresAt: body.expires_at }
  }

  async revokeShare(token: string): Promise<boolean> {
    const res = await this.request('POST', `/api/shares/${encodeURIComponent(token)}/revoke`)
    if (res && !res.ok) await this.failFrom(res)
    return Boolean(res?.ok)
  }

  /** Secret-filtered export by the server, for the conversation of the displayed branch. */
  async exportSession(format: 'json' | 'md'): Promise<string | null> {
    const sessionId = this.branches.get(this.branch)?.sessionId
    if (!sessionId) {
      this.fail('Nothing to export: the conversation has no messages yet.')
      return null
    }
    const res = await this.request('GET', `/api/sessions/${encodeURIComponent(sessionId)}/export?format=${format}`)
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    return res.text()
  }

  // --- Past conversations (#44) ----------------------------------------------------------

  // --- Profile and facts (M1, M3) --------------------------------------------------------

  private async json<T>(method: string, path: string, body?: unknown): Promise<T | null> {
    const res = await this.request(method, path, body)
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    return (await res.json()) as T
  }

  getProfile(): Promise<UserProfile | null> {
    return this.json<UserProfile>('GET', '/api/profile')
  }

  addPreference(text: string): Promise<UserProfile | null> {
    return this.json<UserProfile>('POST', '/api/profile/preferences', { text })
  }

  forgetPreferences(): Promise<UserProfile | null> {
    return this.json<UserProfile>('POST', '/api/profile/forget')
  }

  async forgetFact(entity: string): Promise<boolean> {
    const body = await this.json<{ removed: number }>('POST', '/api/facts/forget', { entity })
    return body !== null
  }

  async getFacts(): Promise<ProjectFact[] | null> {
    const body = await this.json<{ facts: Record<string, { attribute: string; value: string }[]> }>('GET', '/api/facts')
    if (!body) return null
    return Object.entries(body.facts).flatMap(([entity, rows]) =>
      rows.map((r) => ({ entity, attribute: String(r.attribute), value: String(r.value) })),
    )
  }

  async getState(): Promise<Record<string, string> | null> {
    const body = await this.json<{ bodies?: Record<string, string> }>('GET', '/api/state')
    return body?.bodies ?? null
  }

  async evaluate(): Promise<Evaluation | null> {
    const sessionId = this.branches.get(this.branch)?.sessionId
    if (!sessionId) {
      this.fail('Nothing to evaluate: the conversation has no answers yet.')
      return null
    }
    const body = await this.json<{ scores: { relevance: number; coherence: number; faithfulness: number | null }; passages: number }>(
      'POST',
      `/api/sessions/${sessionId}/evaluate`,
    )
    return body ? { ...body.scores, passages: body.passages } : null
  }

  // --- Adversarial corpus (EV4) and log (EV3) --------------------------------------------

  async adversarialResults(): Promise<AdversarialRun | null> {
    const body = await this.json<Record<string, unknown>>('GET', '/api/quality/adversarial')
    return body ? toAdversarial(body) : null
  }

  async runAdversarial(): Promise<AdversarialRun | null> {
    const body = await this.json<Record<string, unknown>>('POST', '/api/quality/adversarial/run')
    return body ? toAdversarial(body) : null
  }

  async journal(sessionId: string): Promise<JournalTurn[] | null> {
    const body = await this.json<{ turns: Record<string, unknown>[] }>('GET', `/api/journal?session=${encodeURIComponent(sessionId)}&limit=100`)
    return body ? body.turns.map(toJournalTurn) : null
  }

  async journalMetrics(days: number): Promise<JournalMetrics | null> {
    const body = await this.json<Record<string, unknown>>('GET', `/api/journal/metrics?days=${days}`)
    return body ? toMetrics(body) : null
  }

  async listTasks(): Promise<ScheduledTask[] | null> {
    const list = await this.json<Record<string, unknown>[]>('GET', '/api/schedule/tasks')
    return list ? list.map(toTask) : null
  }

  async addTask(id: string, prompt: string, every: string): Promise<ScheduledTask | null> {
    const body = await this.json<Record<string, unknown>>('POST', '/api/schedule/tasks', { id, prompt, every })
    return body ? toTask(body) : null
  }

  async removeTask(id: string): Promise<boolean> {
    const res = await this.request('POST', `/api/schedule/tasks/${encodeURIComponent(id)}/remove`)
    if (res && !res.ok) await this.failFrom(res)
    return Boolean(res?.ok)
  }

  async setTaskEnabled(id: string, enabled: boolean): Promise<boolean> {
    const res = await this.request('POST', `/api/schedule/tasks/${encodeURIComponent(id)}/enabled`, { enabled })
    if (res && !res.ok) await this.failFrom(res)
    return Boolean(res?.ok)
  }

  newConversation(): boolean {
    if (this.current) {
      this.fail('A turn is already running: wait for the answer or interrupt it.')
      return false
    }
    this.branches = new Map([['main', { sessionId: null, persisted: 0 }]])
    this.branch = 'main'
    this.branchCount = 0
    this.positions.clear()
    this.lastQuestion = null
    return true
  }

  currentSession(): string | null {
    return this.branches.get(this.branch)?.sessionId ?? null
  }

  async deleteSession(id: string): Promise<boolean> {
    const res = await this.request('POST', `/api/sessions/${encodeURIComponent(id)}/delete`)
    if (!res) return false
    if (!res.ok) {
      await this.failFrom(res)
      return false
    }
    // The displayed conversation was just deleted: start over from an empty conversation.
    if ([...this.branches.values()].some((b) => b.sessionId === id)) this.newConversation()
    return true
  }

  async listSessions(): Promise<SessionSummary[] | null> {
    const res = await this.request('GET', '/api/sessions')
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    const list = (await res.json()) as { session_id: string; title: string; updated_at: string; message_count: number }[]
    return list.map((s) => ({ id: s.session_id, title: s.title, updatedAt: s.updated_at, messageCount: s.message_count }))
  }

  async openSession(id: string): Promise<PastMessage[] | null> {
    if (this.current) {
      this.fail('A turn is already running: wait for the answer or interrupt it.')
      return null
    }
    const res = await this.request('GET', `/api/sessions/${encodeURIComponent(id)}`)
    if (!res) return null
    if (!res.ok) {
      await this.failFrom(res)
      return null
    }
    const { messages } = (await res.json()) as { messages: { role?: string; content?: unknown }[] }
    // The reopened conversation becomes the main branch; previous branches are dropped.
    this.branches = new Map([['main', { sessionId: id, persisted: messages.length }]])
    this.branch = 'main'
    this.branchCount = 0
    this.positions.clear()
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    this.lastQuestion = typeof lastUser?.content === 'string' ? lastUser.content : null
    const out: PastMessage[] = []
    messages.forEach((m, at) => {
      if (m.role !== 'user' && m.role !== 'assistant') return
      const msgId = `h${at}`
      if (m.role === 'user') this.positions.set(msgId, { branch: 'main', at })
      out.push({ id: msgId, role: m.role, text: typeof m.content === 'string' ? m.content : String(m.content ?? '') })
    })
    return out
  }

  // --- Branches (X2) -------------------------------------------------------------------------

  editMessage(id: string, text: string): BranchId | null {
    const clean = text.trim()
    const pos = this.positions.get(id)
    if (!pos || !clean) {
      this.fail(`Message not found or empty: ${id}`)
      return null
    }
    if (this.current) {
      this.fail('A turn is already running: wait for the answer or interrupt it.')
      return null
    }
    const parent = this.branches.get(pos.branch)
    this.branchCount += 1
    const name = `b${this.branchCount}`
    this.branches.set(name, { sessionId: null, persisted: pos.at })
    this.branch = name
    this.positions.set(`${id}-${name}`, { branch: name, at: pos.at })
    void (async () => {
      if (parent?.sessionId) {
        const res = await this.request('POST', `/api/sessions/${parent.sessionId}/fork`, { at_message: pos.at })
        const branch = this.branches.get(name)
        if (res && res.ok && branch) {
          branch.sessionId = ((await res.json()) as { session_id: string }).session_id
        } else {
          if (res && !res.ok) await this.failFrom(res)
          if (branch) branch.persisted = 0 // restarts without history, and says so
          this.fail('The branch could not restore the history: it starts from an empty conversation.')
        }
      }
      await this.run(name, clean, false)
    })()
    return name
  }

  selectBranch(branch: string): void {
    if (this.branches.has(branch)) this.branch = branch
  }

  switchPersona(id: string): void {
    void this.setPersona(id)
  }

  // --- Personas, per conversation (A5, Workstream A; ADR-0054)-------------------------------

  async getFewshot(): Promise<FewshotInfo | null> {
    const b = await this.json<Record<string, unknown>>('GET', '/api/fewshot')
    if (!b) return null
    return {
      configured: b.configured === true,
      file: typeof b.file === 'string' ? b.file : null,
      minScore: typeof b.min_score === 'number' ? b.min_score : 0,
      questions: Array.isArray(b.questions) ? b.questions.map(String) : [],
      error: typeof b.error === 'string' ? b.error : null,
    }
  }

  async listPersonas(): Promise<PersonaInfo[] | null> {
    const list = await this.json<Record<string, unknown>[]>('GET', '/api/personas')
    if (!list) return null
    const personas = list.map(toPersona)
    rememberPersonaNames(personas)
    return personas
  }

  async getPersona(): Promise<PersonaInfo | null> {
    const sessionId = this.currentSession()
    // Conversation not created yet: the default persona from config.json.
    const persona = sessionId
      ? await this.json<Record<string, unknown>>('GET', `/api/sessions/${encodeURIComponent(sessionId)}/persona`).then(
          (p) => (p ? toPersona(p) : null),
        )
      : ((await this.listPersonas())?.find((p) => p.isDefault) ?? null)
    if (persona) {
      this.persona = persona.id
      rememberPersonaNames([persona])
    }
    return persona
  }

  async setPersona(id: string): Promise<PersonaInfo | null> {
    if (this.current) {
      this.fail('A turn is already running: wait for the answer before changing persona.')
      return null
    }
    const sessionId = await this.sessionOf(this.branch)
    if (!sessionId) return null
    const body = await this.json<Record<string, unknown>>('POST', `/api/sessions/${encodeURIComponent(sessionId)}/persona`, {
      persona: id,
    })
    if (!body) return null
    const persona = toPersona(body)
    this.persona = persona.id
    rememberPersonaNames([persona])
    return persona
  }

  // --- Prompt versions, read-only (A4, Workstream A; ADR-0055) ---------------------------

  listPrompts(): Promise<PromptEntry[] | null> {
    return this.json<PromptEntry[]>('GET', '/api/prompts')
  }

  async getPromptText(name: string, version: string): Promise<string | null> {
    const body = await this.json<{ text: string }>('GET', `/api/prompts/${encodeURIComponent(name)}/${encodeURIComponent(version)}`)
    return body ? body.text : null
  }

  async diffPrompts(name: string, a: string, b: string): Promise<string | null> {
    const query = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`
    const body = await this.json<{ diff: string }>('GET', `/api/prompts/${encodeURIComponent(name)}/diff?${query}`)
    return body ? body.diff : null
  }

  async getPromptTrial(): Promise<PromptTrial | null> {
    const sessionId = this.currentSession()
    if (sessionId) return this.json<PromptTrial>('GET', `/api/sessions/${encodeURIComponent(sessionId)}/prompt-trial`)
    const prompts = await this.listPrompts()
    if (!prompts) return null
    return { active: prompts.find((p) => p.name === 'system')?.active ?? null, trial: null }
  }

  async setPromptTrial(version: string | null): Promise<PromptTrial | null> {
    if (this.current) {
      this.fail('A turn is already running: wait for the answer before changing prompt.')
      return null
    }
    const sessionId = await this.sessionOf(this.branch)
    if (!sessionId) return null
    return this.json<PromptTrial>('POST', `/api/sessions/${encodeURIComponent(sessionId)}/prompt-trial`, { version })
  }
}
