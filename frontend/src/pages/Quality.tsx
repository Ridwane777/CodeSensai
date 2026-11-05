import { useEffect, useState } from 'react'
import type { AdversarialRun } from '../contract/engine'
import { ATTACKS, EVAL_BASELINE } from '../engine/fixtures'
import { useEngine } from '../state/useEngine'
import { pct } from '../ui/format'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'

export default function Quality() {
  const { state, evaluate, adversarialResults, runAdversarial } = useEngine()
  const [busy, setBusy] = useState(false)
  const [attacks, setAttacks] = useState<AdversarialRun | null>(null)
  const [attacking, setAttacking] = useState(false)

  // EV4 : serveur réel, les résultats du corpus (dernier passage, sinon ceux du dépôt).
  useEffect(() => {
    if (!adversarialResults) return
    let alive = true
    void adversarialResults().then((r) => {
      if (alive && r) setAttacks(r)
    })
    return () => {
      alive = false
    }
  }, [adversarialResults])

  async function attack() {
    if (!runAdversarial) return
    setAttacking(true)
    const r = await runAdversarial()
    if (r) setAttacks(r)
    setAttacking(false)
  }
  const live = state.timeline.flatMap((i) => (i.kind === 'eval' ? [i] : []))
  // Serveur réel : seules les notes vraiment calculées ; démonstration : exemples fixes.
  const rows = [
    ...live.map((e, i) => ({ question: `Réponse évaluée n°${i + 1}`, relevance: e.relevance, faithfulness: e.faithfulness })),
    ...(evaluate ? [] : EVAL_BASELINE),
  ]

  async function run() {
    setBusy(true)
    await evaluate?.()
    setBusy(false)
  }
  const hits = state.timeline.filter((i) => i.kind === 'cache').length
  return (
    <>
      <PageHeader title="Qualité" intro={evaluate ? "Évaluer les réponses de la conversation avec le juge (un appel au modèle par évaluation), et mesurer ce que le cache évite. Les tests adverses rejouent le vrai corpus EV4 (sans modèle)." : "Évaluer les réponses, attaquer l'agent pour voir où il tient, et mesurer ce que le cache évite. Les résultats de cette page sont simulés pour la démo."} />
      <div className="grid gap-6 lg:grid-cols-2">
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Évaluation automatique <span className="text-xs font-semibold text-muted">· EV1</span></h2>
          {evaluate && (
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={run}
                disabled={busy}
                className="rounded-full border border-line px-3 py-1.5 text-sm font-semibold hover:border-accent hover:bg-accent-soft disabled:opacity-50"
              >
                {busy ? 'Le juge évalue…' : 'Évaluer la dernière réponse'}
              </button>
              <span className="text-xs text-muted">Pertinence notée par le modèle juge ; fidélité = part des affirmations appuyées par le projet.</span>
            </div>
          )}
          {evaluate && rows.length === 0 && <p className="text-sm text-muted">Aucune réponse évaluée pour l&apos;instant.</p>}
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1">Question</th><th>Pertinence</th><th>Fidélité</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.question} className="border-t border-line"><td className="py-2 pr-2">{r.question}</td><td>{pct(r.relevance)}</td><td>{pct(r.faithfulness)}</td></tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Cache sémantique <span className="text-xs font-semibold text-muted">· A6</span></h2>
          <p className="text-4xl font-extrabold" data-testid="cache-hits">{hits}</p>
          <p className="text-sm text-muted">réponse(s) servie(s) depuis le cache pendant cette séance, sans appeler le modèle.</p>
        </GlassCard>
        <GlassCard className="p-5 lg:col-span-2">
          <h2 className="mb-3 text-xl font-extrabold">Tests adverses <span className="text-xs font-semibold text-muted">· EV4</span></h2>
          {runAdversarial ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={attack}
                  disabled={attacking}
                  className="rounded-full border border-line px-3 py-1.5 text-sm font-semibold hover:border-accent hover:bg-accent-soft disabled:opacity-50"
                >
                  {attacking ? 'Attaques en cours…' : 'Relancer les attaques'}
                </button>
                <span className="text-xs text-muted">Le corpus EV4 rejoué contre les vraies défenses (passerelle, garde-fous, permissions), sans appeler le modèle.</span>
              </div>
              {attacks && (
                <>
                  <p className="mb-1 text-sm font-semibold" data-testid="attack-summary">
                    {attacks.summary.total} cas · {attacks.summary.ok} OK · {attacks.summary.knownGaps} écarts connus · {attacks.summary.regressions} régressions · {attacks.summary.fixed} écarts corrigés à reclasser · {attacks.summary.skipped} ignorés
                  </p>
                  <p className="mb-3 text-xs text-muted" data-testid="attack-date">
                    {attacks.ranAt
                      ? `Passage du ${new Date(attacks.ranAt).toLocaleString('fr-FR')} sur ce serveur.`
                      : 'Résultats versionnés dans le dépôt (docs/performance/data/EV4-adversarial-results.md) : pas encore relancés ici.'}
                  </p>
                  <div className="max-h-[28rem] overflow-auto">
                    <table className="w-full text-sm">
                      <thead><tr className="text-left text-muted"><th className="py-1 pr-2">Cas</th><th className="pr-2">Tentative</th><th className="pr-2">Attendu</th><th className="pr-2">Observé</th><th>Verdict</th></tr></thead>
                      <tbody>
                        {attacks.cases.map((c) => (
                          <tr key={c.id} className="border-t border-line align-top" title={c.detail || undefined}>
                            <td className="py-2 pr-2 font-mono text-xs">{c.id}</td>
                            <td className="pr-2">{c.attempt}</td>
                            <td className="pr-2 text-xs">{c.expected}</td>
                            <td className="pr-2 text-xs">{c.observed}</td>
                            <td className={`text-xs font-bold ${c.verdict === 'OK' ? 'text-ok' : c.verdict === 'ÉCART CONNU' || c.verdict === 'IGNORÉ' ? 'text-muted' : 'text-danger'}`}>{c.verdict}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </>
          ) : (
            <>
              <p className="mb-3 text-sm text-muted">Exemple simulé pour la démo : avec le serveur réel, cette carte rejoue le vrai corpus de 85 attaques.</p>
              <ul className="space-y-2 text-sm">
                {ATTACKS.map((a) => (
                  <li key={a.prompt} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${a.result === 'blocked' ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'}`}>
                      {a.result === 'blocked' ? 'Tenu' : 'Faiblesse'}
                    </span>
                    <span className="flex-1 font-medium">{a.prompt}</span>
                    <span className="text-muted">{a.note}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </GlassCard>
        <p className="text-sm text-muted lg:col-span-2" data-testid="structured-note">
          Sortie structurée (T5) : c&apos;est une fonction pour l&apos;automatisation, pas pour le chat. Dans le terminal, <code className="font-mono">/structured &lt;schema.json&gt; &lt;demande&gt;</code> renvoie un JSON validé par le schéma (ADR-0039).
        </p>
      </div>
    </>
  )
}
