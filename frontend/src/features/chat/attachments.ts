/**
 * Fichiers joints au message (glisser-déposer ou trombone) : lus dans le navigateur et ajoutés
 * au texte envoyé, dans un bloc de code. Seulement du texte : un PDF ou un .docx passerait par
 * la conversion de documents du serveur, que le web n'expose pas encore.
 *
 * Le serveur refuse un message de plus de 20 000 caractères (MAX_MESSAGE_CHARS) : la limite est
 * vérifiée ici, avant l'envoi, pour donner un message clair.
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

/** Lit des fichiers ; renvoie ceux qui sont lisibles et un message pour les autres. */
export async function readAttachments(files: File[]): Promise<{ ok: Attachment[]; errors: string[] }> {
  const ok: Attachment[] = []
  const errors: string[] = []
  for (const file of files) {
    if (!isSupported(file.name)) {
      errors.push(`${file.name} : seuls les fichiers texte (code, Markdown, JSON…) peuvent être joints.`)
      continue
    }
    if (file.size > MAX_MESSAGE_CHARS * 4) {
      errors.push(`${file.name} : trop gros pour un message (${Math.round(file.size / 1024)} Ko).`)
      continue
    }
    const text = await file.text()
    if (text.includes('\u0000')) {
      errors.push(`${file.name} : ce n'est pas un fichier texte.`)
      continue
    }
    ok.push({ name: file.name, lang: LANG[extensionOf(file.name)], text })
  }
  return { ok, errors }
}

/** Le message envoyé : le texte tapé, puis chaque fichier dans un bloc de code. */
export function withAttachments(text: string, files: Attachment[]): string {
  const blocks = files.map((f) => `Fichier joint : ${f.name}\n\`\`\`${f.lang}\n${f.text.replace(/\n$/, '')}\n\`\`\``)
  return [text.trim(), ...blocks].filter(Boolean).join('\n\n')
}
