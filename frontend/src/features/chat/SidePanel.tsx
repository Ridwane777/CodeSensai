import { useState } from 'react'
import type { UiState } from '../../state/store'
import { ArtifactPanel } from './ArtifactPanel'
import { SourcesPanel } from './SourcesPanel'

const TABS = [
  { id: 'artefact', label: 'Artefact' },
  { id: 'sources', label: 'Sources' },
] as const

export function SidePanel({ state }: { state: UiState }) {
  const [tab, setTab] = useState<(typeof TABS)[number]['id']>('artefact')
  return (
    <aside className="glass rounded-3xl p-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto" aria-label="Panneau latéral">
      <div role="tablist" className="mb-3 flex gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setTab(t.id)}
            className={`rounded-full px-3 py-1.5 text-sm font-semibold ${tab === t.id ? 'bg-accent-soft' : 'text-muted hover:text-ink'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === 'artefact' ? (
          <ArtifactPanel sections={state.artifact} lastPatched={state.lastPatched} />
        ) : (
          <SourcesPanel sources={state.sources} web={state.web} />
        )}
      </div>
    </aside>
  )
}
