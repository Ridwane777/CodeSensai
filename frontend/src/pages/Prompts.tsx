import { useEffect, useState } from 'react'
import type { FewshotInfo, PromptEntry } from '../contract/engine'
import { PROMPTS } from '../engine/fixtures'
import { useConnection } from '../state/connection'
import { useDemo } from '../state/demoContext'
import { useEngine } from '../state/useEngine'
import { diffLines } from '../ui/diff'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'
import { PillButton } from '../ui/PillButton'

const CANDIDATES = [
  { label: 'Current instruction', score: 0.82 },
  { label: '+ 2 examples picked for the question', score: 0.88 },
  { label: '+ rewording adapted to the context', score: 0.9 },
]

/**
 * Real server (A4, Workstream A; ADR-0055): the real registry, read-only. You can read a
 * version, compare two versions and try a system prompt version in the conversation
 * shown; activating it for everyone remains `sensai-prompt use`.
 */
function RealPrompts() {
  const { state, listPrompts, getPromptText, diffPrompts, setPromptTrial } = useEngine()
  const [entries, setEntries] = useState<PromptEntry[] | null>(null)
  const [name, setName] = useState('system')
  const [version, setVersion] = useState<string | null>(null)
  const [compareTo, setCompareTo] = useState<string>('')
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    if (!listPrompts) return
    let alive = true
    void listPrompts().then((list) => {
      if (alive) setEntries(list)
    })
    return () => {
      alive = false
    }
  }, [listPrompts])

  const entry = entries?.find((e) => e.name === name) ?? entries?.[0] ?? null
  const selected = entry ? (entry.versions.find((v) => v.id === version) ?? entry.versions.find((v) => v.active) ?? entry.versions[0]) : null

  useEffect(() => {
    if (!entry || !selected) return
    let alive = true
    const load = compareTo && compareTo !== selected.id && diffPrompts
      ? diffPrompts(entry.name, compareTo, selected.id)
      : getPromptText
        ? getPromptText(entry.name, selected.id)
        : Promise.resolve(null)
    void load.then((t) => {
      if (alive) setText(t)
    })
    return () => {
      alive = false
    }
  }, [entry, selected, compareTo, getPromptText, diffPrompts])

  const diffing = Boolean(selected && compareTo && compareTo !== selected.id)
  return (
    <>
      <PageHeader
        title="Prompts"
        intro="The sensai-web prompt registry (prompts/versions.json), read-only. A system prompt version can be tried in the conversation shown; activating it for everyone is done with sensai-prompt use."
      />
      {entries && entries.length === 0 && <p className="text-sm text-muted">No prompt registry found.</p>}
      {entry && selected && (
        <>
          <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Prompt">
            {entries!.map((e) => (
              <button key={e.name} type="button" aria-pressed={entry.name === e.name}
                onClick={() => { setName(e.name); setVersion(null); setCompareTo('') }}
                className={`rounded-full border px-4 py-1.5 text-sm font-semibold ${entry.name === e.name ? 'border-accent-strong bg-accent-soft' : 'border-line'}`}>
                {e.name}
              </button>
            ))}
            <span className="ml-auto self-center text-sm">
              En service : <strong data-testid={`active-${entry.name}`}>{entry.active}</strong>
            </span>
          </div>
          <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
            <GlassCard className="p-4">
              <h2 className="mb-2 font-extrabold">Versions <span className="text-xs font-semibold text-muted">· A4</span></h2>
              <ul className="space-y-2">
                {entry.versions.map((v) => (
                  <li key={v.id}>
                    <button type="button" aria-pressed={selected.id === v.id} onClick={() => setVersion(v.id)}
                      className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${selected.id === v.id ? 'border-accent-strong bg-accent-soft' : 'border-line'}`}>
                      <span className="font-bold">{v.id}</span> · {v.date} · {v.author}
                      {v.active && <span className="ml-1 rounded-full bg-accent-soft px-1.5 text-xs font-bold">active</span>}
                      <span className="block text-xs text-muted">{v.description}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </GlassCard>
            <GlassCard className="p-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-extrabold">{diffing ? `Differences ${compareTo} → ${selected.id}` : `Text of ${selected.id}`}</h2>
                <label className="flex items-center gap-2 text-xs font-bold">
                  Compare with
                  <select value={compareTo} onChange={(e) => setCompareTo(e.target.value)}
                    className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold">
                    <option value="">(aucune)</option>
                    {entry.versions.filter((v) => v.id !== selected.id).map((v) => (
                      <option key={v.id} value={v.id}>{v.id}</option>
                    ))}
                  </select>
                </label>
                {entry.name === 'system' && setPromptTrial && (
                  <PillButton disabled={state.promptTrial === selected.id} onClick={() => void setPromptTrial(selected.id)}>
                    Try in this conversation
                  </PillButton>
                )}
              </div>
              {entry.name === 'system' && state.promptTrial && (
                <p className="mb-2 text-xs text-muted">
                  Trial run in this conversation: <strong>{state.promptTrial}</strong>.{' '}
                  <button type="button" className="underline" onClick={() => void setPromptTrial?.(null)}>Back to the active version</button>
                </p>
              )}
              <pre data-testid="prompt-text" className="max-h-80 overflow-auto whitespace-pre-wrap rounded-2xl bg-bg/60 p-3 font-mono text-xs leading-relaxed">
                {diffing && text
                  ? text.split('\n').map((l, i) => (
                      <div key={i} className={l.startsWith('+') && !l.startsWith('+++') ? 'text-ok' : l.startsWith('-') && !l.startsWith('---') ? 'text-danger' : ''}>{l}</div>
                    ))
                  : (text ?? '')}
              </pre>
            </GlassCard>
          </div>
        </>
      )}
      <OptimisationCard />
    </>
  )
}

/** A7 with the real server: the configured few-shot examples (ADR-0044). */
function FewshotCard() {
  const { getFewshot } = useEngine()
  const [info, setInfo] = useState<FewshotInfo | null>(null)
  useEffect(() => {
    let alive = true
    void getFewshot?.().then((i) => alive && setInfo(i))
    return () => {
      alive = false
    }
  }, [getFewshot])
  return (
    <GlassCard className="mt-6 p-5">
      <h2 className="mb-1 font-extrabold">Few-shot examples <span className="text-xs font-semibold text-muted">· A7</span></h2>
      <p className="mb-3 text-sm text-muted">
        For each question, the closest example by meaning is attached to the request if it passes the threshold; the answer
        then says so (“Inspired by the example…”).
      </p>
      {info === null ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : !info.configured ? (
        <p className="text-sm text-muted">No example configured (<code>fewshot_examples</code> key in config.json).</p>
      ) : (
        <>
          <p className="mb-2 text-sm">
            File <code>{info.file}</code> · threshold {info.minScore} · {info.questions.length} example(s)
          </p>
          {info.error && <p className="mb-2 text-sm text-warn">{info.error}</p>}
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {info.questions.map((q) => <li key={q}>{q}</li>)}
          </ul>
        </>
      )}
    </GlassCard>
  )
}

function OptimisationCard() {
  const { getFewshot } = useEngine()
  if (getFewshot) return <FewshotCard />
  return (
    <GlassCard className="mt-6 p-5">
      <h2 className="mb-1 font-extrabold">Automatic optimization <span className="text-xs font-semibold text-muted">· A7</span></h2>
      <p className="mb-3 text-sm text-muted">Simulated example (demo without a server): each variant is scored on a question set.</p>
      <ul className="space-y-2 text-sm">
        {CANDIDATES.map((c, i) => (
          <li key={c.label} className="flex items-center gap-3">
            <span className="w-72 shrink-0">{c.label}</span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-line"><span className="block h-full bg-accent-strong" style={{ width: `${c.score * 100}%` }} /></span>
            <span className="w-12 text-right font-bold">{Math.round(c.score * 100)} %</span>
            {i === CANDIDATES.length - 1 && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">meilleure</span>}
          </li>
        ))}
      </ul>
    </GlassCard>
  )
}

export default function Prompts() {
  const { listPrompts } = useEngine()
  const live = useConnection()?.mode === 'live'
  if (live && listPrompts) return <RealPrompts />
  return <DemoPrompts live={live} />
}

function DemoPrompts({ live }: { live: boolean }) {
  const { data, dispatch } = useDemo()
  const [name, setName] = useState('system')
  const [sel, setSel] = useState<Record<string, string>>({ system: 'v1', memory: 'v1' })
  const versions = PROMPTS[name]
  const current = versions.find((v) => v.id === sel[name]) ?? versions[0]
  const idx = versions.indexOf(current)
  const prev = idx > 0 ? versions[idx - 1] : null
  const lines = prev ? diffLines(prev.text, current.text) : []
  return (
    <>
      <PageHeader title="Prompts" intro="Prompts are immutable versions: you compare them, activate one, roll back. The v1 versions are the ones in the repository; v2 is a demo draft." />
      {live && (
        <p role="note" className="mb-4 rounded-2xl border border-warn/40 bg-surface px-4 py-3 text-sm">
          <strong>Not connected to the server:</strong> sensai-web does not expose prompt versions yet. The v1 texts are the ones in the
          repository, v2 is a demo draft, and “Activate” changes nothing on the agent side. The real tool is{' '}
          <code>sensai-prompt</code> (A4).
        </p>
      )}
      <div className="mb-4 flex gap-2" role="group" aria-label="Prompt">
        {Object.keys(PROMPTS).map((n) => (
          <button key={n} type="button" aria-pressed={name === n} onClick={() => setName(n)}
            className={`rounded-full border px-4 py-1.5 text-sm font-semibold ${name === n ? 'border-accent-strong bg-accent-soft' : 'border-line'}`}>
            {n}
          </button>
        ))}
        <span className="ml-auto self-center text-sm">
          En service : <strong data-testid={`active-${name}`}>{data.promptActive[name]}</strong>
        </span>
      </div>
      <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
        <GlassCard className="p-4">
          <h2 className="mb-2 font-extrabold">Versions <span className="text-xs font-semibold text-muted">· A4</span></h2>
          <ul className="space-y-2">
            {versions.map((v) => (
              <li key={v.id}>
                <button type="button" aria-pressed={current.id === v.id} onClick={() => setSel({ ...sel, [name]: v.id })}
                  className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${current.id === v.id ? 'border-accent-strong bg-accent-soft' : 'border-line'}`}>
                  <span className="font-bold">{v.id}</span> · {v.date}
                  <span className="block text-xs text-muted">{v.description}{v.simulated ? ' (simulated draft)' : ''}</span>
                </button>
              </li>
            ))}
          </ul>
        </GlassCard>
        <GlassCard className="p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-extrabold">{prev ? `Differences ${prev.id} → ${current.id}` : `Text of ${current.id}`}</h2>
            <PillButton disabled={data.promptActive[name] === current.id} onClick={() => dispatch({ type: 'use_prompt', name, version: current.id })}>
              Activate
            </PillButton>
          </div>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-2xl bg-bg/60 p-3 font-mono text-xs leading-relaxed">
            {prev
              ? lines.map((l, i) => (
                  <div key={i} className={l.mark === '+' ? 'text-ok' : l.mark === '-' ? 'text-danger' : ''}>{`${l.mark} ${l.text}`}</div>
                ))
              : current.text}
          </pre>
        </GlassCard>
      </div>
      <OptimisationCard />
    </>
  )
}
