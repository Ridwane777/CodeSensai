import { useEffect, useState } from 'react'
import type { PersonaInfo } from '../contract/engine'
import { AGENTS } from '../engine/fixtures'
import { NoticeChip } from '../features/chat/ActionCards'
import { useConnection } from '../state/connection'
import { useEngine } from '../state/useEngine'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'
import { PillButton } from '../ui/PillButton'

export default function Agents() {
  const { state, switchPersona, listPersonas } = useEngine()
  const conn = useConnection()
  const live = conn?.mode === 'live' ? conn.config : null
  // Real server: the personas from config.json (A5, ADR-0054).
  const [personas, setPersonas] = useState<PersonaInfo[] | null>(null)
  const isLive = live !== null
  useEffect(() => {
    if (!isLive || !listPersonas) return
    let alive = true
    void listPersonas().then((list) => {
      if (alive) setPersonas(list)
    })
    return () => {
      alive = false
    }
  }, [isLive, listPersonas])
  const handoffs = state.timeline.filter((i) => i.kind === 'handoff')
  const relays = (
    <>
      <h2 className="mb-3 mt-8 text-xl font-extrabold">Session handoffs</h2>
      {handoffs.length === 0 ? (
        <p className="text-sm text-muted">No handoff yet.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {handoffs.map((h, i) => <NoticeChip key={i} item={h} />)}
        </div>
      )}
    </>
  )
  // Real server: the agent that sensai-web actually runs; no fake profiles to enable.
  if (live)
    return (
      <>
        <PageHeader title="Agents" intro="The agent run by sensai-web, and the sub-agents that take over during the session (delegate_task, team_task)." />
        <GlassCard className="max-w-2xl p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-extrabold">CodeSensai</h2>
            <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Active</span>
          </div>
          <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1.5 text-sm">
            <dt className="font-bold">Model</dt><dd className="font-mono text-muted">{live.model}</dd>
            <dt className="font-bold">Project</dt><dd className="font-mono text-muted">{live.project}</dd>
            <dt className="font-bold">RAG</dt><dd className="text-muted">{live.rag ? `enabled${live.rerank ? ', with reranking' : ''}` : 'disabled'}</dd>
            <dt className="font-bold">Cache</dt><dd className="text-muted">{live.cache ? 'semantic cache enabled' : 'disabled'}</dd>
          </dl>
        </GlassCard>
        <h2 className="mb-1 mt-8 text-xl font-extrabold">Personas <span className="text-xs font-semibold text-muted">· A5</span></h2>
        <p className="mb-3 max-w-3xl text-sm text-muted">
          Read from config.json. The chosen persona applies to the conversation shown, while sensai-web is running: it
          is not saved. Creating a persona and keyword routing remain in the <code>sensai</code> CLI.
        </p>
        <div className="grid gap-6 md:grid-cols-2">
          {(personas ?? []).map((p) => {
            const active = state.persona === p.id
            return (
              <GlassCard key={p.id} data-testid={`persona-${p.id}`} className={`p-5 ${active ? 'ring-2 ring-accent-strong' : ''}`}>
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-lg font-extrabold">{p.name}</h3>
                  <span className="flex gap-1">
                    {p.isDefault && <span className="rounded-full border border-line px-2 py-0.5 text-xs font-bold">default</span>}
                    {active && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Active</span>}
                  </span>
                </div>
                <p className="text-sm font-semibold text-accent-strong">{p.role}</p>
                <dl className="mt-3 space-y-1 text-sm">
                  <div><dt className="inline font-bold">Tone: </dt><dd className="inline text-muted">{p.tone}</dd></div>
                  <div><dt className="inline font-bold">Scope: </dt><dd className="inline text-muted">{p.scope}</dd></div>
                  <div>
                    <dt className="inline font-bold">Disabled tools: </dt>
                    <dd className="inline font-mono text-muted">{p.toolsDisabled.length ? p.toolsDisabled.join(', ') : 'aucun'}</dd>
                  </div>
                </dl>
                <PillButton className="mt-4" disabled={active} aria-label={`Enable ${p.name}`} onClick={() => switchPersona(p.id)}>
                  {active ? 'Active agent' : 'Enable for this conversation'}
                </PillButton>
              </GlassCard>
            )
          })}
        </div>
        {relays}
      </>
    )
  return (
    <>
      <PageHeader title="Agents" intro="Several agent profiles, switchable mid-session without losing the conversation. The profiles come from a configuration file (simulated here)." />
      <div className="grid gap-6 md:grid-cols-2">
        {AGENTS.map((a) => {
          const active = state.persona === a.id
          return (
            <GlassCard key={a.id} className={`p-5 ${active ? 'ring-2 ring-accent-strong' : ''}`}>
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-xl font-extrabold">{a.name}</h2>
                {active && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Active</span>}
              </div>
              <p className="text-sm font-semibold text-accent-strong">{a.role}</p>
              <dl className="mt-3 space-y-1 text-sm">
                <div><dt className="inline font-bold">Tone: </dt><dd className="inline text-muted">{a.tone}</dd></div>
                <div><dt className="inline font-bold">Scope: </dt><dd className="inline text-muted">{a.scope}</dd></div>
              </dl>
              <PillButton className="mt-4" disabled={active} aria-label={`Enable ${a.name}`} onClick={() => switchPersona(a.id)}>
                {active ? 'Active agent' : 'Enable'}
              </PillButton>
            </GlassCard>
          )
        })}
      </div>
      {relays}
    </>
  )
}
