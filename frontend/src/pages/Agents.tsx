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
  // Serveur réel : les personas de config.json (A5, ADR-0054).
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
      <h2 className="mb-3 mt-8 text-xl font-extrabold">Relais de la séance</h2>
      {handoffs.length === 0 ? (
        <p className="text-sm text-muted">Aucun passage de relais pour l&apos;instant.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {handoffs.map((h, i) => <NoticeChip key={i} item={h} />)}
        </div>
      )}
    </>
  )
  // Serveur réel : l'agent que sensai-web fait vraiment tourner ; pas de faux profils à activer.
  if (live)
    return (
      <>
        <PageHeader title="Agents" intro="L'agent que fait tourner sensai-web, et les sous-agents qui prennent le relais pendant la séance (delegate_task, team_task)." />
        <GlassCard className="max-w-2xl p-5">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-extrabold">CodeSensei</h2>
            <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Actif</span>
          </div>
          <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1.5 text-sm">
            <dt className="font-bold">Modèle</dt><dd className="font-mono text-muted">{live.model}</dd>
            <dt className="font-bold">Projet</dt><dd className="font-mono text-muted">{live.project}</dd>
            <dt className="font-bold">RAG</dt><dd className="text-muted">{live.rag ? `activé${live.rerank ? ', avec reclassement' : ''}` : 'désactivé'}</dd>
            <dt className="font-bold">Cache</dt><dd className="text-muted">{live.cache ? 'cache sémantique activé' : 'désactivé'}</dd>
          </dl>
        </GlassCard>
        <h2 className="mb-1 mt-8 text-xl font-extrabold">Personas <span className="text-xs font-semibold text-muted">· A5</span></h2>
        <p className="mb-3 max-w-3xl text-sm text-muted">
          Lues dans config.json. La persona choisie vaut pour la conversation affichée, tant que sensai-web tourne : elle
          n&apos;est pas enregistrée. Créer une persona et le routage par mots-clés restent dans le CLI <code>sensai</code>.
        </p>
        <div className="grid gap-6 md:grid-cols-2">
          {(personas ?? []).map((p) => {
            const active = state.persona === p.id
            return (
              <GlassCard key={p.id} data-testid={`persona-${p.id}`} className={`p-5 ${active ? 'ring-2 ring-accent-strong' : ''}`}>
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-lg font-extrabold">{p.name}</h3>
                  <span className="flex gap-1">
                    {p.isDefault && <span className="rounded-full border border-line px-2 py-0.5 text-xs font-bold">par défaut</span>}
                    {active && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Actif</span>}
                  </span>
                </div>
                <p className="text-sm font-semibold text-accent-strong">{p.role}</p>
                <dl className="mt-3 space-y-1 text-sm">
                  <div><dt className="inline font-bold">Ton : </dt><dd className="inline text-muted">{p.tone}</dd></div>
                  <div><dt className="inline font-bold">Périmètre : </dt><dd className="inline text-muted">{p.scope}</dd></div>
                  <div>
                    <dt className="inline font-bold">Outils désactivés : </dt>
                    <dd className="inline font-mono text-muted">{p.toolsDisabled.length ? p.toolsDisabled.join(', ') : 'aucun'}</dd>
                  </div>
                </dl>
                <PillButton className="mt-4" disabled={active} aria-label={`Activer ${p.name}`} onClick={() => switchPersona(p.id)}>
                  {active ? 'Agent actif' : 'Activer pour cette conversation'}
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
      <PageHeader title="Agents" intro="Plusieurs profils d'agent, activables en cours de session sans perdre la conversation. Les profils viennent d'un fichier de configuration (simulé ici)." />
      <div className="grid gap-6 md:grid-cols-2">
        {AGENTS.map((a) => {
          const active = state.persona === a.id
          return (
            <GlassCard key={a.id} className={`p-5 ${active ? 'ring-2 ring-accent-strong' : ''}`}>
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-xl font-extrabold">{a.name}</h2>
                {active && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">Actif</span>}
              </div>
              <p className="text-sm font-semibold text-accent-strong">{a.role}</p>
              <dl className="mt-3 space-y-1 text-sm">
                <div><dt className="inline font-bold">Ton : </dt><dd className="inline text-muted">{a.tone}</dd></div>
                <div><dt className="inline font-bold">Périmètre : </dt><dd className="inline text-muted">{a.scope}</dd></div>
              </dl>
              <PillButton className="mt-4" disabled={active} aria-label={`Activer ${a.name}`} onClick={() => switchPersona(a.id)}>
                {active ? 'Agent actif' : 'Activer'}
              </PillButton>
            </GlassCard>
          )
        })}
      </div>
      {relays}
    </>
  )
}
