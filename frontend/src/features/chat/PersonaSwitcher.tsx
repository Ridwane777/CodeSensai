import { useEffect, useState } from 'react'
import type { PersonaInfo } from '../../contract/engine'
import { useEngine } from '../../state/useEngine'
import { PERSONA_LABEL } from '../../ui/personas'

/**
 * « Agent actif ». Serveur réel (A5, ADR-0054) : les personas de config.json, choisies pour la
 * conversation affichée ; démonstration : les deux profils simulés.
 */
export function PersonaSwitcher({ persona }: { persona: string }) {
  const { switchPersona, listPersonas } = useEngine()
  const [real, setReal] = useState<PersonaInfo[] | null>(null)

  useEffect(() => {
    if (!listPersonas) return
    let alive = true
    void listPersonas().then((list) => {
      if (!alive || !list) return
      // Le nom de la persona s'affiche sur les tours de l'agent.
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
        title={current?.toolsDisabled.length ? `Outils désactivés : ${current.toolsDisabled.join(', ')}` : undefined}
        className="rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-semibold"
      >
        {options.map(([id, label]) => (
          <option key={id} value={id}>{label}</option>
        ))}
      </select>
    </label>
  )
}
