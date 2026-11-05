import { useState } from 'react'
import { downloadText } from '../export/download'
import { printPdf } from '../export/printPdf'
import { shareLink } from '../export/shareLink'
import { toJson } from '../export/toJson'
import { toMarkdown } from '../export/toMarkdown'
import type { SharedLink } from '../contract/engine'
import { useEngine } from '../state/useEngine'
import { GlassCard } from '../ui/GlassCard'
import { PageHeader } from '../ui/PageHeader'
import { PillButton } from '../ui/PillButton'

export default function Export() {
  const { state, share, revokeShare, exportSession } = useEngine()
  const [copied, setCopied] = useState(false)
  const [real, setReal] = useState<SharedLink | null>(null)
  const [busy, setBusy] = useState(false)
  const [revoked, setRevoked] = useState(false)
  // Serveur réel : un vrai lien, créé à la demande. Démonstration : lien factice.
  const link = share ? real?.url ?? '' : shareLink(state)

  async function create() {
    if (!share) return
    setBusy(true)
    setCopied(false)
    setReal(await share())
    setRevoked(false)
    setBusy(false)
  }

  async function revoke() {
    if (!revokeShare || !real) return
    setBusy(true)
    if (await revokeShare(real.token)) {
      setReal(null)
      setRevoked(true)
    }
    setBusy(false)
  }

  async function serverExport(format: 'json' | 'md') {
    if (!exportSession) return
    const body = await exportSession(format)
    if (body !== null)
      downloadText(`conversation-codesensei.${format}`, format === 'json' ? 'application/json' : 'text/markdown', body)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <>
      <PageHeader title="Export" intro="Garder une trace de la séance : conversation et document de suivi, en JSON, Markdown ou PDF, plus un lien de partage." />
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-6">
          <GlassCard className="space-y-3 p-5">
            <h2 className="text-xl font-extrabold">Formats</h2>
            <div className="flex flex-wrap gap-2">
              <PillButton variant="outline" onClick={() => downloadText('seance-codesensei.json', 'application/json', toJson(state))}>Exporter en JSON</PillButton>
              <PillButton variant="outline" onClick={() => downloadText('seance-codesensei.md', 'text/markdown', toMarkdown(state))}>Exporter en Markdown</PillButton>
              <PillButton variant="outline" onClick={printPdf}>Exporter en PDF</PillButton>
            </div>
            <p className="text-xs text-muted">Séance complète vue par le navigateur : messages, étapes de raisonnement et artefact.</p>
            {exportSession && (
              <>
                <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                  <PillButton variant="outline" onClick={() => void serverExport('json')}>Conversation du serveur (JSON)</PillButton>
                  <PillButton variant="outline" onClick={() => void serverExport('md')}>Conversation du serveur (Markdown)</PillButton>
                </div>
                <p className="text-xs text-muted">Les messages enregistrés par sensai-web, secrets masqués par le serveur.</p>
              </>
            )}
          </GlassCard>
          <GlassCard className="space-y-3 p-5">
            <h2 className="text-xl font-extrabold">Lien de partage</h2>
            {share && (
              <PillButton onClick={create} disabled={busy} arrow={false}>
                {real ? 'Créer un nouveau lien' : 'Créer un lien de partage'}
              </PillButton>
            )}
            {link && (
              <>
                <input readOnly aria-label="Lien de partage" value={link} className="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-xs" />
                <div className="flex flex-wrap gap-2">
                  <PillButton onClick={copy} arrow={false}>{copied ? 'Lien copié' : 'Copier le lien'}</PillButton>
                  {revokeShare && real && (
                    <PillButton variant="outline" onClick={revoke} disabled={busy} arrow={false}>Révoquer le lien</PillButton>
                  )}
                </div>
              </>
            )}
            {revoked && <p role="status" className="text-xs font-semibold text-ok">Lien révoqué : la page publique ne répond plus.</p>}
            {share ? (
              <p className="text-xs text-muted">
                Copie en lecture seule de la conversation, secrets masqués, lisible sans jeton par qui peut joindre ce serveur
                {real ? ` ; valable jusqu'au ${real.expiresAt.slice(0, 10)}` : ' ; valable 7 jours'}.
              </p>
            ) : (
              <p className="text-xs text-muted">Lien simulé : aucune page publique n&apos;est créée dans cette démonstration.</p>
            )}
          </GlassCard>
        </div>
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Aperçu</h2>
          <pre id="printable" className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-2xl bg-bg/60 p-4 font-mono text-xs leading-relaxed">{toMarkdown(state)}</pre>
        </GlassCard>
      </div>
    </>
  )
}
