import { useEffect, useRef, useState } from 'react'
import type { Turn } from '../../state/store'
import { BrandMark } from '../../ui/FloatingNav'
import { personaLabel } from '../../ui/personas'
import { ReasoningRibbon } from './ReasoningRibbon'
import { activity, ThinkingIndicator } from './ThinkingIndicator'
import { renderRich, visibleAnswer } from './inline'

export function TurnView({ turn }: { turn: Turn }) {
  const started = useRef(Date.now())
  // Turn duration, kept when the turn ends (a turn reopened from history has none).
  const [took, setTook] = useState<number | null>(null)
  const wasLive = useRef(!turn.done)
  useEffect(() => {
    if (turn.done && wasLive.current) {
      wasLive.current = false
      setTook(Math.round((Date.now() - started.current) / 1000))
    }
  }, [turn.done])
  const answer = visibleAnswer(turn.text)
  return (
    <article className="rise-in flex gap-4" aria-label={`Answer from ${personaLabel(turn.agent)}`}>
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent" aria-hidden="true">
        <BrandMark className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="mb-2 text-sm font-semibold">{personaLabel(turn.agent)}</p>
        <ReasoningRibbon steps={turn.steps} active={!turn.done} took={took} />
        {answer && (
          <div className="text-[15.5px] leading-7">
            {renderRich(answer)}
            {!turn.done && <span className="caret ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 rounded-sm bg-accent" aria-hidden="true" />}
          </div>
        )}
        {!turn.done && (
          <div className="mt-2">
            <ThinkingIndicator label={activity(turn)} since={started.current} />
          </div>
        )}
        {turn.fewshot && (
          <p className="mt-1 text-xs text-muted" title="Few-shot example (A7) attached to the question, chosen because it is the closest match to the request">
            Inspired by the example: “{turn.fewshot}”
          </p>
        )}
        {turn.interrupted && <p className="mt-1 text-xs font-semibold text-warn">Generation interrupted</p>}
      </div>
    </article>
  )
}
