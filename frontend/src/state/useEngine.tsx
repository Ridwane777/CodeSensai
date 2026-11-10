import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from 'react'
import type {
  AdversarialRun,
  Engine,
  Evaluation,
  FewshotInfo,
  JournalMetrics,
  JournalTurn,
  PersonaInfo,
  ProjectFact,
  PromptEntry,
  PromptTrial,
  ScheduledTask,
  SessionSummary,
  SharedLink,
  UserProfile,
} from '../contract/engine'
import { MockEngine } from '../engine/mockEngine'
import { route } from '../engine/router'
import { initialState, reduce, type UiState } from './store'

interface Ctx {
  state: UiState
  send(text: string): void
  interrupt(): void
  confirm(requestId: string, approved: boolean): void
  answer(requestId: string, values: Record<string, unknown>): void
  edit(messageId: string, text: string): void
  /** Asks the last question again (↻); no effect if there is none or a turn is running. */
  regenerate(): void
  switchBranch(branch: string): void
  switchPersona(id: string): void
  /** Present only with the real server (#44). */
  listSessions?: () => Promise<SessionSummary[] | null>
  evaluate?: () => Promise<Evaluation | null>
  listTasks?: () => Promise<ScheduledTask[] | null>
  addTask?: (id: string, prompt: string, every: string) => Promise<ScheduledTask | null>
  removeTask?: (id: string) => Promise<boolean>
  setTaskEnabled?: (id: string, enabled: boolean) => Promise<boolean>
  getProfile?: () => Promise<UserProfile | null>
  addPreference?: (text: string) => Promise<UserProfile | null>
  forgetPreferences?: () => Promise<UserProfile | null>
  getFacts?: () => Promise<ProjectFact[] | null>
  forgetFact?: (entity: string) => Promise<boolean>
  newConversation?: () => void
  deleteSession?: (id: string) => Promise<boolean>
  currentSession?: () => string | null
  openSession?: (id: string) => Promise<boolean>
  /** Present only with the real server (X3). */
  share?: () => Promise<SharedLink | null>
  revokeShare?: (token: string) => Promise<boolean>
  exportSession?: (format: 'json' | 'md') => Promise<string | null>
  /** Real personas (A5, ADR-0054): present only with the real server. */
  listPersonas?: () => Promise<PersonaInfo[] | null>
  getFewshot?: () => Promise<FewshotInfo | null>
  /** Prompt registry, read-only, plus trial runs in the conversation (A4, ADR-0055). */
  listPrompts?: () => Promise<PromptEntry[] | null>
  getPromptText?: (name: string, version: string) => Promise<string | null>
  diffPrompts?: (name: string, a: string, b: string) => Promise<string | null>
  setPromptTrial?: (version: string | null) => Promise<PromptTrial | null>
  /** Present only with the real server (EV4, EV3). */
  adversarialResults?: () => Promise<AdversarialRun | null>
  runAdversarial?: () => Promise<AdversarialRun | null>
  journal?: (sessionId: string) => Promise<JournalTurn[] | null>
  journalMetrics?: (days: number) => Promise<JournalMetrics | null>
}

const EngineContext = createContext<Ctx | null>(null)

export function EngineProvider({ children, engine }: { children: ReactNode; engine?: Engine }) {
  const [eng] = useState<Engine>(() => engine ?? new MockEngine({ route }))
  const [state, dispatch] = useReducer(reduce, initialState)
  const stateRef = useRef(state)
  stateRef.current = state
  const counter = useRef(0)

  useEffect(() => eng.subscribe(dispatch), [eng])

  // A5 / A4 (real server): the persona and the prompt trial run belong to the conversation
  // shown; reread on load, when a conversation is opened and on a new one.
  const syncConversation = useCallback(async () => {
    const [persona, trial] = await Promise.all([eng.getPersona?.(), eng.getPromptTrial?.()])
    if (persona) dispatch({ type: 'set_persona', persona: persona.id })
    if (trial) dispatch({ type: 'set_prompt_trial', version: trial.trial })
  }, [eng])

  useEffect(() => {
    void syncConversation()
  }, [syncConversation])

  // M4: the real state document fills the Artifact panel right from load.
  useEffect(() => {
    if (!eng.getState) return
    let alive = true
    void eng.getState().then((bodies) => {
      if (!alive || !bodies) return
      for (const [section, markdown] of Object.entries(bodies))
        if (markdown.trim()) dispatch({ type: 'artifact_patch', section, markdown })
    })
    return () => {
      alive = false
    }
  }, [eng])

  const send = useCallback(
    (text: string) => {
      const clean = text.trim()
      if (!clean) return
      counter.current += 1
      const id = `m${counter.current}`
      dispatch({ type: 'user_message', id, text: clean })
      eng.send({ id, text: clean })
    },
    [eng],
  )

  const edit = useCallback(
    (messageId: string, text: string) => {
      const clean = text.trim()
      if (!clean) return
      const branch = eng.editMessage(messageId, clean)
      if (!branch) return
      dispatch({ type: 'fork', branch, fromId: messageId, id: `${messageId}-${branch}`, text: clean })
    },
    [eng],
  )

  const regenerate = useCallback(() => {
    const s = stateRef.current
    if (s.thinking) return
    const items = s.timeline.filter((i) => i.branch === s.activeBranch)
    const last = [...items].reverse().find((i) => i.kind === 'user')
    if (!last || last.kind !== 'user') return
    counter.current += 1
    const id = `m${counter.current}`
    dispatch({ type: 'user_message', id, text: last.text })
    // Real server: `/again` skips the cache; demo: the same question replayed.
    eng.send({ id, text: eng.regenerates ? '/again' : last.text })
  }, [eng])

  // Functions stay stable while the engine does not change: the Memory page and the sidebar
  // use them as effect dependencies (otherwise one request per render).
  const sessions = useMemo(
    () => ({
      share: eng.share ? () => eng.share!() : undefined,
      revokeShare: eng.revokeShare ? (token: string) => eng.revokeShare!(token) : undefined,
      exportSession: eng.exportSession ? (format: 'json' | 'md') => eng.exportSession!(format) : undefined,
      listSessions: eng.listSessions ? () => eng.listSessions!() : undefined,
      getProfile: eng.getProfile ? () => eng.getProfile!() : undefined,
      evaluate: eng.evaluate
        ? async () => {
            const result = await eng.evaluate!()
            // The Quality page notebook takes the score (relevance scaled to 1).
            if (result)
              dispatch({ type: 'eval_score', relevance: result.relevance / 5, faithfulness: result.faithfulness ?? 0 })
            return result
          }
        : undefined,
      listTasks: eng.listTasks ? () => eng.listTasks!() : undefined,
      addTask: eng.addTask ? (id: string, prompt: string, every: string) => eng.addTask!(id, prompt, every) : undefined,
      removeTask: eng.removeTask ? (id: string) => eng.removeTask!(id) : undefined,
      setTaskEnabled: eng.setTaskEnabled ? (id: string, enabled: boolean) => eng.setTaskEnabled!(id, enabled) : undefined,
      addPreference: eng.addPreference ? (text: string) => eng.addPreference!(text) : undefined,
      forgetPreferences: eng.forgetPreferences ? () => eng.forgetPreferences!() : undefined,
      getFacts: eng.getFacts ? () => eng.getFacts!() : undefined,
      forgetFact: eng.forgetFact ? (entity: string) => eng.forgetFact!(entity) : undefined,
      newConversation: eng.newConversation
        ? () => {
            if (eng.newConversation!()) {
              dispatch({ type: 'load_history', messages: [] })
              // New conversation: default persona and active prompt.
              void syncConversation()
            }
          }
        : undefined,
      deleteSession: eng.deleteSession
        ? async (id: string) => {
            const wasOpen = eng.currentSession?.() === id
            const ok = await eng.deleteSession!(id)
            if (ok && wasOpen) {
              dispatch({ type: 'load_history', messages: [] })
              void syncConversation()
            }
            return ok
          }
        : undefined,
      currentSession: eng.currentSession ? () => eng.currentSession!() : undefined,
      adversarialResults: eng.adversarialResults ? () => eng.adversarialResults!() : undefined,
      runAdversarial: eng.runAdversarial ? () => eng.runAdversarial!() : undefined,
      journal: eng.journal ? (sessionId: string) => eng.journal!(sessionId) : undefined,
      journalMetrics: eng.journalMetrics ? (days: number) => eng.journalMetrics!(days) : undefined,
      openSession: eng.openSession
        ? async (id: string) => {
            const messages = await eng.openSession!(id)
            if (messages) {
              dispatch({ type: 'load_history', messages })
              void syncConversation()
            }
            return messages !== null
          }
        : undefined,
      listPersonas: eng.listPersonas ? () => eng.listPersonas!() : undefined,
      getFewshot: eng.getFewshot ? () => eng.getFewshot!() : undefined,
      listPrompts: eng.listPrompts ? () => eng.listPrompts!() : undefined,
      getPromptText: eng.getPromptText ? (name: string, version: string) => eng.getPromptText!(name, version) : undefined,
      diffPrompts: eng.diffPrompts ? (name: string, a: string, b: string) => eng.diffPrompts!(name, a, b) : undefined,
      setPromptTrial: eng.setPromptTrial
        ? async (version: string | null) => {
            const trial = await eng.setPromptTrial!(version)
            if (trial) dispatch({ type: 'set_prompt_trial', version: trial.trial })
            return trial
          }
        : undefined,
      setPersona: eng.setPersona
        ? async (id: string) => {
            const persona = await eng.setPersona!(id)
            if (persona) dispatch({ type: 'set_persona', persona: persona.id })
          }
        : undefined,
    }),
    [eng, syncConversation],
  )

  const value: Ctx = {
    state,
    send,
    regenerate,
    edit,
    interrupt: () => eng.interrupt(),
    confirm: (requestId, approved) => {
      dispatch({ type: 'resolve', requestId, status: approved ? 'approved' : 'denied' })
      eng.confirm(requestId, approved)
    },
    answer: (requestId, values) => {
      dispatch({ type: 'resolve', requestId, status: 'answered', values })
      eng.answer(requestId, values)
    },
    switchBranch: (branch) => {
      eng.selectBranch?.(branch)
      dispatch({ type: 'switch_branch', branch })
    },
    ...sessions,
    // Real server: the conversation persona changes on the server (A5); simulated: the displayed name.
    switchPersona: (id) => (sessions.setPersona ? void sessions.setPersona(id) : eng.switchPersona(id)),
  }
  return <EngineContext.Provider value={value}>{children}</EngineContext.Provider>
}

export function useEngine(): Ctx {
  const ctx = useContext(EngineContext)
  if (!ctx) throw new Error('useEngine must be used inside <EngineProvider>')
  return ctx
}
