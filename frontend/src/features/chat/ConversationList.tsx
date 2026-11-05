import { useEffect, useState } from 'react'
import type { SessionSummary } from '../../contract/engine'
import { useEngine } from '../../state/useEngine'

/**
 * Les conversations du projet, à gauche du chat (serveur réel seulement) : en commencer une,
 * en rouvrir une, en supprimer une. La suppression se confirme dans la ligne (pas de boîte de
 * dialogue du navigateur) et elle est définitive. `onOpen` est appelé après une ouverture (la barre
 * latérale s'en sert pour aller sur le chat).
 */
export function ConversationList({ onOpen }: { onOpen?: () => void } = {}) {
  const { state, listSessions, openSession, newConversation, deleteSession, currentSession } = useEngine()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const turns = state.timeline.filter((i) => i.kind === 'turn').length

  // Relue au chargement et après chaque réponse (une nouvelle conversation apparaît).
  useEffect(() => {
    if (state.thinking || !listSessions) return
    let alive = true
    void listSessions().then((list) => alive && list && setSessions(list))
    return () => {
      alive = false
    }
  }, [listSessions, state.thinking, turns])

  if (!listSessions) return null
  const open = currentSession?.() ?? null

  async function remove(id: string) {
    setConfirming(null)
    if (await deleteSession?.(id)) setSessions((list) => list?.filter((s) => s.id !== id) ?? null)
  }

  return (
    <nav aria-label="Conversations" className="flex flex-col gap-2 text-sm">
      <button
        type="button"
        onClick={() => { newConversation?.(); onOpen?.() }}
        disabled={state.thinking}
        className="rounded-full border border-line px-3 py-1.5 font-semibold hover:border-accent hover:bg-accent-soft disabled:opacity-50"
      >
        + Nouvelle conversation
      </button>
      {sessions === null ? (
        <p className="text-muted">Chargement…</p>
      ) : sessions.length === 0 ? (
        <p className="text-muted">Aucune conversation enregistrée.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {sessions.map((s) => (
            <li key={s.id} className={`group rounded-xl px-2 py-1.5 ${s.id === open ? 'bg-accent-soft' : 'hover:bg-accent-soft'}`}>
              {confirming === s.id ? (
                <div className="flex items-center gap-2">
                  <span className="flex-1 text-xs" title="Les faits retenus pendant la conversation restent dans Mémoire, où l'on peut les oublier.">Supprimer définitivement ? (les faits retenus restent dans Mémoire)</span>
                  <button type="button" className="text-xs font-bold text-danger" onClick={() => remove(s.id)}>Oui</button>
                  <button type="button" className="text-xs" onClick={() => setConfirming(null)}>Non</button>
                </div>
              ) : (
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    disabled={state.thinking}
                    aria-current={s.id === open ? 'true' : undefined}
                    onClick={() => { void openSession?.(s.id); onOpen?.() }}
                    className="min-w-0 flex-1 truncate text-left"
                    title={s.title}
                  >
                    {s.title || s.id}
                  </button>
                  <button
                    type="button"
                    aria-label={`Supprimer ${s.title || s.id}`}
                    disabled={state.thinking}
                    onClick={() => setConfirming(s.id)}
                    className="rounded px-1 text-xs text-muted opacity-0 hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    ✕
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}
