/**
 * Files attached to the message (drag and drop or paperclip): read in the browser and appended
 * to the sent text, in a code block. Text only: a PDF or a .docx would need the server's
 * document conversion, which the web UI does not expose yet.
 *
 * The server rejects messages over 20,000 characters (MAX_MESSAGE_CHARS): the limit is
 * checked here, before sending, to give a clear message.
 */

export const MAX_MESSAGE_CHARS = 20_000
export const MAX_FILES = 3

const LANG: Record<string, string> = {
  py: 'python', js: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx', json: 'json', md: 'markdown',
  txt: '', yaml: 'yaml', yml: 'yaml', toml: 'toml', csv: 'csv', html: 'html', css: 'css', sh: 'bash',
  ini: 'ini', cfg: 'ini', rs: 'rust', go: 'go', java: 'java', c: 'c', h: 'c', cpp: 'cpp', sql: 'sql', log: '',
}

export interface Attachment {
  name: string
  lang: string
  text: string
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : ''
}

export function isSupported(name: string): boolean {
  return extensionOf(name) in LANG
}

/** Reads files; returns the readable ones and a message for the others. */
export async function readAttachments(files: File[]): Promise<{ ok: Attachment[]; errors: string[] }> {
  const ok: Attachment[] = []
  const errors: string[] = []
  for (const file of files) {
    if (!isSupported(file.name)) {
      errors.push(`${file.name}: only text files (code, Markdown, JSON…) can be attached.`)
      continue
    }
    if (file.size > MAX_MESSAGE_CHARS * 4) {
      errors.push(`${file.name}: too large for a message (${Math.round(file.size / 1024)} KB).`)
      continue
    }
    const text = await file.text()
    if (text.includes('\u0000')) {
      errors.push(`${file.name}: not a text file.`)
      continue
    }
    ok.push({ name: file.name, lang: LANG[extensionOf(file.name)], text })
  }
  return { ok, errors }
}

/** The sent message: the typed text, then each file in a code block. */
export function withAttachments(text: string, files: Attachment[]): string {
  const blocks = files.map((f) => `Fichier joint : ${f.name}\n\`\`\`${f.lang}\n${f.text.replace(/\n$/, '')}\n\`\`\``)
  return [text.trim(), ...blocks].filter(Boolean).join('\n\n')
}
