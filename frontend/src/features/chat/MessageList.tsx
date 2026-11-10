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
            aria-label="New message text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full resize-none rounded-2xl bg-transparent p-2 outline-none"
            rows={2}
          />
          <div className="flex justify-end gap-2">
            <PillButton variant="outline" onClick={() => setEditing(false)}>Cancel</PillButton>
            <PillButton type="submit" disabled={!draft.trim()}>Send the variant</PillButton>
          </div>
        </form>
      ) : (
        <div className="group flex items-end justify-end gap-2">
          <button
            type="button"
            aria-label="Edit the message"
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

/** True if the page is (almost) at the bottom: only then does the view follow the text. */
function nearBottom(): boolean {
  if (typeof window === 'undefined') return true
  const doc = document.documentElement
  return window.innerHeight + window.scrollY >= doc.scrollHeight - 160
}

export function MessageList({ items }: { items: TimelineItem[] }) {
  const { regenerate, state } = useEngine()
  const end = useRef<HTMLDivElement>(null)
  const lastTurn = items.reduce((n, item, i) => (item.kind === 'turn' ? i : n), -1)
  // Follow the answer while the user is at the bottom; if they scroll up to read, stop pulling them down.
  const [following, setFollowing] = useState(true)
  const count = useRef(items.length)
  // During a smooth scroll we started, the page is not at the bottom yet: ignore these events.
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
    // New item: smooth scroll. Growing text: follow without animation, otherwise it stutters.
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
                  ↻ Regenerate
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
