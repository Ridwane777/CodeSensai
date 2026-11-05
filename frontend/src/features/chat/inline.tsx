import type { ReactNode } from 'react'
import { renderInline, renderRich } from './markdown'

export { renderInline, renderRich }

/**
 * Retire les appels d'outil que le modèle écrit parfois en texte (`<function=…>…</function>`,
 * `<tool_call>`) : l'agent les lit et les exécute (ADR-0031), l'interface les montre déjà comme
 * une étape du raisonnement. Le CLI les masque aussi (`ui.visible_answer`). Un bloc pas encore
 * fermé (réponse en cours) est masqué jusqu'à la fin du texte reçu.
 */
export function visibleAnswer(text: string): string {
  return text
    .replace(/<function=[\s\S]*?(?:<\/function>|$)/g, '')
    .replace(/<\/?tool_call>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s+/, '')
}

/** Markdown minimal pour l'artefact : listes à puces et paragraphes. */
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
