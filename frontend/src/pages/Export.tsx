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
  // Real server: a real link, created on demand. Demo: a fake link.
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
      <PageHeader title="Export" intro="Keep a record of the session: conversation and state document, as JSON, Markdown or PDF, plus a share link." />
      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <div className="space-y-6">
          <GlassCard className="space-y-3 p-5">
            <h2 className="text-xl font-extrabold">Formats</h2>
            <div className="flex flex-wrap gap-2">
              <PillButton variant="outline" onClick={() => downloadText('codesensai-session.json', 'application/json', toJson(state))}>Export as JSON</PillButton>
              <PillButton variant="outline" onClick={() => downloadText('codesensai-session.md', 'text/markdown', toMarkdown(state))}>Export as Markdown</PillButton>
              <PillButton variant="outline" onClick={printPdf}>Export as PDF</PillButton>
            </div>
            <p className="text-xs text-muted">Full session as seen by the browser: messages, reasoning steps and artifact.</p>
            {exportSession && (
              <>
                <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                  <PillButton variant="outline" onClick={() => void serverExport('json')}>Server conversation (JSON)</PillButton>
                  <PillButton variant="outline" onClick={() => void serverExport('md')}>Server conversation (Markdown)</PillButton>
                </div>
                <p className="text-xs text-muted">The messages saved by sensai-web, with secrets masked by the server.</p>
              </>
            )}
          </GlassCard>
          <GlassCard className="space-y-3 p-5">
            <h2 className="text-xl font-extrabold">Share link</h2>
            {share && (
              <PillButton onClick={create} disabled={busy} arrow={false}>
                {real ? 'Create a new link' : 'Create a share link'}
              </PillButton>
            )}
            {link && (
              <>
                <input readOnly aria-label="Share link" value={link} className="w-full rounded-xl border border-line bg-surface px-3 py-2 font-mono text-xs" />
                <div className="flex flex-wrap gap-2">
                  <PillButton onClick={copy} arrow={false}>{copied ? 'Link copied' : 'Copy the link'}</PillButton>
                  {revokeShare && real && (
                    <PillButton variant="outline" onClick={revoke} disabled={busy} arrow={false}>Revoke the link</PillButton>
                  )}
                </div>
              </>
            )}
            {revoked && <p role="status" className="text-xs font-semibold text-ok">Link revoked: the public page no longer responds.</p>}
            {share ? (
              <p className="text-xs text-muted">
                Read-only copy of the conversation, secrets masked, readable without a token by anyone who can reach this server
                {real ? `; valid until ${real.expiresAt.slice(0, 10)}` : '; valid for 7 days'}.
              </p>
            ) : (
              <p className="text-xs text-muted">Simulated link: no public page is created in this demo.</p>
            )}
          </GlassCard>
        </div>
        <GlassCard className="p-5">
          <h2 className="mb-3 text-xl font-extrabold">Preview</h2>
          <pre id="printable" className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-2xl bg-bg/60 p-4 font-mono text-xs leading-relaxed">{toMarkdown(state)}</pre>
        </GlassCard>
      </div>
    </>
  )
}
