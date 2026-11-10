import type { EngineEvent, UserMessage } from './events'

export type BranchId = string

/** A conversation saved server-side (M1), as listed by `GET /api/sessions`. */
export interface SessionSummary {
  id: string
  title: string
  updatedAt: string
  messageCount: number
}

/** A message from a reopened conversation; `id` lets you edit it later (X2). */
export interface PastMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

/** The user profile (M1), as returned by `GET /api/profile`. */
export interface UserProfile {
  name: string
  instructions: string
  preferences: string[]
}

/** A fact remembered about the project (M3). */
export interface ProjectFact {
  entity: string
  attribute: string
  value: string
}

/** Result of an on-demand evaluation (EV1): the judge's scores. */
export interface Evaluation {
  /** 1 to 5 */
  relevance: number
  /** 1 to 5 */
  coherence: number
  /** 0 to 1, null when there is no project passage to check against */
  faithfulness: number | null
  passages: number
}

/** A scheduled task (X5), as stored by `sensai-schedule`. */
export interface ScheduledTask {
  id: string
  prompt: string
  intervalS: number
  enabled: boolean
  lastRunAt: string | null
  lastStatus: string | null
  nextDue: string | null
}

/** What the server reports about A7: examples file, threshold, example questions. */
export interface FewshotInfo {
  configured: boolean
  file: string | null
  minScore: number
  questions: string[]
  error: string | null
}

/** A persona from config.json (A5, Workstream A), as returned by `GET /api/personas`. */
export interface PersonaInfo {
  id: string
  name: string
  role: string
  tone: string
  scope: string
  /** Tools denied while this persona is active (on top of those in config.json). */
  toolsDisabled: string[]
  isDefault: boolean
}

/** An immutable version from the prompt registry (A4, Workstream A). */
export interface PromptVersionInfo {
  id: string
  date: string
  author: string
  description: string
  active: boolean
}

export interface PromptEntry {
  name: string
  active: string
  /** Newest first. */
  versions: PromptVersionInfo[]
}

/** Trial run of a system prompt version in the displayed conversation (ADR-0055). */
export interface PromptTrial {
  active: string | null
  /** null: the conversation uses the active version. */
  trial: string | null
}

/** A case from the adversarial corpus (EV4), as returned by `/api/quality/adversarial`. */
export interface AttackResult {
  id: string
  category: string
  attempt: string
  expected: string
  observed: string
  /** Status label sent by the server (e.g. OK, known gap, regression, fixed gap, skipped) */
  verdict: string
  detail: string
}

export interface AdversarialRun {
  cases: AttackResult[]
  summary: { total: number; ok: number; knownGaps: number; regressions: number; fixed: number; skipped: number }
  /** null: versioned table from the repository, not rerun by this server yet */
  ranAt: string | null
  source: 'run' | 'committed' | 'none'
}

/** A tool call recorded in the server log (EV3). */
export interface JournalTool {
  tool: string
  arguments: string
  durationMs: number
  ok: boolean
  agent: string
}

/** A turn recorded in the server log (EV3), durations measured server-side. */
export interface JournalTurn {
  id: number
  startedAt: string
  modelMs: number | null
  tokensSent: number | null
  outcome: string
  interface: string
  tools: JournalTool[]
}

export interface JournalMetrics {
  days: number
  tools: { tool: string; calls: number; failures: number; meanMs: number; maxMs: number }[]
  model: { turns: number; meanMs: number | null; maxMs: number | null; notFinal: number }
}

export interface SharedLink {
  url: string
  token: string
  expiresAt: string
}

/** The only contact point between the UI and the engine (ADR-0005). */
export interface Engine {
  send(msg: UserMessage): void
  interrupt(): void
  editMessage(id: string, text: string): BranchId | null
  confirm(requestId: string, approved: boolean): void
  answer(requestId: string, values: Record<string, unknown>): void
  switchPersona(id: string): void
  /** Branch the next messages go to (real engine: one session per branch). */
  selectBranch?(branch: BranchId): void
  /** True if the engine can re-ask the last question bypassing the cache (`/again`). */
  readonly regenerates?: boolean
  /** Starts over with an empty conversation; false if a turn is running (reported). */
  newConversation?(): boolean
  /** Deletes a saved conversation; false on failure (reported). */
  deleteSession?(id: string): Promise<boolean>
  /** The conversation the next messages go to, null if it does not exist yet. */
  currentSession?(): string | null
  /** Real profile and facts (M1, M3); absent from the simulated engine. Null on failure (reported). */
  getProfile?(): Promise<UserProfile | null>
  addPreference?(text: string): Promise<UserProfile | null>
  forgetPreferences?(): Promise<UserProfile | null>
  getFacts?(): Promise<ProjectFact[] | null>
  /** Forgets an entity's facts (M3); false on failure (reported). */
  forgetFact?(entity: string): Promise<boolean>
  /** Sections of the state document (M4), for the Artifact panel on load. */
  getState?(): Promise<Record<string, string> | null>
  /** Has the judge score the last answer of the displayed conversation (EV1). */
  evaluate?(): Promise<Evaluation | null>
  /** Scheduled tasks (X5); run by `sensai-schedule`, not by the web server. */
  listTasks?(): Promise<ScheduledTask[] | null>
  addTask?(id: string, prompt: string, every: string): Promise<ScheduledTask | null>
  removeTask?(id: string): Promise<boolean>
  setTaskEnabled?(id: string, enabled: boolean): Promise<boolean>
  /** Past conversations of the project (#44); absent from the simulated engine. */
  listSessions?(): Promise<SessionSummary[] | null>
  /** Reopens a conversation: the next messages continue it. Null on failure (reported). */
  openSession?(id: string): Promise<PastMessage[] | null>
  /** Public read-only link (X3, ADR-0048); absent from the simulated engine. */
  share?(): Promise<SharedLink | null>
  /** Revokes a share link: the public page then returns 404 (X3). */
  revokeShare?(token: string): Promise<boolean>
  /** Server export, secrets masked (X3, ADR-0024); null if there is nothing to export or on failure (reported). */
  exportSession?(format: 'json' | 'md'): Promise<string | null>
  /** Real personas (A5, ADR-0054); absent from the simulated engine. */
  listPersonas?(): Promise<PersonaInfo[] | null>
  /** Configured few-shot examples (A7), read-only; absent from the simulated engine. */
  getFewshot?(): Promise<FewshotInfo | null>
  /** Persona of the displayed conversation (the default one until it exists). */
  getPersona?(): Promise<PersonaInfo | null>
  /** Changes the persona of the displayed conversation; null on failure (reported). */
  setPersona?(id: string): Promise<PersonaInfo | null>
  /** Prompt registry, read-only (A4, ADR-0055); absent from the simulated engine. */
  listPrompts?(): Promise<PromptEntry[] | null>
  getPromptText?(name: string, version: string): Promise<string | null>
  diffPrompts?(name: string, a: string, b: string): Promise<string | null>
  getPromptTrial?(): Promise<PromptTrial | null>
  /** Tries a system prompt version in this conversation (null: back to the active one). */
  setPromptTrial?(version: string | null): Promise<PromptTrial | null>
  /** Adversarial corpus (EV4): latest results, and rerun (no model). */
  adversarialResults?(): Promise<AdversarialRun | null>
  runAdversarial?(): Promise<AdversarialRun | null>
  /** Turn log (EV3) of a conversation, newest first. */
  journal?(sessionId: string): Promise<JournalTurn[] | null>
  /** Log metrics over `days` days, across all conversations (EV3). */
  journalMetrics?(days: number): Promise<JournalMetrics | null>
  subscribe(listener: (e: EngineEvent) => void): () => void
}
