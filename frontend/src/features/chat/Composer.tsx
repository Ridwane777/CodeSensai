import { useEffect, useRef, useState, type ReactNode } from 'react'
import { SUGGESTIONS } from '../../engine/router'
import { useConnection } from '../../state/connection'
import { useEngine } from '../../state/useEngine'
import { PillButton } from '../../ui/PillButton'
import { MAX_FILES, MAX_MESSAGE_CHARS, readAttachments, withAttachments, type Attachment } from './attachments'

/** Starter questions for the real agent: they are about the project opened by sensai-web. */
export const STARTERS = [
  'Explain the structure of this project',
  'Find and fix a bug in the code',
  'Write tests for a function',
  'Summarize the latest project decisions',
]

export function Suggestions() {
  const { send } = useEngine()
  // With the real server, no demo scenarios: questions about the project.
  const live = useConnection()?.mode === 'live'
  const items = live ? STARTERS.map((t) => ({ key: t, label: t, text: t })) : SUGGESTIONS.map((s) => ({ key: s.scenario, label: s.label, text: s.text }))
  return (
    <div className="flex flex-wrap justify-center gap-2" aria-label="Suggestions">
      {items.map((s) => (
        <button
          key={s.key}
          type="button"
          onClick={() => send(s.text)}
          className="rounded-full border border-line bg-surface/70 px-3.5 py-1.5 text-[13px] font-medium text-muted transition-colors duration-200 hover:border-accent hover:bg-accent-soft hover:text-ink"
        >
          {s.label}
        </button>
      ))}
    </div>
  )
}

/** Input area; `footer` renders under the help line (chat context bar). */
export function Composer({ autoFocus = false, footer }: { autoFocus?: boolean; footer?: ReactNode }) {
  const { send, interrupt, state } = useEngine()
  const [value, setValue] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)
  // The field grows with the text (up to max-h-60), then scrolls.
  useEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [value])
  const [files, setFiles] = useState<Attachment[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  const empty = value.trim() === '' && files.length === 0

  async function attach(list: FileList | null) {
    if (!list?.length) return
    const room = MAX_FILES - files.length
    const picked = Array.from(list).slice(0, Math.max(room, 0))
    const { ok, errors } = await readAttachments(picked)
    if (list.length > room) errors.push(`At most ${MAX_FILES} files per message.`)
    setFiles((f) => [...f, ...ok])
    setNote(errors.length ? errors.join(' ') : null)
  }

  function submit() {
    if (empty) return
    const message = withAttachments(value, files)
    if (message.length > MAX_MESSAGE_CHARS) {
      setNote(`Message too long (${message.length} characters, ${MAX_MESSAGE_CHARS} max): remove a file or shorten it.`)
      return
    }
    send(message)
    setValue('')
    setFiles([])
    setNote(null)
  }

  return (
    <div>
    {(files.length > 0 || note) && (
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        {files.map((f, i) => (
          <span key={`${f.name}-${i}`} className="glass flex items-center gap-1 rounded-full px-3 py-1 font-mono">
            📎 {f.name}
            <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((l) => l.filter((_, j) => j !== i))} className="ml-1 text-muted hover:text-danger">✕</button>
          </span>
        ))}
        {note && <span role="status" className="text-warn">{note}</span>}
      </div>
    )}
    <form
      className={`code-card relative flex items-end gap-3 overflow-hidden rounded-3xl p-3 transition-shadow duration-300 focus-within:ring-1 focus-within:ring-accent/40 ${dragging ? 'ring-2 ring-accent' : ''}`}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        void attach(e.dataTransfer.files)
      }}
    >
      <span className="mb-2.5 ml-2 shrink-0 select-none font-mono text-sm text-accent" aria-hidden="true">
        <span className="hidden text-[color:var(--code-muted)] sm:inline">~/projet </span>❯
      </span>
      <textarea
        ref={area}
        autoFocus={autoFocus}
        aria-label="Message"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && state.thinking) {
            e.preventDefault()
            interrupt()
            return
          }
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder="Ask CodeSensai something…"
        rows={1}
        className="relative max-h-60 min-h-[2.75rem] flex-1 resize-none bg-transparent focus-visible:outline-none px-1 py-2.5 font-mono text-[14px] text-[color:var(--code-text)] outline-none placeholder:text-[color:var(--code-muted)]"
      />
      <input
        ref={picker}
        type="file"
        multiple
        hidden
        aria-label="Files to attach"
        onChange={(e) => {
          void attach(e.target.files)
          e.target.value = ''
        }}
      />
      <button
        type="button"
        onClick={() => picker.current?.click()}
        aria-label="Attach a file"
        title="Attach a text file (or drop it here)"
        className="mb-1.5 shrink-0 rounded-full px-2 py-1 text-lg text-[color:var(--code-muted)] hover:text-accent"
      >
        📎
      </button>
      {state.thinking && (
        <PillButton variant="outline" onClick={interrupt} arrow={false} aria-label="Stop the answer (Esc)" title="Esc">
          ■ Stop
        </PillButton>
      )}
      <PillButton type="submit" disabled={empty}>Send</PillButton>
    </form>
    <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-2 text-[11px] text-muted">
      <span>
        <kbd className="font-sans font-semibold">Enter</kbd> to send · <kbd className="font-sans font-semibold">Shift+Enter</kbd> new line
        {state.thinking && <> · <kbd className="font-sans font-semibold">Esc</kbd> to stop</>}
      </span>
      {footer}
    </div>
    </div>
  )
}
