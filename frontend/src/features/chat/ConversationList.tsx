import { useEffect, useState } from 'react'
import type { SessionSummary } from '../../contract/engine'
import { useEngine } from '../../state/useEngine'

/**
 * The project conversations, left of the chat (real server only): start one, reopen one,
 * delete one. Deletion is confirmed inline (no browser dialog) and is permanent. `onOpen` is
 * called after opening one (the sidebar uses it to go to the chat).
 */
export function ConversationList({ onOpen }: { onOpen?: () => void } = {}) {
  const { state, listSessions, openSession, newConversation, deleteSession, currentSession } = useEngine()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const turns = state.timeline.filter((i) => i.kind === 'turn').length

  // Reloaded on mount and after each answer (a new conversation appears).
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
        <p className="text-muted">Loading…</p>
      ) : sessions.length === 0 ? (
        <p className="text-muted">No saved conversations.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {sessions.map((s) => (
            <li key={s.id} className={`group rounded-xl px-2 py-1.5 ${s.id === open ? 'bg-accent-soft' : 'hover:bg-accent-soft'}`}>
              {confirming === s.id ? (
                <div className="flex items-center gap-2">
                  <span className="flex-1 text-xs" title="Facts remembered during the conversation stay in Memory, where they can be forgotten.">Delete permanently? (remembered facts stay in Memory)</span>
                  <button type="button" className="text-xs font-bold text-danger" onClick={() => remove(s.id)}>Yes</button>
                  <button type="button" className="text-xs" onClick={() => setConfirming(null)}>No</button>
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
                    aria-label={`Delete ${s.title || s.id}`}
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
