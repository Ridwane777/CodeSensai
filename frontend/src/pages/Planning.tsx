import { useEffect, useState } from 'react'
import type { ScheduledTask } from '../contract/engine'
import { FREQUENCIES } from '../engine/fixtures'
import { useDemo } from '../state/demoContext'
import { useEngine } from '../state/useEngine'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'
import { PillButton } from '../ui/PillButton'

/** Les vraies fréquences, au format de `sensai-schedule` (`30m`, `1h`, `1d`). */
const REAL_FREQUENCIES = [
  { every: '30m', seconds: 1800, label: 'toutes les 30 minutes' },
  { every: '1h', seconds: 3600, label: 'toutes les heures' },
  { every: '1d', seconds: 86400, label: 'chaque jour' },
  { every: '7d', seconds: 604800, label: 'chaque semaine' },
]

function everyLabel(seconds: number): string {
  const found = REAL_FREQUENCIES.find((f) => f.seconds === seconds)
  if (found) return found.label
  if (seconds % 3600 === 0) return `toutes les ${seconds / 3600} h`
  return `toutes les ${Math.round(seconds / 60)} min`
}

/** Identifiant de tâche accepté par `sensai-schedule` (a-z, 0-9, « - », 40 caractères). */
export function taskIdFrom(title: string): string {
  return (
    title
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 40)
      .replace(/-+$/, '') || 'tache'
  )
}

/** Serveur réel (X5) : les tâches de `sensai-schedule`, qui seul les exécute. */
function RealPlanning() {
  const { listTasks, addTask, removeTask, setTaskEnabled } = useEngine()
  const [tasks, setTasks] = useState<ScheduledTask[] | null>(null)
  const [prompt, setPrompt] = useState('')
  const [every, setEvery] = useState('1d')

  async function refresh() {
    const list = await listTasks?.()
    if (list) setTasks(list)
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listTasks])

  async function add() {
    if (!prompt.trim()) return
    if (await addTask?.(taskIdFrom(prompt), prompt.trim(), every)) {
      setPrompt('')
      await refresh()
    }
  }

  return (
    <>
      <PageHeader
        title="Planification"
        intro="Confier des tâches récurrentes à l'agent : résumés, bilans, veille. Elles sont enregistrées pour sensai-schedule, qui les exécute : lancez « sensai-schedule loop » dans un terminal pour qu'elles tournent."
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <GlassCard className="p-5">
          {tasks === null ? (
            <p className="text-sm text-muted">Chargement des tâches…</p>
          ) : tasks.length === 0 ? (
            <p className="text-sm text-muted">Aucune tâche planifiée.</p>
          ) : (
            <ul className="space-y-2">
              {tasks.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold" title={t.prompt}>{t.prompt}</span>
                    <span className="text-xs text-muted">
                      {everyLabel(t.intervalS)} · {t.lastRunAt ? `dernier passage ${t.lastRunAt.slice(0, 16).replace('T', ' ')} (${t.lastStatus ?? '?'})` : 'jamais exécutée'}
                    </span>
                  </span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={t.enabled}
                    aria-label={`Activer ${t.id}`}
                    onClick={async () => { if (await setTaskEnabled?.(t.id, !t.enabled)) await refresh() }}
                    className={`relative h-6 w-11 rounded-full transition-colors ${t.enabled ? 'bg-accent-strong' : 'bg-line'}`}
                  >
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${t.enabled ? 'left-[1.4rem]' : 'left-0.5'}`} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Retirer ${t.id}`}
                    onClick={async () => { if (await removeTask?.(t.id)) await refresh() }}
                    className="rounded px-1 text-muted hover:text-danger"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </GlassCard>
        <GlassCard className="space-y-3 p-5">
          <h2 className="text-xl font-extrabold">Nouvelle tâche</h2>
          <label className="flex flex-col gap-1 text-sm font-medium">Ce que l&apos;agent doit faire
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} className="rounded-xl border border-line bg-surface px-3 py-2" />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">Fréquence
            <select value={every} onChange={(e) => setEvery(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2">
              {REAL_FREQUENCIES.map((f) => <option key={f.every} value={f.every}>{f.label}</option>)}
            </select>
          </label>
          <PillButton onClick={add} disabled={!prompt.trim()}>Planifier</PillButton>
        </GlassCard>
      </div>
    </>
  )
}

export default function Planning() {
  const { listTasks } = useEngine()
  return listTasks ? <RealPlanning /> : <DemoPlanning />
}

function DemoPlanning() {
  const { data, dispatch } = useDemo()
  const [title, setTitle] = useState('')
  const [every, setEvery] = useState(FREQUENCIES[1])
  return (
    <>
      <PageHeader title="Planification" intro="Confier des tâches récurrentes à l'agent : résumés, bilans, veille. L'exécution est simulée : aucune tâche ne tourne réellement." />
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <GlassCard className="p-5">
          <ul className="space-y-2">
            {data.tasks.map((t) => (
              <li key={t.id} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2 text-sm">
                <span className="flex-1 font-semibold">{t.title}</span>
                <span className="text-muted">{t.every}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={t.active}
                  aria-label={`Activer ${t.title}`}
                  onClick={() => dispatch({ type: 'toggle_task', id: t.id })}
                  className={`relative h-6 w-11 rounded-full transition-colors ${t.active ? 'bg-accent-strong' : 'bg-line'}`}
                >
                  <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${t.active ? 'left-[1.4rem]' : 'left-0.5'}`} />
                </button>
              </li>
            ))}
          </ul>
        </GlassCard>
        <GlassCard className="space-y-3 p-5">
          <h2 className="text-xl font-extrabold">Nouvelle tâche</h2>
          <label className="flex flex-col gap-1 text-sm font-medium">Titre de la tâche
            <input value={title} onChange={(e) => setTitle(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2" />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">Fréquence
            <select value={every} onChange={(e) => setEvery(e.target.value)} className="rounded-xl border border-line bg-surface px-3 py-2">
              {FREQUENCIES.map((f) => <option key={f}>{f}</option>)}
            </select>
          </label>
          <PillButton onClick={() => { dispatch({ type: 'add_task', title, every }); setTitle('') }}>Planifier</PillButton>
        </GlassCard>
      </div>
    </>
  )
}
