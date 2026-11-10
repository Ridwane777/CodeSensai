import { useState } from 'react'
import { BranchTree } from '../features/chat/BranchTree'
import { Composer } from '../features/chat/Composer'
import { MessageList } from '../features/chat/MessageList'
import { PersonaSwitcher } from '../features/chat/PersonaSwitcher'
import { SidePanel } from '../features/chat/SidePanel'
import { StatusBar } from '../features/chat/StatusBar'
import { Welcome } from '../features/chat/Welcome'
import { useConnection } from '../state/connection'
import { useEngine } from '../state/useEngine'
import { visibleTimeline } from '../state/store'

const PANEL_KEY = 'codesensei.panel'

function readPanel(): boolean {
  try {
    return localStorage.getItem(PANEL_KEY) === 'open'
  } catch {
    return false
  }
}

/**
 * The conversation takes the full usable width; the Artifact / Sources panel is collapsed by default
 * and opens on demand, so as not to show everything at once (friction notes from 2026-10-31).
 */
export default function Chat() {
  const { state, listPersonas, setPromptTrial } = useEngine()
  // Real server: the switcher only appears if sensai-web exposes the personas (A5, ADR-0054).
  const live = useConnection()?.mode === 'live'
  const showPersonas = !live || Boolean(listPersonas)
  const [panel, setPanel] = useState(readPanel)
  const items = visibleTimeline(state, state.activeBranch)
  if (state.timeline.length === 0) return <Welcome />

  const saved = state.timeline.reduce((n, i) => (i.kind === 'compression' ? n + i.savedTokens : n), 0)
  const hasPanelContent = Object.keys(state.artifact).length > 0 || state.sources.length > 0 || state.web.length > 0
  const toggle = () => {
    setPanel((open) => {
      try {
        localStorage.setItem(PANEL_KEY, open ? 'closed' : 'open')
      } catch {
        /* storage unavailable: the choice will not be remembered */
      }
      return !open
    })
  }

  return (
    <div className="flex gap-6">
      <div className="flex min-h-[calc(100vh-4rem)] min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-10 -mx-2 flex flex-wrap items-center gap-3 chat-toolbar px-2 py-3">
          {showPersonas && <PersonaSwitcher persona={state.persona} />}
          {state.promptTrial && (
            <span data-testid="prompt-trial-badge" className="flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-xs font-bold">
              system prompt {state.promptTrial} (trial run)
              {setPromptTrial && (
                <button
                  type="button"
                  onClick={() => void setPromptTrial(null)}
                  aria-label="Back to the active prompt version"
                  className="rounded-full border border-line px-2 py-0.5 font-semibold hover:border-accent"
                >
                  back to active
                </button>
              )}
            </span>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={toggle}
            aria-pressed={panel}
            aria-label={panel ? 'Hide the Artifact and Sources panel' : 'Show the Artifact and Sources panel'}
            className="relative rounded-full border border-line px-3 py-1.5 text-sm font-medium text-muted transition-colors duration-200 hover:border-accent hover:text-ink"
          >
            {panel ? 'Hide the panel' : 'Artifact · Sources'}
            {!panel && hasPanelContent && (
              <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-accent" aria-hidden="true" />
            )}
          </button>
        </div>
        <div className="mx-auto w-full max-w-4xl flex-1">
          <BranchTree />
          <MessageList items={items} />
        </div>
        <div className="composer-dock sticky bottom-0 -mx-2 px-2 pb-4 pt-8">
          <div className="mx-auto w-full max-w-4xl">
            {state.error && (
              <p role="alert" className="rise-in mb-2 rounded-2xl border border-danger bg-surface-solid px-4 py-2 text-sm text-danger">
                {state.error}
              </p>
            )}
            <Composer footer={<StatusBar usage={state.usage} saved={saved} />} />
          </div>
        </div>
      </div>
      {panel && (
        // A single panel: a drawer over the conversation on small screens, a right-hand column on large screens.
        <div
          className="fixed inset-0 z-50 flex justify-end bg-black/50 lg:static lg:z-auto lg:block lg:w-[24rem] lg:shrink-0 lg:bg-transparent lg:pt-3"
          onClick={toggle}
        >
          <div
            className="rise-in h-full w-[min(24rem,90vw)] overflow-y-auto bg-surface p-3 lg:sticky lg:bg-transparent lg:top-3 lg:h-auto lg:w-full lg:overflow-visible lg:p-0"
            onClick={(e) => e.stopPropagation()}
          >
            <SidePanel state={state} />
          </div>
        </div>
      )}
    </div>
  )
}
