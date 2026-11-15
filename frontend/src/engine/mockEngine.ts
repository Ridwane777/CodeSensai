import type { Engine, BranchId } from '../contract/engine'
import type { EngineEvent, UserMessage } from '../contract/events'
import { realClock, type Clock } from './clock'
import type { Scenario, Step } from './scenarios/types'

type Listener = (e: EngineEvent) => void

export interface MockEngineOptions {
  route: (text: string) => Scenario
  clock?: Clock
  /** Speed factor: 2 = twice as fast (rehearsals). */
  speed?: number
}

export interface HistoryItem {
  id: string
  text: string
  branch: string
}

export class MockEngine implements Engine {
  private listeners = new Set<Listener>()
  private timer: ReturnType<typeof setTimeout> | null = null
  private steps: readonly Step[] = []
  private index = 0
  private waiting: string | null = null
  private run = 0
  private currentTurn: string | null = null
  private persona = 'sensei'
  private answers: Record<string, unknown> = {}
  private branch = 'main'
  private branchCount = 0
  private log: HistoryItem[] = []
  private readonly clock: Clock
  private readonly speed: number

  constructor(private opts: MockEngineOptions) {
    this.clock = opts.clock ?? realClock
    this.speed = opts.speed ?? 1
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
    }
  }

  send(msg: UserMessage): void {
    const text = msg.text.trim()
    if (!text) return
    this.log.push({ id: msg.id, text, branch: this.branch })
    this.start(text)
  }

  history(): HistoryItem[] {
    return [...this.log]
  }

  editMessage(id: string, text: string): BranchId | null {
    const clean = text.trim()
    if (!this.log.some((m) => m.id === id) || !clean) {
      this.emit({ type: 'error', message: `Message not found or empty: ${id}` })
      return null
    }
    this.branchCount += 1
    this.branch = `b${this.branchCount}`
    this.log.push({ id: `${id}-${this.branch}`, text: clean, branch: this.branch })
    this.start(clean)
    return this.branch
  }

  interrupt(): void {
    if (this.timer !== null) this.clock.clearTimeout(this.timer)
    this.timer = null
    this.waiting = null
    this.steps = []
    if (this.currentTurn === null) return
    const turnId = this.currentTurn
    this.currentTurn = null
    this.emit({ type: 'done', turnId, interrupted: true })
  }

  confirm(requestId: string, approved: boolean): void {
    if (this.waiting !== requestId) return
    const step = this.steps[this.index]
    if (!approved && step && 'waitFor' in step && step.deny) {
      this.steps = step.deny
      this.index = -1
    }
    this.resume(requestId)
  }

  answer(requestId: string, values: Record<string, unknown>): void {
    if (this.waiting !== requestId) return
    this.answers = { ...this.answers, ...values }
    this.resume(requestId)
  }

  switchPersona(id: string): void {
    const from = this.persona
    this.persona = id
    this.emit({ type: 'agent_handoff', from, to: id })
  }

  private resume(requestId: string): void {
    if (this.waiting !== requestId) return
    this.waiting = null
    this.index += 1
    this.play()
  }

  protected start(text: string): void {
    this.interrupt()
    this.run += 1
    this.answers = {}
    this.steps = this.opts.route(text).steps
    this.index = 0
    this.waiting = null
    this.play()
  }

  protected emit(event: EngineEvent): void {
    for (const l of [...this.listeners]) l(event)
  }

  private fill(text: string): string {
    return text.replace(/\{\{(\w+)\}\}/g, (_, key: string) => {
      const v = this.answers[key]
      return v === undefined || v === '' ? '-' : String(v)
    })
  }

  private runId(id: string): string {
    return `r${this.run}:${id}`
  }

  private stamp(event: EngineEvent): EngineEvent {
    let out: EngineEvent = event
    if ('turnId' in out) out = { ...out, turnId: this.runId(out.turnId) } as EngineEvent
    if (out.type === 'turn_start') out = { ...out, agent: this.persona }
    if (out.type === 'confirm_request' || out.type === 'question') out = { ...out, requestId: this.runId(out.requestId) }
    if ('text' in out && typeof out.text === 'string') out = { ...out, text: this.fill(out.text) } as EngineEvent
    if (out.type === 'action') {
      const args = Object.fromEntries(
        Object.entries(out.args).map(([k, v]) => [k, typeof v === 'string' ? this.fill(v) : v]),
      )
      out = { ...out, args }
    }
    return out
  }

  protected play(): void {
    const step = this.steps[this.index]
    if (!step) {
      this.timer = null
      return
    }
    this.timer = this.clock.setTimeout(() => {
      this.timer = null
      if ('waitFor' in step) {
        this.waiting = this.runId(step.requestId)
        return
      }
      if (step.event.type === 'agent_handoff') {
        // The scripted handoff follows the actually active agent: no duplicate, and the engine keeps track of it.
        if (step.event.to === this.persona) {
          this.index += 1
          this.play()
          return
        }
        const handoff: EngineEvent = { type: 'agent_handoff', from: this.persona, to: step.event.to }
        this.persona = step.event.to
        this.emit(handoff)
        this.index += 1
        this.play()
        return
      }
      const event = this.stamp(step.event)
      if (event.type === 'turn_start') this.currentTurn = event.turnId
      if (event.type === 'done') this.currentTurn = null
      this.emit(event)
      this.index += 1
      this.play()
    }, step.delay / this.speed)
  }
}
