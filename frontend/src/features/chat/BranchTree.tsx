import { useEngine } from '../../state/useEngine'

export function BranchTree() {
  const { state, switchBranch } = useEngine()
  const ids = ['main', ...Object.keys(state.branches)]
  if (ids.length < 2) return null
  return (
    <nav aria-label="Branches de la conversation" className="mb-4 flex flex-wrap items-center gap-2 text-sm">
      <span className="font-semibold text-muted">Versions</span>
      {ids.map((b, i) => (
        <button
          key={b}
          type="button"
          aria-label={b === 'main' ? 'Branche principale' : `Variante ${i}`}
          aria-pressed={state.activeBranch === b}
          onClick={() => switchBranch(b)}
          className={`rounded-full border px-3 py-1 font-medium ${
            state.activeBranch === b ? 'border-accent-strong bg-accent-soft' : 'border-line hover:bg-accent-soft'
          }`}
        >
          {b === 'main' ? 'Principale' : `Variante ${i}`}
        </button>
      ))}
    </nav>
  )
}
