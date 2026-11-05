import type { EngineEvent, UserMessage } from './events'

export type BranchId = string

/** Une conversation enregistrée côté serveur (M1), telle que la liste `GET /api/sessions`. */
export interface SessionSummary {
  id: string
  title: string
  updatedAt: string
  messageCount: number
}

/** Un message d'une conversation rouverte ; `id` permet ensuite de le modifier (X2). */
export interface PastMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
}

/** Le profil de l'utilisateur (M1), tel que `GET /api/profile` le renvoie. */
export interface UserProfile {
  name: string
  instructions: string
  preferences: string[]
}

/** Un fait retenu sur le projet (M3). */
export interface ProjectFact {
  entity: string
  attribute: string
  value: string
}

/** Résultat d'une évaluation à la demande (EV1) : notes du juge. */
export interface Evaluation {
  /** 1 à 5 */
  relevance: number
  /** 1 à 5 */
  coherence: number
  /** 0 à 1, null sans passage du projet à vérifier */
  faithfulness: number | null
  passages: number
}

/** Une tâche planifiée (X5), telle que `sensai-schedule` la stocke. */
export interface ScheduledTask {
  id: string
  prompt: string
  intervalS: number
  enabled: boolean
  lastRunAt: string | null
  lastStatus: string | null
  nextDue: string | null
}

/** Ce que le serveur dit de l'A7 : fichier d'exemples, seuil, questions des exemples. */
export interface FewshotInfo {
  configured: boolean
  file: string | null
  minScore: number
  questions: string[]
  error: string | null
}

/** Une persona de config.json (A5, lot A), telle que `GET /api/personas` la renvoie. */
export interface PersonaInfo {
  id: string
  name: string
  role: string
  tone: string
  scope: string
  /** Outils refusés tant que cette persona est active (s'ajoutent à ceux de config.json). */
  toolsDisabled: string[]
  isDefault: boolean
}

/** Une version du registre de prompts (A4, lot A), immuable. */
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
  /** De la plus récente à la plus ancienne. */
  versions: PromptVersionInfo[]
}

/** Essai d'une version du prompt système dans la conversation affichée (ADR-0055). */
export interface PromptTrial {
  active: string | null
  /** null : la conversation utilise la version active. */
  trial: string | null
}

/** Un cas du corpus adversarial (EV4), tel que `/api/quality/adversarial` le renvoie. */
export interface AttackResult {
  id: string
  category: string
  attempt: string
  expected: string
  observed: string
  /** « OK », « ÉCART CONNU », « RÉGRESSION », « ÉCART CORRIGÉ » ou « IGNORÉ » */
  verdict: string
  detail: string
}

export interface AdversarialRun {
  cases: AttackResult[]
  summary: { total: number; ok: number; knownGaps: number; regressions: number; fixed: number; skipped: number }
  /** null : tableau versionné du dépôt, pas encore relancé par ce serveur */
  ranAt: string | null
  source: 'run' | 'committed' | 'none'
}

/** Un appel d'outil noté dans le journal du serveur (EV3). */
export interface JournalTool {
  tool: string
  arguments: string
  durationMs: number
  ok: boolean
  agent: string
}

/** Un tour noté dans le journal du serveur (EV3), durées mesurées côté serveur. */
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

/** Seul point de contact entre l'interface et le moteur (ADR-0005). */
export interface Engine {
  send(msg: UserMessage): void
  interrupt(): void
  editMessage(id: string, text: string): BranchId | null
  confirm(requestId: string, approved: boolean): void
  answer(requestId: string, values: Record<string, unknown>): void
  switchPersona(id: string): void
  /** Branche sur laquelle partent les prochains messages (moteur réel : une session par branche). */
  selectBranch?(branch: BranchId): void
  /** Vrai si le moteur sait redemander la dernière question sans le cache (`/again`). */
  readonly regenerates?: boolean
  /** Repart d'une conversation vide ; false si un tour est en cours (signalé). */
  newConversation?(): boolean
  /** Supprime une conversation enregistrée ; false en cas d'échec (signalé). */
  deleteSession?(id: string): Promise<boolean>
  /** La conversation où partent les prochains messages, null si elle n'existe pas encore. */
  currentSession?(): string | null
  /** Profil et faits réels (M1, M3) ; absents du moteur simulé. Null en cas d'échec (signalé). */
  getProfile?(): Promise<UserProfile | null>
  addPreference?(text: string): Promise<UserProfile | null>
  forgetPreferences?(): Promise<UserProfile | null>
  getFacts?(): Promise<ProjectFact[] | null>
  /** Oublie les faits d'une entité (M3) ; false en cas d'échec (signalé). */
  forgetFact?(entity: string): Promise<boolean>
  /** Sections du document d'état (M4), pour le panneau Artefact au chargement. */
  getState?(): Promise<Record<string, string> | null>
  /** Fait juger la dernière réponse de la conversation affichée (EV1). */
  evaluate?(): Promise<Evaluation | null>
  /** Tâches planifiées (X5) ; exécutées par `sensai-schedule`, pas par le serveur web. */
  listTasks?(): Promise<ScheduledTask[] | null>
  addTask?(id: string, prompt: string, every: string): Promise<ScheduledTask | null>
  removeTask?(id: string): Promise<boolean>
  setTaskEnabled?(id: string, enabled: boolean): Promise<boolean>
  /** Conversations passées du projet (#44) ; absent du moteur simulé. */
  listSessions?(): Promise<SessionSummary[] | null>
  /** Rouvre une conversation : les prochains messages la continuent. Null en cas d'échec (signalé). */
  openSession?(id: string): Promise<PastMessage[] | null>
  /** Lien public en lecture seule (X3, ADR-0048) ; absent du moteur simulé. */
  share?(): Promise<SharedLink | null>
  /** Révoque un lien de partage : la page publique répond ensuite 404 (X3). */
  revokeShare?(token: string): Promise<boolean>
  /** Export du serveur, secrets masqués (X3, ADR-0024) ; null si rien à exporter ou en cas d'échec (signalé). */
  exportSession?(format: 'json' | 'md'): Promise<string | null>
  /** Personas réelles (A5, ADR-0054) ; absentes du moteur simulé. */
  listPersonas?(): Promise<PersonaInfo[] | null>
  /** Exemples few-shot configurés (A7), en lecture seule ; absent du moteur simulé. */
  getFewshot?(): Promise<FewshotInfo | null>
  /** Persona de la conversation affichée (celle par défaut tant qu'elle n'existe pas). */
  getPersona?(): Promise<PersonaInfo | null>
  /** Change la persona de la conversation affichée ; null en cas d'échec (signalé). */
  setPersona?(id: string): Promise<PersonaInfo | null>
  /** Registre des prompts, en lecture seule (A4, ADR-0055) ; absent du moteur simulé. */
  listPrompts?(): Promise<PromptEntry[] | null>
  getPromptText?(name: string, version: string): Promise<string | null>
  diffPrompts?(name: string, a: string, b: string): Promise<string | null>
  getPromptTrial?(): Promise<PromptTrial | null>
  /** Essaie une version du prompt système dans cette conversation (null : revenir à l'active). */
  setPromptTrial?(version: string | null): Promise<PromptTrial | null>
  /** Corpus adversarial (EV4) : derniers résultats, et relance (sans modèle). */
  adversarialResults?(): Promise<AdversarialRun | null>
  runAdversarial?(): Promise<AdversarialRun | null>
  /** Journal des tours (EV3) d'une conversation, le plus récent d'abord. */
  journal?(sessionId: string): Promise<JournalTurn[] | null>
  /** Métriques du journal sur `days` jours, toutes conversations confondues (EV3). */
  journalMetrics?(days: number): Promise<JournalMetrics | null>
  subscribe(listener: (e: EngineEvent) => void): () => void
}
