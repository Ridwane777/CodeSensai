import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { TimelineItem } from '../../state/store'
import { useEngine } from '../../state/useEngine'
import { PillButton } from '../../ui/PillButton'
import { ConfirmCard, GuardrailCard, NoticeChip, QuestionCard } from './ActionCards'
import { TurnView } from './TurnView'

function UserBubble({ id, text }: { id: string; text: string }) {
  const { edit } = useEngine()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(text)
  return (
    <div className="rise-in ml-auto max-w-[85%]">
      {editing ? (
        <form
          className="glass rounded-3xl p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!draft.trim()) return
            edit(id, draft)
            setEditing(false)
          }}
        >
          <textarea
            aria-label="Nouveau texte du message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full resize-none rounded-2xl bg-transparent p-2 outline-none"
            rows={2}
          />
          <div className="flex justify-end gap-2">
            <PillButton variant="outline" onClick={() => setEditing(false)}>Annuler</PillButton>
            <PillButton type="submit" disabled={!draft.trim()}>Envoyer la variante</PillButton>
          </div>
        </form>
      ) : (
        <div className="group flex items-end justify-end gap-2">
          <button
            type="button"
            aria-label="Modifier le message"
            onClick={() => { setDraft(text); setEditing(true) }}
            className="rounded-full px-2 py-1 text-xs text-muted opacity-0 transition-opacity hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
          >
            ✎ Modifier
          </button>
          <p className="max-h-80 overflow-auto whitespace-pre-wrap rounded-3xl rounded-br-md border border-line bg-surface px-4 py-2.5 leading-relaxed">{text}</p>
        </div>
      )}
    </div>
  )
}

/** Vrai si la page est (presque) en bas : on ne fait suivre le texte que dans ce cas. */
function nearBottom(): boolean {
  if (typeof window === 'undefined') return true
  const doc = document.documentElement
  return window.innerHeight + window.scrollY >= doc.scrollHeight - 160
}

export function MessageList({ items }: { items: TimelineItem[] }) {
  const { regenerate, state } = useEngine()
  const end = useRef<HTMLDivElement>(null)
  const lastTurn = items.reduce((n, item, i) => (item.kind === 'turn' ? i : n), -1)
  // On suit la réponse tant que l'utilisateur est en bas ; s'il remonte lire, on ne le tire plus vers le bas.
  const [following, setFollowing] = useState(true)
  const count = useRef(items.length)
  // Pendant un défilement doux lancé par nous, la page n'est pas encore en bas : on ignore ces événements.
  const settling = useRef(0)
  useEffect(() => {
    const onScroll = () => {
      if (Date.now() < settling.current) return
      setFollowing(nearBottom())
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  useLayoutEffect(() => {
    const added = items.length !== count.current
    count.current = items.length
    if (!following && !added) return
    // Nouvel élément : glissement doux. Texte qui s'allonge : on suit sans animation, sinon ça saccade.
    if (added) settling.current = Date.now() + 800
    end.current?.scrollIntoView?.({ behavior: added ? 'smooth' : 'auto', block: 'end' })
  }, [items, following])
  return (
    <>
    <div className="flex flex-col gap-8 pb-6 pt-2" role="log" aria-live="polite" aria-label="Conversation">
      {items.map((item, i) => {
        if (item.kind === 'user') return <UserBubble key={`${item.id}-${i}`} id={item.id} text={item.text} />
        if (item.kind === 'turn')
          return (
            <div key={item.turn.id}>
              <TurnView turn={item.turn} />
              {i === lastTurn && item.turn.done && !state.thinking && (
                <button
                  type="button"
                  onClick={regenerate}
                  className="ml-12 mt-2 rounded-full px-2 py-1 text-xs text-muted hover:bg-accent-soft hover:text-ink"
                >
                  ↻ Régénérer
                </button>
              )}
            </div>
          )
        if (item.kind === 'confirm') return <ConfirmCard key={item.requestId} item={item} />
        if (item.kind === 'question') return <QuestionCard key={item.requestId} item={item} />
        if (item.kind === 'guardrail') return <GuardrailCard key={i} item={item} />
        return <NoticeChip key={i} item={item} />
      })}
      <div ref={end} className="scroll-mb-40" />
    </div>
    {!following && (
      <button
        type="button"
        onClick={() => {
          setFollowing(true)
          settling.current = Date.now() + 800
          end.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
        }}
        className="rise-in fixed bottom-36 left-1/2 z-20 -translate-x-1/2 rounded-full border border-line bg-surface px-4 py-1.5 text-xs font-semibold shadow-lg transition-colors hover:border-accent lg:left-[calc(50%+8rem)]"
      >
        ↓ Revenir en bas
      </button>
    )}
    </>
  )
}
