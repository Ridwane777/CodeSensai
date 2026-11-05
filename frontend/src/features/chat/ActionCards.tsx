import { useState } from 'react'
import { useEngine } from '../../state/useEngine'
import type { ConfirmItem, GuardrailItem, QuestionItem, TimelineItem } from '../../state/store'
import { fmt, pct } from '../../ui/format'
import { personaLabel } from '../../ui/personas'
import { PillButton } from '../../ui/PillButton'


/**
 * Le détail d'une demande d'accord. Pour `write_file`, le serveur envoie le diff unifié du
 * fichier (outil `write_file`, `describe_call`) : les lignes ajoutées sont en vert, les lignes
 * retirées en rouge, comme dans un outil de revue de code.
 */
export function ConfirmDetail({ text }: { text: string }) {
  const lines = text.split('\n')
  const start = lines.findIndex((l) => l.startsWith('--- ') || l.startsWith('@@'))
  if (start < 0) return <p className="max-h-72 overflow-auto whitespace-pre-wrap text-sm text-muted">{text}</p>
  const intro = lines.slice(0, start).join('\n').trim()
  return (
    <div className="mt-1">
      {intro && <p className="whitespace-pre-wrap text-sm text-muted">{intro}</p>}
      <pre aria-label="Modifications proposées" className="mt-2 max-h-80 overflow-auto rounded-xl bg-accent-soft p-3 font-mono text-xs leading-snug">
        {lines.slice(start).map((l, i) => {
          const tone =
            l.startsWith('+++') || l.startsWith('---')
              ? 'text-muted'
              : l.startsWith('+')
                ? 'bg-[color-mix(in_srgb,var(--ok)_15%,transparent)] text-ok'
                : l.startsWith('-')
                  ? 'bg-[color-mix(in_srgb,var(--danger)_15%,transparent)] text-danger'
                  : l.startsWith('@@')
                    ? 'text-accent'
                    : ''
          return (
            <span key={i} className={`block ${tone}`}>
              {l || ' '}
            </span>
          )
        })}
      </pre>
    </div>
  )
}

export function ConfirmCard({ item }: { item: ConfirmItem }) {
  const { confirm } = useEngine()
  const pending = item.status === 'pending'
  return (
    <section
      role="group"
      aria-label="Confirmation requise"
      className={`glass rise-in rounded-3xl border-2 p-4 ${item.risk === 'high' ? 'border-danger' : 'border-accent-strong'}`}
    >
      <p className="text-xs font-bold uppercase tracking-wide text-danger">
        {item.risk === 'high' ? 'Action risquée · accord requis' : 'Accord requis'}
      </p>
      <h3 className="mt-1 text-lg font-extrabold">{item.title}</h3>
      <ConfirmDetail text={item.detail} />
      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <PillButton onClick={() => confirm(item.requestId, true)}>Autoriser</PillButton>
          <PillButton variant="outline" onClick={() => confirm(item.requestId, false)}>Refuser</PillButton>
        </div>
      ) : item.status === 'expired' ? (
        <p className="mt-3 text-sm font-bold text-muted">Expirée : l&apos;agent a été interrompu avant ta réponse.</p>
      ) : (
        <p className={`mt-3 text-sm font-bold ${item.status === 'approved' ? 'text-ok' : 'text-danger'}`}>
          {item.status === 'approved' ? '✓ Autorisé' : '✕ Refusé'}
        </p>
      )}
    </section>
  )
}

export function QuestionCard({ item }: { item: QuestionItem }) {
  const { answer } = useEngine()
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(
      item.fields.map((f) => [f.id, f.kind === 'choice' ? f.options[0] : f.kind === 'toggle' ? false : '']),
    ),
  )
  const set = (id: string, v: unknown) => setValues((s) => ({ ...s, [id]: v }))
  const missing = item.fields.some((f) => f.kind === 'text' && String(values[f.id] ?? '').trim() === '')

  if (item.status === 'expired') {
    return (
      <section className="glass rise-in rounded-3xl p-4" aria-label="Question expirée">
        <h3 className="font-extrabold">{item.title}</h3>
        <p className="mt-1 text-sm font-bold text-muted">Expirée : l&apos;agent a été interrompu avant ta réponse.</p>
      </section>
    )
  }

  if (item.status === 'answered') {
    return (
      <section className="glass rise-in rounded-3xl p-4" aria-label="Réponses envoyées">
        <h3 className="font-extrabold">{item.title}</h3>
        <ul className="mt-2 space-y-1 text-sm">
          {item.fields.map((f) => {
            const v = item.values?.[f.id]
            return (
              <li key={f.id}>
                <span className="text-muted">{f.label} :</span>{' '}
                <strong>{typeof v === 'boolean' ? (v ? 'Oui' : 'Non') : String(v ?? '—')}</strong>
              </li>
            )
          })}
        </ul>
      </section>
    )
  }

  return (
    <form
      className="glass rise-in space-y-3 rounded-3xl border-2 border-accent-strong p-4"
      aria-label={item.title}
      onSubmit={(e) => {
        e.preventDefault()
        if (!missing) answer(item.requestId, values)
      }}
    >
      <h3 className="text-lg font-extrabold">{item.title}</h3>
      {item.fields.map((f) => {
        const id = `${item.requestId}-${f.id}`
        return (
          <div key={f.id} className="flex flex-col gap-1 text-sm">
            {f.kind === 'toggle' ? (
              <label className="flex items-center gap-2 font-medium">
                <input
                  type="checkbox"
                  checked={Boolean(values[f.id])}
                  onChange={(e) => set(f.id, e.target.checked)}
                  className="h-4 w-4 accent-[var(--accent-strong)]"
                />
                {f.label}
              </label>
            ) : (
              <>
                <label htmlFor={id} className="font-medium">{f.label}</label>
                {f.kind === 'choice' ? (
                  <select
                    id={id}
                    value={String(values[f.id])}
                    onChange={(e) => set(f.id, e.target.value)}
                    className="rounded-xl border border-line bg-surface px-3 py-2"
                  >
                    {f.options.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <input
                    id={id}
                    value={String(values[f.id])}
                    placeholder={f.placeholder}
                    onChange={(e) => set(f.id, e.target.value)}
                    className="rounded-xl border border-line bg-surface px-3 py-2"
                  />
                )}
              </>
            )}
          </div>
        )
      })}
      <PillButton type="submit" disabled={missing}>Envoyer mes réponses</PillButton>
    </form>
  )
}

const G_LABEL: Record<GuardrailItem['gKind'], string> = {
  secret: 'Secret masqué',
  pii: 'Donnée personnelle masquée',
  unsafe: 'Contenu bloqué',
}

export function GuardrailCard({ item }: { item: GuardrailItem }) {
  return (
    <section role="alert" className="glass rise-in flex items-start gap-3 rounded-3xl border border-danger p-4">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-danger/15 text-danger" aria-hidden="true">🛡</span>
      <div>
        <p className="text-sm font-extrabold text-danger">{G_LABEL[item.gKind]}</p>
        <p className="text-sm">{item.message}</p>
      </div>
    </section>
  )
}

export function NoticeChip({ item }: { item: TimelineItem }) {
  let text: string | null = null
  if (item.kind === 'compression') text = `Contexte compressé : ${fmt(item.savedTokens)} tokens libérés`
  else if (item.kind === 'cache') text = `Réponse servie depuis le cache (similarité ${pct(item.similarity)})`
  else if (item.kind === 'eval')
    text = `Évaluation automatique : pertinence ${pct(item.relevance)} · fidélité ${pct(item.faithfulness)}`
  else if (item.kind === 'handoff') text = `Passage de relais : ${personaLabel(item.from)} → ${personaLabel(item.to)}`
  if (!text) return null
  return (
    <p className="rise-in mx-auto w-fit rounded-full border border-line bg-accent-soft px-4 py-1.5 text-xs font-semibold">
      {text}
    </p>
  )
}
