import { renderMarkdown } from './inline'

export function ArtifactPanel({ sections, lastPatched }: { sections: Record<string, string>; lastPatched: string | null }) {
  const names = Object.keys(sections)
  if (names.length === 0)
    return <p className="text-sm text-muted">Aucun document pour l&apos;instant : l&apos;agent en crée un quand il travaille sur une tâche.</p>
  return (
    <div className="space-y-3">
      {names.map((name) => {
        const fresh = name === lastPatched
        return (
          <section
            key={name}
            data-fresh={fresh ? 'true' : 'false'}
            className={`rounded-2xl border p-3 text-sm transition-colors ${fresh ? 'border-accent-strong bg-accent-soft' : 'border-line'}`}
          >
            <div className="mb-1 flex items-center gap-2">
              <h3 className="font-extrabold">{name}</h3>
              {fresh && <span className="rounded-full bg-accent-strong px-2 py-0.5 text-[10px] font-bold text-accent-contrast">modifié</span>}
            </div>
            <div className="space-y-1">{renderMarkdown(sections[name])}</div>
          </section>
        )
      })}
    </div>
  )
}
