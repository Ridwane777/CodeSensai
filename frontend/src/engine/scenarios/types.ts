import type { EngineEvent } from '../../contract/events'

export type Step =
  | { delay: number; event: EngineEvent }
  | { delay: number; waitFor: 'confirm' | 'answer'; requestId: string; deny?: readonly Step[] }

export interface Scenario {
  id: string
  steps: readonly Step[]
}
