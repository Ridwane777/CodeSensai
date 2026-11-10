import { useConnection } from '../state/connection'

/** Always says which engine the interface talks to: the real agent, or the demo (ADR-0035). */
export function SimBadge() {
  const conn = useConnection()
  if (conn?.mode === 'live' && conn.config) {
    return (
      <span
        className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-ink"
        title={`Connected to the real agent (sensai-web), project ${conn.config.project}.`}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
        Real agent · {conn.config.model}
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-line bg-accent-soft px-3 py-1 text-xs font-semibold text-ink"
      title="The agent engine is simulated in the browser: the interface is real, the answers are scripted."
    >
      <span className="h-2 w-2 rounded-full bg-accent-strong" aria-hidden="true" />
      Simulated engine
    </span>
  )
}
