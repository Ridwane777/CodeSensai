import { useEffect, useState } from 'react'
import type { PersonaInfo } from '../../contract/engine'
import { useEngine } from '../../state/useEngine'
import { PERSONA_LABEL } from '../../ui/personas'

/**
 * "Active agent". Real server (A5, ADR-0054): the personas from config.json, selected for the
 * displayed conversation; demo: the two simulated profiles.
 */
export function PersonaSwitcher({ persona }: { persona: string }) {
  const { switchPersona, listPersonas } = useEngine()
  const [real, setReal] = useState<PersonaInfo[] | null>(null)

  useEffect(() => {
    if (!listPersonas) return
    let alive = true
    void listPersonas().then((list) => {
      if (!alive || !list) return
      // The persona name is shown on the agent's turns.
      for (const p of list) PERSONA_LABEL[p.id] = p.name
      setReal(list)
    })
    return () => {
      alive = false
    }
  }, [listPersonas])

  const options = real ? real.map((p) => [p.id, p.name] as const) : Object.entries(PERSONA_LABEL)
  const current = real?.find((p) => p.id === persona)
  return (
    <label className="flex items-center gap-2 text-xs font-bold">
      Agent actif
      <select
        value={persona}
        onChange={(e) => switchPersona(e.target.value)}
        title={current?.toolsDisabled.length ? `Disabled tools: ${current.toolsDisabled.join(', ')}` : undefined}
        className="rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-semibold"
      >
        {options.map(([id, label]) => (
          <option key={id} value={id}>{label}</option>
        ))}
      </select>
    </label>
  )
}
