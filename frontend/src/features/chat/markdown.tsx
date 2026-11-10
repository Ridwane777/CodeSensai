import { Fragment, useState, type ReactNode } from 'react'
import { highlight } from '../code/syntax'

/**
 * Hand-written Markdown for model answers (no dependency): headings, lists, quotes,
 * highlighted code blocks with a "Copy" button, bold, italic, `code` and links.
 * Never raw HTML: everything goes through React, so everything is escaped. A link is clickable
 * only if it starts with http(s):// (no `javascript:`).
 */

const PY_LIKE = new Set(['', 'py', 'python', 'python3', 'sh', 'bash', 'shell', 'console'])

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  const lines = code.split('\n')
  return (
    <div className="my-2 overflow-hidden rounded-xl bg-accent-soft">
      <div className="flex items-center justify-between px-3 pt-1.5 font-mono text-[11px] text-muted">
        <span>{lang || 'code'}</span>
        <button type="button" onClick={copy} className="rounded px-1.5 py-0.5 hover:text-ink" aria-label="Copy code">
          {copied ? '✓ Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 pt-1 font-mono text-[0.85em] leading-snug">
        <code data-lang={lang || undefined}>
          {PY_LIKE.has(lang.toLowerCase())
            ? lines.map((l, i) => (
                <Fragment key={i}>
                  {highlight(l)}
                  {i < lines.length - 1 && '\n'}
                </Fragment>
              ))
            : code}
        </code>
      </pre>
    </div>
  )
}

const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)|(?<![*\w])\*[^*\s][^*]*\*(?![*\w]))/g

/** Bold, italic, `code` and links within a line. */
export function renderInline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (!part) return null
    if (part.startsWith('`') && part.endsWith('`') && part.length > 1)
      return <code key={i} className="rounded bg-accent-soft px-1 py-0.5 font-mono text-[0.9em]">{part.slice(1, -1)}</code>
    if (part.startsWith('**') && part.endsWith('**') && part.length > 3) return <strong key={i}>{part.slice(2, -2)}</strong>
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part)
    if (link) {
      return /^https?:\/\//i.test(link[2]) ? (
        <a key={i} href={link[2]} target="_blank" rel="noopener noreferrer nofollow" className="font-semibold text-accent underline">
          {link[1]}
        </a>
      ) : (
        link[1]
      )
    }
    if (part.length > 2 && part.startsWith('*') && part.endsWith('*')) return <em key={i}>{part.slice(1, -1)}</em>
    return part
  })
}

/** Text outside code blocks: headings, lists, quotes and paragraphs. */
function renderBlocks(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  let para: string[] = []
  const key = () => `${keyBase}-${out.length}`
  const flushPara = () => {
    if (para.length) {
      out.push(<p key={key()} className="my-1.5 whitespace-pre-wrap">{renderInline(para.join('\n'))}</p>)
      para = []
    }
  }
  const flushList = () => {
    if (!list) return
    const items = list.items.map((it, i) => <li key={i}>{renderInline(it)}</li>)
    out.push(
      list.ordered ? (
        <ol key={key()} className="my-1.5 list-decimal space-y-0.5 pl-6">{items}</ol>
      ) : (
        <ul key={key()} className="my-1.5 list-disc space-y-0.5 pl-6">{items}</ul>
      ),
    )
    list = null
  }
  for (const line of text.split('\n')) {
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const quote = /^>\s?(.*)$/.exec(line)
    if (heading) {
      flushPara()
      flushList()
      const size = ['text-xl', 'text-lg', 'text-base', 'text-base'][heading[1].length - 1]
      out.push(<p key={key()} role="heading" aria-level={heading[1].length + 1} className={`mb-1 mt-3 font-extrabold ${size}`}>{renderInline(heading[2])}</p>)
    } else if (bullet || numbered) {
      flushPara()
      const ordered = !bullet
      if (list && list.ordered !== ordered) flushList()
      list ??= { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
    } else if (quote) {
      flushPara()
      flushList()
      out.push(<blockquote key={key()} className="my-1.5 border-l-2 border-accent pl-3 text-muted">{renderInline(quote[1])}</blockquote>)
    } else if (!line.trim()) {
      flushPara()
      flushList()
    } else {
      flushList()
      para.push(line)
    }
  }
  flushPara()
  flushList()
  return out
}

/**
 * Model answer: code blocks (even not yet closed while streaming), then the rest as Markdown.
 */
export function renderRich(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const fence = /```([\w+.#-]*)[^\n]*\n?([\s\S]*?)(?:```|$)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = fence.exec(text)) !== null) {
    if (m.index > last) out.push(...renderBlocks(text.slice(last, m.index), `t${out.length}`))
    out.push(<CodeBlock key={`c${out.length}`} lang={m[1]} code={m[2].replace(/\n$/, '')} />)
    last = fence.lastIndex
    if (last >= text.length) break
  }
  if (last < text.length) out.push(...renderBlocks(text.slice(last), `t${out.length}`))
  return out
}
