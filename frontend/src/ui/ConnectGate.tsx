import { useState, type FormEvent } from 'react'
import { useConnection } from '../state/connection'
import { GlassCard } from './GlassCard'
import { PillButton } from './PillButton'

/** Screen shown while the interface does not know which engine to talk to (ADR-0035). */
export function ConnectGate() {
  const conn = useConnection()
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!conn || conn.mode === 'checking') {
    return (
      <main className="grid min-h-screen place-items-center px-4">
        <p className="text-muted" role="status">Looking for the CodeSensai server…</p>
      </main>
    )
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!conn) return
    setBusy(true)
    setError(await conn.login(token))
    setBusy(false)
  }

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <GlassCard className="w-full max-w-md p-8">
        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Connect to CodeSensai</h1>
        <p className="mt-2 text-sm text-muted">
          Paste the token printed in the terminal when <code>sensai-web</code> starts. It changes on every
          start and stays in this tab.
        </p>
        <form className="mt-6 flex flex-col gap-3" onSubmit={submit}>
          <label className="text-sm font-semibold text-ink" htmlFor="sensai-token">
            Access token
          </label>
          <input
            id="sensai-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="rounded-2xl border border-line bg-surface px-4 py-2.5 text-ink"
          />
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <PillButton type="submit" disabled={busy}>
            Connect
          </PillButton>
          <PillButton variant="outline" arrow={false} onClick={() => conn.chooseDemo()}>
            Continue in demo mode (simulated engine)
          </PillButton>
        </form>
      </GlassCard>
    </main>
  )
}
