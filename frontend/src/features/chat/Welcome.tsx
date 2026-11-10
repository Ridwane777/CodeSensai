import { BrandMark } from '../../ui/FloatingNav'
import { Composer, Suggestions } from './Composer'
import { greeting } from './greeting'
import { useConnection } from '../../state/connection'

/**
 * Chat welcome screen, kept plain: a greeting, the input field in the center and a few quick starts.
 * Nothing to enable and no flashy animation: you can type right away (friction notes from 2026-10-31).
 */
export function Welcome({ now = new Date() }: { now?: Date }) {
  const conn = useConnection()
  const live = conn?.mode === 'live' ? conn.config?.model : null
  return (
    <section
      className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-3xl flex-col justify-center gap-8 py-10"
      aria-label="Conversation welcome"
    >
      <div className="fade-up flex flex-col items-center gap-4 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-soft text-accent" aria-hidden="true">
          <BrandMark className="h-6 w-6" />
        </span>
        <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">
          {greeting(now)}, I am <span className="text-accent">CodeSensai</span>.
        </h1>
        <p className="max-w-xl text-muted">
          I read your project, reason out loud and ask for your approval before acting.
        </p>
        <p className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs font-medium text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
          {live ? `Real agent · ${live}` : 'Simulated engine'}
        </p>
      </div>
      <div className="fade-up" style={{ animationDelay: '120ms' }}>
        <Composer autoFocus />
      </div>
      <div className="fade-up" style={{ animationDelay: '220ms' }}>
        <Suggestions />
      </div>
    </section>
  )
}
