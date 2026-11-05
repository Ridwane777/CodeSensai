import type { Step } from './types'

export const start = (turnId: string, agent = 'sensei'): Step => ({
  delay: 140,
  event: { type: 'turn_start', turnId, agent },
})

export const end = (turnId: string): Step => ({
  delay: 90,
  event: { type: 'done', turnId, interrupted: false },
})

/** Découpe un texte en tokens (un mot + son espace) pour simuler le streaming. */
export function say(turnId: string, text: string, perWord = 34): Step[] {
  return text
    .split(/(?<=\s)/)
    .map((word) => ({ delay: perWord, event: { type: 'token', turnId, text: word } }) as Step)
}

export const think = (turnId: string, stepId: string, text: string, delay = 520): Step => ({
  delay,
  event: { type: 'thought', turnId, stepId, text },
})

export const act = (
  turnId: string,
  stepId: string,
  tool: string,
  args: Record<string, unknown>,
  delay = 420,
): Step => ({ delay, event: { type: 'action', turnId, stepId, tool, args } })

export const obs = (
  turnId: string,
  stepId: string,
  text: string,
  ms: number,
  ok = true,
  delay = 640,
): Step => ({ delay, event: { type: 'observation', turnId, stepId, text, ms, ok } })
