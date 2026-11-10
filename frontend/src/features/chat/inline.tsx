import type { ReactNode } from 'react'
import { renderInline, renderRich } from './markdown'

export { renderInline, renderRich }

/**
 * Removes tool calls that the model sometimes writes as text (`<function=…>…</function>`,
 * `<tool_call>`): the agent reads and runs them (ADR-0031), and the UI already shows them as a
 * reasoning step. The CLI hides them too (`ui.visible_answer`). A block not yet closed (answer
 * in progress) is hidden up to the end of the received text.
 */
export function visibleAnswer(text: string): string {
  return text
    .replace(/<function=[\s\S]*?(?:<\/function>|$)/g, '')
    .replace(/<\/?tool_call>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s+/, '')
}

/** Minimal Markdown for the artifact: bullet lists and paragraphs. */
export function renderMarkdown(md: string): ReactNode {
  const out: ReactNode[] = []
  let bullets: string[] = []
  const flush = () => {
    if (bullets.length) {
      out.push(
        <ul key={`u${out.length}`} className="list-disc space-y-1 pl-5">
          {bullets.map((b, i) => <li key={i}>{renderInline(b)}</li>)}
        </ul>,
      )
      bullets = []
    }
  }
  for (const line of md.split('\n')) {
    if (line.startsWith('- ')) bullets.push(line.slice(2))
    else if (line.trim()) {
      flush()
      out.push(<p key={`p${out.length}`}>{renderInline(line)}</p>)
    }
  }
  flush()
  return out
}
