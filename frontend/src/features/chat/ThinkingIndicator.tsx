import { useEffect, useState } from 'react'
import type { Turn } from '../../state/store'

/** What the agent is doing right now, in a short phrase. */
export function activity(turn: Turn): string {
  const last = turn.steps[turn.steps.length - 1]
  if (last?.tool && last.observation === undefined) return `Using ${last.tool}`
  if (turn.text.trim()) return 'Writing'
  return 'Thinking'
}

/** Seconds elapsed since `since`, updated every second. */
export function useElapsed(since: number, running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [running])
  return Math.max(0, Math.floor((now - since) / 1000))
}

export function formatSeconds(s: number): string {
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}

/** The spinning star and shimmering text: the agent is visibly working, without anything jumping. */
export function ThinkingIndicator({ label, since }: { label: string; since: number }) {
  const seconds = useElapsed(since, true)
  return (
    <p role="status" className="flex items-center gap-2 text-sm" aria-label={`${label} in progress`}>
      <span className="relative grid h-5 w-5 place-items-center text-accent" aria-hidden="true">
        <span className="breathe absolute inset-0 rounded-full bg-accent-soft" />
        <svg viewBox="0 0 24 24" className="spin-soft relative h-4 w-4" fill="currentColor">
          <path d="M12 2l1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8z" />
        </svg>
      </span>
      <span className="shimmer font-medium">{label}…</span>
      {seconds > 0 && <span className="tabular-nums text-xs text-muted">{formatSeconds(seconds)}</span>}
    </p>
  )
}
