import { useEffect, useState } from 'react'
import type { JournalMetrics, JournalTurn } from '../contract/engine'
import { useEngine } from '../state/useEngine'
import { fmt } from '../ui/format'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'

const OUTCOME: Record<string, string> = {
  final_answer: 'Answer',
  error: 'Failure',
  interrupted: 'Interrupted',
  max_iterations: 'Too many steps',
}

function Metric({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <GlassCard className="p-4"><p className="text-xs font-semibold text-muted">{label}</p><p className="text-3xl font-extrabold" data-testid={id}>{value}</p></GlassCard>
  )
}

const ms = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${fmt(v)} ms`)

/** Real server (EV3): the log stored server-side, which survives a reload. */
function ServerJournal() {
  const { state, journal, journalMetrics, currentSession } = useEngine()
  const [view, setView] = useState<'session' | 'tools'>('session')
  const [turns, setTurns] = useState<JournalTurn[] | null>(null)
  const [metrics, setMetrics] = useState<JournalMetrics | null>(null)
  const session = currentSession?.() ?? null

  // Reloaded on open, on conversation change and at the end of each turn.
  useEffect(() => {
    if (state.thinking) return
    let alive = true
    if (session && journal) void journal(session).then((t) => alive && setTurns(t))
    else setTurns([])
    if (journalMetrics) void journalMetrics(7).then((m) => alive && setMetrics(m))
    return () => {
      alive = false
    }
  }, [session, state.thinking, journal, journalMetrics])

  const tab = (id: 'session' | 'tools', label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={view === id}
      onClick={() => setView(id)}
      className={`rounded-full px-3 py-1.5 text-sm font-semibold ${view === id ? 'bg-accent-soft text-ink' : 'text-muted hover:text-ink'}`}
    >
      {label}
    </button>
  )
  const calls = (turns ?? []).flatMap((t) => t.tools)
  return (
    <>
      <PageHeader title="Log" intro="What the agent did, recorded by the server (web and terminal): each turn, the time spent waiting for the model, each tool with its arguments (secrets masked), its duration and its outcome." />
      <div role="tablist" className="mb-4 flex gap-2">
        {tab('session', 'This conversation')}
        {tab('tools', 'All tools')}
      </div>
      {view === 'session' ? (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-4">
            <Metric id="metric-turns" label="Turns" value={String(turns?.length ?? 0)} />
            <Metric id="metric-calls" label="Tool calls" value={String(calls.length)} />
            <Metric id="metric-errors" label="Tool failures" value={String(calls.filter((c) => !c.ok).length)} />
            {/* Sum of recorded turns: the tab counter restarts from zero when the conversation is reopened. */}
            <Metric id="metric-tokens" label="Tokens sent (estimated)" value={fmt((turns ?? []).reduce((n, t) => n + (t.tokensSent ?? 0), 0))} />
          </div>
          <GlassCard className="p-5">
            {!session ? (
              <p className="text-sm text-muted">No open conversation: send a message in the chat, or reopen a conversation.</p>
            ) : !turns || turns.length === 0 ? (
              <p className="text-sm text-muted">No recorded turn for this conversation.</p>
            ) : (
              <ol className="space-y-4">
                {turns.map((t) => (
                  <li key={t.id} className="rounded-xl border border-line p-3" data-testid="journal-turn">
                    <p className="mb-2 flex flex-wrap gap-x-4 text-xs text-muted">
                      <span>{new Date(t.startedAt).toLocaleString('fr-FR')}</span>
                      <span>{t.interface === 'cli' ? 'terminal' : 'web'}</span>
                      <span className={t.outcome === 'final_answer' ? 'text-ok' : 'text-danger'}>{OUTCOME[t.outcome] ?? t.outcome}</span>
                      <span>model: {ms(t.modelMs)}</span>
                      {t.tokensSent !== null && <span>~{fmt(t.tokensSent)} tokens sent (estimated)</span>}
                    </p>
                    {t.tools.length > 0 && (
                      <table className="w-full text-sm">
                        <tbody>
                          {t.tools.map((c, i) => (
                            <tr key={i} className="border-t border-line align-top">
                              <td className="py-1 pr-3 font-mono text-xs font-bold">{c.agent === 'main' ? c.tool : `${c.agent} › ${c.tool}`}</td>
                              <td className="max-w-xs break-all pr-3 font-mono text-xs text-muted">{c.arguments}</td>
                              <td className="pr-3 text-xs">{ms(c.durationMs)}</td>
                              <td className={`text-xs font-bold ${c.ok ? 'text-ok' : 'text-danger'}`}>{c.ok ? 'Success' : 'Failure'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </GlassCard>
        </>
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <Metric id="metric-model-turns" label="Turns (7 days)" value={String(metrics?.model.turns ?? 0)} />
            <Metric id="metric-model-mean" label="Mean model time" value={ms(metrics?.model.meanMs)} />
            <Metric id="metric-model-max" label="Max model time" value={ms(metrics?.model.maxMs)} />
          </div>
          <GlassCard className="p-5">
            {!metrics || metrics.tools.length === 0 ? (
              <p className="text-sm text-muted">No tool call in the last 7 days.</p>
            ) : (
              <table className="w-full text-sm">
                <thead><tr className="text-left text-muted"><th className="py-1">Tool</th><th>Calls</th><th>Failures</th><th>Mean duration</th><th>Max duration</th></tr></thead>
                <tbody>
                  {metrics.tools.map((t) => (
                    <tr key={t.tool} className="border-t border-line">
                      <td className="py-2 pr-3 font-mono text-xs font-bold">{t.tool}</td>
                      <td>{t.calls}</td>
                      <td className={t.failures ? 'text-danger' : ''}>{t.failures}</td>
                      <td>{ms(t.meanMs)}</td>
                      <td>{ms(t.maxMs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-3 text-xs text-muted">All conversations and interfaces combined. Wall-clock durations measured by the server: a tool duration includes waiting for your confirmation.</p>
          </GlassCard>
        </>
      )}
    </>
  )
}

/** Simulated engine: the calls of this tab, computed in the browser (nothing is kept). */
function LiveJournal() {
  const { state } = useEngine()
  const logs = state.logs
  const timed = logs.filter((l) => l.ms !== undefined)
  const mean = timed.length ? Math.round(timed.reduce((n, l) => n + (l.ms ?? 0), 0) / timed.length) : null
  const failed = logs.filter((l) => l.ok === false).length
  const rate = logs.length ? Math.round((failed / logs.length) * 100) : null
  const max = Math.max(1, ...timed.map((l) => l.ms ?? 0))
  return (
    <>
      <PageHeader title="Log" intro="Each tool called by the agent during the session: arguments, duration, success or failure. Demo: computed in the browser, nothing is saved." />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Metric id="metric-calls" label="Tool calls" value={String(logs.length)} />
        <Metric id="metric-latency" label="Mean latency" value={mean === null ? '-' : `${mean} ms`} />
        <Metric id="metric-errors" label="Failure rate" value={rate === null ? '-' : `${rate} %`} />
        <Metric id="metric-tokens" label="Tokens used" value={fmt(state.usage.used)} />
      </div>
      <GlassCard className="p-5">
        {logs.length === 0 ? (
          <p className="text-sm text-muted">No call yet. Start a scenario in the chat: the calls show up here.</p>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1">Tool</th><th>Arguments</th><th>Duration</th><th>Status</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-t border-line align-top">
                  <td className="py-2 pr-3 font-mono text-xs font-bold">{l.tool}</td>
                  <td className="max-w-xs break-all pr-3 font-mono text-xs text-muted">{JSON.stringify(l.args)}</td>
                  <td className="pr-3">
                    {l.ms === undefined ? '…' : (
                      <span className="flex items-center gap-2">{l.ms} ms
                        <span className="block h-1.5 w-20 overflow-hidden rounded-full bg-line"><span className="block h-full bg-accent-strong" style={{ width: `${(l.ms / max) * 100}%` }} /></span>
                      </span>
                    )}
                  </td>
                  <td className={l.ok === false ? 'font-bold text-danger' : 'font-bold text-ok'}>{l.ok === undefined ? 'running' : l.ok ? 'Success' : 'Failure'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </GlassCard>
    </>
  )
}

export default function Journal() {
  const { journal } = useEngine()
  return journal ? <ServerJournal /> : <LiveJournal />
}
