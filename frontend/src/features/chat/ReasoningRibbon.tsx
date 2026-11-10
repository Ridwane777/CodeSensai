import { useEffect, useRef, useState } from 'react'
import type { ReasoningStep } from '../../state/store'
import { formatSeconds } from './ThinkingIndicator'

function compact(args: Record<string, unknown> | undefined) {
  if (!args || Object.keys(args).length === 0) return ''
  const s = JSON.stringify(args)
  return s.length > 90 ? `${s.slice(0, 87)}…` : s
}

/**
 * The reasoning shown as a terminal: each Thought → Action → Observation step becomes numbered lines
 * ("› thought", "$ tool(args)", "← observation"); the current step keeps the cursor.
 * Open during the turn, it slides closed when the answer is done (like the "thinking" of chat
 * interfaces); a click reopens it.
 */
export function ReasoningRibbon({ steps, active, took = null }: { steps: ReasoningStep[]; active: boolean; took?: number | null }) {
  const [open, setOpen] = useState(true)
  const wasActive = useRef(active)
  useEffect(() => {
    if (wasActive.current && !active) setOpen(false)
    wasActive.current = active
  }, [active])
  if (steps.length === 0) return null
  let n = 0
  const num = () => ++n
  return (
    <section className="code-card mb-3 overflow-hidden rounded-2xl font-mono text-[12.5px] shadow-none" aria-label="Agent reasoning">
      <div className={`flex items-center gap-2 px-3 py-2 transition-colors ${open ? 'border-b border-[color:var(--code-border)]' : ''}`}>
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
        </span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="ml-1 rounded-md px-1.5 py-0.5 text-[color:var(--code-muted)] transition-colors hover:text-[color:var(--code-text)]"
        >
          <span aria-hidden="true" className={`mr-1 inline-block transition-transform duration-300 ${open ? 'rotate-90' : ''}`}>▸</span>
          Reasoning · {steps.length} {steps.length > 1 ? 'steps' : 'step'}
          {took !== null && took > 0 && ` · ${formatSeconds(took)}`}
        </button>
      </div>
      <div className="fold" data-open={open} aria-hidden={!open} {...(open ? {} : { inert: "" })}>
        <div>
        <ol className="relative py-2">
          {steps.map((st, i) => {
            const running = active && i === steps.length - 1 && st.observation === undefined
            return (
              <li key={st.id} className="rise-in">
                {st.thought && (
                  <Line n={num()}>
                    <span className="text-[color:var(--code-keyword)]">› Thought</span>{' '}
                    <span className="text-[color:var(--code-text)]">{st.thought}</span>
                  </Line>
                )}
                {st.tool && (
                  <Line n={num()}>
                    <span className="text-[color:var(--code-muted)]">$ </span>
                    <span className="sr-only">Action </span>
                    {st.tool.startsWith('mcp_') && (
                      <span className="mr-1 rounded bg-accent-soft px-1 text-[10px] font-bold" title="Tool from an external MCP server (T1)">MCP</span>
                    )}
                    <span className="text-[color:var(--code-fn)]">{st.tool}</span>
                    <span className="break-all text-[color:var(--code-string)]">({compact(st.args)})</span>
                  </Line>
                )}
                {st.observation !== undefined ? (
                  <Line n={num()} tone={st.ok === false ? 'bad' : 'good'}>
                    <span className={st.ok === false ? 'text-[color:var(--code-bad)]' : 'text-[color:var(--code-good)]'}>
                      {st.ok === false ? '✗ Failed' : '← Observation'}
                    </span>{' '}
                    <span className="text-[color:var(--code-text)]">{st.observation}</span>
                    {st.ms !== undefined && <span className="ml-2 text-[color:var(--code-muted)]">{st.ms} ms</span>}
                  </Line>
                ) : (
                  running && (
                    <Line n={num()}>
                      <span className="text-[color:var(--code-muted)]">en cours…</span>
                      <span className="caret ml-1 inline-block h-3.5 w-[7px] translate-y-0.5 bg-accent" aria-hidden="true" />
                    </Line>
                  )
                )}
              </li>
            )
          })}
        </ol>
        </div>
      </div>
    </section>
  )
}

function Line({ n, tone, children }: { n: number; tone?: 'good' | 'bad'; children: React.ReactNode }) {
  const bg = tone === 'bad' ? 'bg-[color:var(--code-bad-bg)]' : ''
  return (
    <p className={`flex gap-3 px-3 py-0.5 leading-6 ${bg}`}>
      <span className="w-5 shrink-0 select-none text-right text-[color:var(--code-gutter)]" aria-hidden="true">{n}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </p>
  )
}
