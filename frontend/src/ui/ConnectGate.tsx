import { useState, type FormEvent } from 'react'
import { useConnection } from '../state/connection'
import { GlassCard } from './GlassCard'
import { PillButton } from './PillButton'

/** Écran affiché tant que l'interface ne sait pas à quel moteur parler (ADR-0035). */
export function ConnectGate() {
  const conn = useConnection()
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!conn || conn.mode === 'checking') {
    return (
      <main className="grid min-h-screen place-items-center px-4">
        <p className="text-muted" role="status">Recherche du serveur CodeSensei…</p>
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
        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Connexion à CodeSensei</h1>
        <p className="mt-2 text-sm text-muted">
          Collez le jeton affiché dans le terminal au démarrage de <code>sensai-web</code>. Il change à chaque
          démarrage et reste dans cet onglet.
        </p>
        <form className="mt-6 flex flex-col gap-3" onSubmit={submit}>
          <label className="text-sm font-semibold text-ink" htmlFor="sensai-token">
            Jeton d'accès
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
            Se connecter
          </PillButton>
          <PillButton variant="outline" arrow={false} onClick={() => conn.chooseDemo()}>
            Continuer en démonstration (moteur simulé)
          </PillButton>
        </form>
      </GlassCard>
    </main>
  )
}
