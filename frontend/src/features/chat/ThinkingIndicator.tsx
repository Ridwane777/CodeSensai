import { useEffect, useState } from 'react'
import type { Turn } from '../../state/store'

/** Ce que l'agent fait en ce moment, en une phrase courte. */
export function activity(turn: Turn): string {
  const last = turn.steps[turn.steps.length - 1]
  if (last?.tool && last.observation === undefined) return `Utilise ${last.tool}`
  if (turn.text.trim()) return 'Rédaction'
  return 'Réflexion'
}

/** Secondes écoulées depuis `since`, mises à jour chaque seconde. */
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

/** L'étoile qui tourne et le texte qui brille : on voit que l'agent travaille, sans que rien ne saute. */
export function ThinkingIndicator({ label, since }: { label: string; since: number }) {
  const seconds = useElapsed(since, true)
  return (
    <p role="status" className="flex items-center gap-2 text-sm" aria-label={`${label} en cours`}>
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
