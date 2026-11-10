import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useConnection } from '../../state/connection'
import { useEngine } from '../../state/useEngine'

/**
 * Landing hero, a full-screen stage (light or dark depending on the theme): a huge watermark name, a single centered field to
 * ask the first question, a glow of light on the right. No image, no card, nothing moves
 * except the slowly breathing glow (feedback from Christopher on 2026-10-31: “more room”).
 */
export function LandingHero() {
  const conn = useConnection()
  const live = conn?.mode === 'live' ? conn.config : null
  const { send } = useEngine()
  const navigate = useNavigate()
  const [value, setValue] = useState('')

  function start(text: string) {
    const clean = text.trim()
    if (!clean) return
    send(clean)
    navigate('/chat')
  }

  return (
    <section aria-labelledby="hero-titre" className="stage flex min-h-[100svh] flex-col px-5 pb-8 pt-16 sm:px-10 lg:pt-8">
      <div className="stage-stars" aria-hidden="true" />
      <div className="stage-aura" aria-hidden="true" />

      <p className="stage-label inline-flex w-fit items-center gap-2 self-end rounded-full px-3.5 py-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${live ? 'bg-ok' : 'bg-accent'}`} aria-hidden="true" />
        {live ? `Real agent · ${live.model}` : 'Demo · simulated engine'}
      </p>

      <div className="flex flex-1 flex-col items-center justify-center">
        <h1 id="hero-titre" className="fade-up select-none text-center">
          <span className="wordmark block">CodeSensai</span>
          <span className="sr-only">, a developer agent that thinks out loud</span>
        </h1>

        <form
          className="stage-input fade-up relative z-10 mt-4 sm:-mt-[6cqw] flex w-full max-w-xl items-center gap-2 rounded-full py-2 pl-6 pr-2"
          style={{ animationDelay: '120ms' }}
          onSubmit={(e) => {
            e.preventDefault()
            start(value)
          }}
        >
          <input
            aria-label="First question"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Ask anything about your code…"
            className="min-w-0 flex-1 bg-transparent py-2 text-[15px] outline-none focus-visible:outline-none"
          />
          <button
            type="submit"
            aria-label="Send"
            disabled={!value.trim()}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full stage-send transition-opacity duration-200 disabled:opacity-30"
          >
            <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 10h12M11 5l5 5-5 5" />
            </svg>
          </button>
        </form>
      </div>

      <div className="relative z-10 grid items-end gap-6 sm:grid-cols-[auto_1fr_auto]">
        <a href="#parcours" aria-label="See more" className="stage-muted hidden transition-colors sm:block">
          <svg viewBox="0 0 20 20" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M10 3v14M5 12l5 5 5-5" />
          </svg>
        </a>
        <p className="max-w-md stage-text text-[15px] leading-relaxed sm:justify-self-center">
          A developer agent that reads your project, reasons out loud, tests its code in a sandbox and asks for
          approval before acting.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link to="/chat" className="stage-pill">
            {live ? 'Open the chat' : 'Start the demo'}
          </Link>
          <a href="#parcours" className="stage-pill">
            28 features
          </a>
        </div>
      </div>
    </section>
  )
}
