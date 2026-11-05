import type { ReactNode } from 'react'

const KEYWORDS = new Set(['def', 'async', 'await', 'return', 'for', 'in', 'if', 'else', 'with', 'as', 'class', 'yield', 'import', 'assert'])

/** Coloration Python minimale : mots-clés, chaînes, nombres, appels de fonction, commentaires. */
export function highlight(line: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(#.*$)|("[^"]*"?|'[^']*'?)|(\b\d+(?:\.\d+)?\b)|(\b[A-Za-z_]\w*\b)|(\s+)|(.)/g
  let m: RegExpExecArray | null
  let k = 0
  while ((m = re.exec(line))) {
    const [tok, comment, str, num, word] = m
    let cls = ''
    if (comment) cls = 'italic text-[color:var(--code-comment)]'
    else if (str) cls = 'text-[color:var(--code-string)]'
    else if (num) cls = 'text-[color:var(--code-number)]'
    else if (word && KEYWORDS.has(word)) cls = 'font-semibold text-[color:var(--code-keyword)]'
    else if (word && line[re.lastIndex] === '(') cls = 'text-[color:var(--code-fn)]'
    out.push(cls ? <span key={k++} className={cls}>{tok}</span> : tok)
  }
  return out
}
