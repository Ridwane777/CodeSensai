import { pct } from '../../ui/format'

export function SourcesPanel({
  sources,
  web,
}: {
  sources: { path: string; lines: string; score: number }[]
  web: { title: string; url: string }[]
}) {
  if (sources.length === 0 && web.length === 0) return <p className="text-sm text-muted">Aucune source pour l&apos;instant.</p>
  return (
    <div className="space-y-4 text-sm">
      {sources.length > 0 && (
        <section aria-label="Passages du projet">
          <h3 className="mb-2 font-extrabold">Dans le projet</h3>
          <ul className="space-y-2">
            {sources.map((s) => (
              <li key={`${s.path}:${s.lines}`} className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2">
                <code className="break-all font-mono text-xs">{`${s.path}:${s.lines}`}</code>
                <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold">{pct(s.score)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {web.length > 0 && (
        <section aria-label="Résultats web">
          <h3 className="mb-2 font-extrabold">Sur le web</h3>
          <ul className="space-y-2">
            {web.map((w) => (
              <li key={w.url}>
                <a href={w.url} target="_blank" rel="noopener noreferrer" className="block rounded-xl border border-line px-3 py-2 hover:bg-accent-soft">
                  <span className="font-semibold">{w.title}</span>
                  <span className="block break-all text-xs text-muted">{w.url}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
