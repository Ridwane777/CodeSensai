import { PROMPTS } from '../engine/fixtures'

export interface PlanTask {
  id: string
  title: string
  every: string
  active: boolean
}

export interface DemoData {
  prefs: string[]
  tasks: PlanTask[]
  promptActive: Record<string, string>
}

export type DemoAction =
  | { type: 'add_pref'; text: string }
  | { type: 'forget_prefs' }
  | { type: 'add_task'; title: string; every: string }
  | { type: 'toggle_task'; id: string }
  | { type: 'use_prompt'; name: string; version: string }

export const initialDemo: DemoData = {
  prefs: ['answer in English and use pytest'],
  tasks: [
    { id: 't1', title: 'Daily project summary', every: 'every day', active: true },
    { id: 't2', title: 'Weekly review', every: 'every Monday', active: true },
  ],
  promptActive: { system: 'v1', memory: 'v1' },
}

export function demoReducer(s: DemoData, a: DemoAction): DemoData {
  switch (a.type) {
    case 'add_pref': {
      const text = a.text.trim()
      if (!text || s.prefs.includes(text)) return s
      return { ...s, prefs: [...s.prefs, text] }
    }
    case 'forget_prefs':
      return { ...s, prefs: [] }
    case 'add_task': {
      const title = a.title.trim()
      if (!title) return s
      const n = s.tasks.reduce((m, t) => Math.max(m, Number(t.id.slice(1))), 0) + 1
      return { ...s, tasks: [...s.tasks, { id: `t${n}`, title, every: a.every, active: true }] }
    }
    case 'toggle_task':
      return { ...s, tasks: s.tasks.map((t) => (t.id === a.id ? { ...t, active: !t.active } : t)) }
    case 'use_prompt': {
      if (!PROMPTS[a.name]?.some((v) => v.id === a.version)) return s
      return { ...s, promptActive: { ...s.promptActive, [a.name]: a.version } }
    }
  }
}
