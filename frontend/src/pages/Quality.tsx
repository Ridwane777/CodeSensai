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

  // EV4: real server, the corpus results (latest run, otherwise the ones in the repository).
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
  // Real server: only the scores actually computed; demo: fixed examples.
  const rows = [
    ...live.map((e, i) => ({ question: `Evaluated answer #${i + 1}`, relevance: e.relevance, faithfulness: e.faithfulness })),
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
      <PageHeader title="Quality" intro={evaluate ? 'Evaluate the conversation answers with the judge (one model call per evaluation), and measure what the cache saves. The adversarial tests replay the real EV4 corpus (no model).' : 'Evaluate answers, attack the agent to see where it holds, and measure what the cache saves. The results on this page are simulated for the demo.'} />
      <div className="grid gap-6 lg:grid-cols-2">
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Automatic evaluation <span className="text-xs font-semibold text-muted">· EV1</span></h2>
          {evaluate && (
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={run}
                disabled={busy}
                className="rounded-full border border-line px-3 py-1.5 text-sm font-semibold hover:border-accent hover:bg-accent-soft disabled:opacity-50"
              >
                {busy ? 'The judge is evaluating…' : 'Evaluate the latest answer'}
              </button>
              <span className="text-xs text-muted">Relevance scored by the judge model; faithfulness = share of claims supported by the project.</span>
            </div>
          )}
          {evaluate && rows.length === 0 && <p className="text-sm text-muted">No evaluated answer yet.</p>}
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted"><th className="py-1">Question</th><th>Relevance</th><th>Faithfulness</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.question} className="border-t border-line"><td className="py-2 pr-2">{r.question}</td><td>{pct(r.relevance)}</td><td>{pct(r.faithfulness)}</td></tr>
              ))}
            </tbody>
          </table>
        </GlassCard>
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Semantic cache <span className="text-xs font-semibold text-muted">· A6</span></h2>
          <p className="text-4xl font-extrabold" data-testid="cache-hits">{hits}</p>
          <p className="text-sm text-muted">answer(s) served from the cache during this session, without calling the model.</p>
        </GlassCard>
        <GlassCard className="p-5 lg:col-span-2">
          <h2 className="mb-3 text-xl font-extrabold">Adversarial tests <span className="text-xs font-semibold text-muted">· EV4</span></h2>
          {runAdversarial ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={attack}
                  disabled={attacking}
                  className="rounded-full border border-line px-3 py-1.5 text-sm font-semibold hover:border-accent hover:bg-accent-soft disabled:opacity-50"
                >
                  {attacking ? 'Attacks running…' : 'Rerun the attacks'}
                </button>
                <span className="text-xs text-muted">The EV4 corpus replayed against the real defenses (gateway, guardrails, permissions), without calling the model.</span>
              </div>
              {attacks && (
                <>
                  <p className="mb-1 text-sm font-semibold" data-testid="attack-summary">
                    {attacks.summary.total} cases · {attacks.summary.ok} OK · {attacks.summary.knownGaps} known gaps · {attacks.summary.regressions} regressions · {attacks.summary.fixed} fixed gaps to reclassify · {attacks.summary.skipped} skipped
                  </p>
                  <p className="mb-3 text-xs text-muted" data-testid="attack-date">
                    {attacks.ranAt
                      ? `Run of ${new Date(attacks.ranAt).toLocaleString('en-GB')} on this server.`
                      : 'Results versioned in the repository (docs/performance/data/EV4-adversarial-results.md): not rerun here yet.'}
                  </p>
                  <div className="max-h-[28rem] overflow-auto">
                    <table className="w-full text-sm">
                      <thead><tr className="text-left text-muted"><th className="py-1 pr-2">Case</th><th className="pr-2">Attempt</th><th className="pr-2">Expected</th><th className="pr-2">Observed</th><th>Verdict</th></tr></thead>
                      <tbody>
                        {attacks.cases.map((c) => (
                          <tr key={c.id} className="border-t border-line align-top" title={c.detail || undefined}>
                            <td className="py-2 pr-2 font-mono text-xs">{c.id}</td>
                            <td className="pr-2">{c.attempt}</td>
                            <td className="pr-2 text-xs">{c.expected}</td>
                            <td className="pr-2 text-xs">{c.observed}</td>
                            <td className={`text-xs font-bold ${c.verdict === 'OK' ? 'text-ok' : c.verdict === 'KNOWN GAP' || c.verdict === 'SKIPPED' ? 'text-muted' : 'text-danger'}`}>{c.verdict}</td>
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
              <p className="mb-3 text-sm text-muted">Simulated example for the demo: with the real server, this card replays the real corpus of 85 attacks.</p>
              <ul className="space-y-2 text-sm">
                {ATTACKS.map((a) => (
                  <li key={a.prompt} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-bold ${a.result === 'blocked' ? 'bg-ok/15 text-ok' : 'bg-danger/15 text-danger'}`}>
                      {a.result === 'blocked' ? 'Held' : 'Weakness'}
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
          Structured output (T5): a feature for automation, not for the chat. In the terminal, <code className="font-mono">/structured &lt;schema.json&gt; &lt;request&gt;</code> returns JSON validated against the schema (ADR-0039).
        </p>
      </div>
    </>
  )
}
