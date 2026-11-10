import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ProjectFact, SessionSummary, UserProfile } from '../contract/engine'
import { FACTS, SESSIONS } from '../engine/fixtures'
import { useDemo } from '../state/demoContext'
import { useEngine } from '../state/useEngine'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'
import { PillButton } from '../ui/PillButton'

/** The conversations saved by the real server (#44), to reopen in the chat. */
function PastSessions() {
  const { listSessions, openSession } = useEngine()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null)
  const [opening, setOpening] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    void listSessions?.().then((list) => alive && setSessions(list ?? []))
    return () => {
      alive = false
    }
  }, [listSessions])

  async function reopen(id: string) {
    setOpening(id)
    const ok = await openSession?.(id)
    setOpening(null)
    if (ok) navigate('/chat')
  }

  if (sessions === null) return <p className="text-sm text-muted">Loading conversations…</p>
  if (sessions.length === 0) return <p className="text-sm text-muted">No saved conversation for this project.</p>
  return (
    <ul className="space-y-2 text-sm">
      {sessions.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
          <span className="min-w-0 flex-1 truncate font-semibold">{s.title || s.id}</span>
          <span className="text-muted">{s.messageCount} messages · {s.updatedAt.slice(0, 16).replace('T', ' ')}</span>
          <PillButton arrow={false} disabled={opening !== null} aria-label={`Reopen ${s.title || s.id}`} onClick={() => reopen(s.id)}>
            {opening === s.id ? 'Opening…' : 'Reopen'}
          </PillButton>
        </li>
      ))}
    </ul>
  )
}

export default function Memory() {
  const { listSessions, getProfile, addPreference, forgetPreferences, getFacts, forgetFact } = useEngine()
  const { data, dispatch } = useDemo()
  const [text, setText] = useState('')
  // Real server: the real profile and facts; demo: the page data.
  const real = Boolean(getProfile && getFacts)
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [facts, setFacts] = useState<ProjectFact[] | null>(null)

  useEffect(() => {
    if (!getProfile || !getFacts) return
    let alive = true
    void getProfile().then((p) => alive && p && setProfile(p))
    void getFacts().then((f) => alive && setFacts(f ?? []))
    return () => {
      alive = false
    }
  }, [getProfile, getFacts])

  const prefs = real ? profile?.preferences ?? [] : data.prefs
  const shownFacts = real
    ? (facts ?? []).map((f) => ({ entity: f.entity, fact: `${f.attribute} : ${f.value}` }))
    : FACTS

  async function add(value: string) {
    if (!real) return dispatch({ type: 'add_pref', text: value })
    const p = await addPreference?.(value)
    if (p) setProfile(p)
  }

  async function forget() {
    if (!real) return dispatch({ type: 'forget_prefs' })
    const p = await forgetPreferences?.()
    if (p) setProfile(p)
  }
  return (
    <>
      <PageHeader title="Memory" intro="What CodeSensai remembers from one session to the next: your profile, the facts about the project and the session history." />
      <div className="grid gap-6 lg:grid-cols-2">
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Profile <span className="text-xs font-semibold text-muted">· M1</span></h2>
          {prefs.length === 0 ? (
            <p className="text-sm text-muted">No saved preference.</p>
          ) : (
            <ul className="space-y-2">
              {prefs.map((p) => (
                <li key={p} className="rounded-xl border border-line px-3 py-2 text-sm">{p}</li>
              ))}
            </ul>
          )}
          <form
            className="mt-4 flex flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              void add(text)
              setText('')
            }}
          >
            <input
              aria-label="New preference"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="e.g. write comments in English"
              className="min-w-0 flex-1 rounded-full border border-line bg-surface px-4 py-2 text-sm"
            />
            <PillButton type="submit" disabled={!text.trim()}>Add</PillButton>
            <PillButton variant="outline" onClick={() => void forget()}>Forget everything</PillButton>
          </form>
        </GlassCard>
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Structured facts <span className="text-xs font-semibold text-muted">· M3</span></h2>
          {real && facts !== null && shownFacts.length === 0 && (
            <p className="text-sm text-muted">No fact kept for this project (the agent saves them with the save_fact tool).</p>
          )}
          <dl className="space-y-2 text-sm">
            {shownFacts.map((f, i) => (
              <div key={`${f.entity}-${i}`} className="flex gap-3 rounded-xl border border-line px-3 py-2">
                <dt className="w-44 shrink-0 font-bold">{f.entity}</dt>
                <dd className="flex-1 text-muted">{f.fact}</dd>
                {real && forgetFact && (
                  <button
                    type="button"
                    aria-label={`Forget ${f.entity}`}
                    onClick={async () => {
                      if (await forgetFact(f.entity)) setFacts((list) => list?.filter((x) => x.entity !== f.entity) ?? null)
                    }}
                    className="shrink-0 text-xs text-muted hover:text-danger"
                  >
                    Forget
                  </button>
                )}
              </div>
            ))}
          </dl>
        </GlassCard>
        <GlassCard className="p-5 lg:col-span-2">
          <h2 className="mb-3 text-xl font-extrabold">Project sessions</h2>
          {listSessions ? <PastSessions /> : (
          <ul className="space-y-2 text-sm">
            {SESSIONS.map((s) => (
              <li key={s.id} className="flex items-center justify-between rounded-xl border border-line px-3 py-2">
                <code className="font-mono">{s.id}</code>
                <span className="text-muted">{s.messages} messages</span>
                {s.current && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">session reprise</span>}
              </li>
            ))}
          </ul>
          )}
        </GlassCard>
      </div>
    </>
  )
}
