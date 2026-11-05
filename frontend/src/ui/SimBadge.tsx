import { useConnection } from '../state/connection'

/** Dit toujours à quel moteur parle l'interface : le vrai agent, ou la démonstration (ADR-0035). */
export function SimBadge() {
  const conn = useConnection()
  if (conn?.mode === 'live' && conn.config) {
    return (
      <span
        className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-ink"
        title={`Connecté au vrai agent (sensai-web), projet ${conn.config.project}.`}
      >
        <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
        Agent réel · {conn.config.model}
      </span>
    )
  }
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-line bg-accent-soft px-3 py-1 text-xs font-semibold text-ink"
      title="Le moteur de l'agent est simulé dans le navigateur : l'interface est réelle, les réponses sont scénarisées."
    >
      <span className="h-2 w-2 rounded-full bg-accent-strong" aria-hidden="true" />
      Moteur simulé
    </span>
  )
}
