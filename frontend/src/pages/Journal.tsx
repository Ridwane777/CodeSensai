import { useEffect, useState } from 'react'
import type { JournalMetrics, JournalTurn } from '../contract/engine'
import { useEngine } from '../state/useEngine'
import { fmt } from '../ui/format'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'

const OUTCOME: Record<string, string> = {
  final_answer: 'Réponse',
  error: 'Échec',
  interrupted: 'Interrompu',
  max_iterations: 'Trop d’étapes',
}

function Metric({ id, label, value }: { id: string; label: string; value: string }) {
  return (
    <GlassCard className="p-4"><p className="text-xs font-semibold text-muted">{label}</p><p className="text-3xl font-extrabold" data-testid={id}>{value}</p></GlassCard>
  )
}

const ms = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${fmt(v)} ms`)

/** Serveur réel (EV3) : le journal enregistré côté serveur, qui survit au rechargement. */
function ServerJournal() {
  const { state, journal, journalMetrics, currentSession } = useEngine()
  const [view, setView] = useState<'session' | 'tools'>('session')
  const [turns, setTurns] = useState<JournalTurn[] | null>(null)
  const [metrics, setMetrics] = useState<JournalMetrics | null>(null)
  const session = currentSession?.() ?? null

  // Rechargé à l'ouverture, au changement de conversation et à la fin de chaque tour.
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
      <PageHeader title="Journal" intro="Ce que l'agent a fait, enregistré par le serveur (web et terminal) : chaque tour, le temps passé à attendre le modèle, chaque outil avec ses arguments (secrets masqués), sa durée et son issue." />
      <div role="tablist" className="mb-4 flex gap-2">
        {tab('session', 'Cette conversation')}
        {tab('tools', 'Tous les outils')}
      </div>
      {view === 'session' ? (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-4">
            <Metric id="metric-turns" label="Tours" value={String(turns?.length ?? 0)} />
            <Metric id="metric-calls" label="Appels d'outils" value={String(calls.length)} />
            <Metric id="metric-errors" label="Échecs d'outils" value={String(calls.filter((c) => !c.ok).length)} />
            {/* Somme des tours enregistrés : le compteur de l'onglet repart de zéro quand on rouvre la conversation. */}
            <Metric id="metric-tokens" label="Tokens envoyés (estimés)" value={fmt((turns ?? []).reduce((n, t) => n + (t.tokensSent ?? 0), 0))} />
          </div>
          <GlassCard className="p-5">
            {!session ? (
              <p className="text-sm text-muted">Aucune conversation ouverte : envoie un message dans le chat, ou rouvre une conversation.</p>
            ) : !turns || turns.length === 0 ? (
              <p className="text-sm text-muted">Aucun tour enregistré pour cette conversation.</p>
            ) : (
              <ol className="space-y-4">
                {turns.map((t) => (
                  <li key={t.id} className="rounded-xl border border-line p-3" data-testid="journal-turn">
                    <p className="mb-2 flex flex-wrap gap-x-4 text-xs text-muted">
                      <span>{new Date(t.startedAt).toLocaleString('fr-FR')}</span>
                      <span>{t.interface === 'cli' ? 'terminal' : 'web'}</span>
                      <span className={t.outcome === 'final_answer' ? 'text-ok' : 'text-danger'}>{OUTCOME[t.outcome] ?? t.outcome}</span>
                      <span>modèle : {ms(t.modelMs)}</span>
                      {t.tokensSent !== null && <span>~{fmt(t.tokensSent)} tokens envoyés (estimés)</span>}
                    </p>
                    {t.tools.length > 0 && (
                      <table className="w-full text-sm">
                        <tbody>
                          {t.tools.map((c, i) => (
                            <tr key={i} className="border-t border-line align-top">
                              <td className="py-1 pr-3 font-mono text-xs font-bold">{c.agent === 'main' ? c.tool : `${c.agent} › ${c.tool}`}</td>
                              <td className="max-w-xs break-all pr-3 font-mono text-xs text-muted">{c.arguments}</td>
                              <td className="pr-3 text-xs">{ms(c.durationMs)}</td>
                              <td className={`text-xs font-bold ${c.ok ? 'text-ok' : 'text-danger'}`}>{c.ok ? 'Succès' : 'Échec'}</td>
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
            <Metric id="metric-model-turns" label="Tours (7 jours)" value={String(metrics?.model.turns ?? 0)} />
            <Metric id="metric-model-mean" label="Temps modèle moyen" value={ms(metrics?.model.meanMs)} />
            <Metric id="metric-model-max" label="Temps modèle max" value={ms(metrics?.model.maxMs)} />
          </div>
          <GlassCard className="p-5">
            {!metrics || metrics.tools.length === 0 ? (
              <p className="text-sm text-muted">Aucun appel d&apos;outil sur les 7 derniers jours.</p>
            ) : (
              <table className="w-full text-sm">
                <thead><tr className="text-left text-muted"><th className="py-1">Outil</th><th>Appels</th><th>Échecs</th><th>Durée moyenne</th><th>Durée max</th></tr></thead>
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
            <p className="mt-3 text-xs text-muted">Toutes conversations et interfaces confondues. Durées murales mesurées par le serveur : celle d&apos;un outil inclut l&apos;attente de ta confirmation.</p>
          </GlassCard>
        </>
      )}
    </>
  )
}

/** Moteur simulé : les appels de l'onglet, calculés dans le navigateur (rien n'est gardé). */
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
      <PageHeader title="Journal" intro="Chaque outil appelé par l'agent pendant la séance : arguments, durée, succès ou échec. Démonstration : calculé dans le navigateur, rien n'est enregistré." />
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <Metric id="metric-calls" label="Appels d'outils" value={String(logs.length)} />
        <Metric id="metric-latency" label="Latence moyenne" value={mean === null ? '—' : `${mean} ms`} />
        <Metric id="metric-errors" label="Taux d'échec" value={rate === null ? '—' : `${rate} %`} />
        <Metric id="metric-tokens" label="Tokens utilisés" value={fmt(state.usage.used)} />
      </div>
      <GlassCard className="p-5">
        {logs.length === 0 ? (
          <p className="text-sm text-muted">Aucun appel pour l&apos;instant. Lance un scénario dans le chat : les appels apparaissent ici.</p>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1">Outil</th><th>Arguments</th><th>Durée</th><th>État</th></tr></thead>
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
                  <td className={l.ok === false ? 'font-bold text-danger' : 'font-bold text-ok'}>{l.ok === undefined ? 'en cours' : l.ok ? 'Succès' : 'Échec'}</td>
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
