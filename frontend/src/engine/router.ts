import { SCENARIOS } from './scenarios'
import type { Scenario } from './scenarios/types'

/** Order matters: the first scenario with a matching keyword wins. French keywords are kept alongside English ones. */
export const KEYWORDS: [string, string[]][] = [
  ['risky', ['delete', 'remove', 'clean', 'supprim', 'efface', 'nettoie']],
  ['secret', ['api key', 'secret', 'password', '.env', 'cle api', 'mot de passe']],
  ['form', ['deploy', 'configur', 'form', 'deploi', 'formulaire']],
  ['web', ['web', 'internet', 'news', 'online', 'mcp', 'actualite', 'en ligne']],
  ['budget', ['budget', 'context', 'compress', 'cache', 'evaluat', 'contexte', 'evalue']],
  ['wrapup', ['wrap up', 'wrap-up', 'recap', 'summary', 'export', 'share', 'schedul', 'bilan', 'partage', 'planifi']],
  ['fix', ['fix', 'bug', 'error', 'repair', 'function', 'write', 'corrige', 'erreur', 'repare', 'fonction', 'ecris']],
  ['search', ['where is', 'where do', 'where are', 'search', 'find', 'explain', 'login', 'ou est', 'ou verifie', 'ou gere', 'cherche', 'trouve', 'explique']],
  ['resume', ['resume', 'hello', 'session', 'profile', 'reprend', 'bonjour', 'salut', 'profil']],
]

export const SUGGESTIONS: { label: string; text: string; scenario: string }[] = [
  { label: 'Resume the session', text: 'Resume where we left off', scenario: 'resume' },
  { label: 'Search the code', text: 'Where do we check that an unknown session does not crash?', scenario: 'search' },
  { label: 'Write and test', text: 'Write a function that computes the average latency of the log', scenario: 'fix' },
  { label: 'Risky action', text: 'Delete the temporary files in the build/ folder', scenario: 'risky' },
  { label: 'Protect a secret', text: 'Show the API key from my .env file', scenario: 'secret' },
  { label: 'Ask questions', text: 'Prepare a deployment', scenario: 'form' },
  { label: 'Search the web', text: 'Look up the latest pytest version on the web', scenario: 'web' },
  { label: 'Context and cache', text: 'The context is getting long, compress it', scenario: 'budget' },
  { label: 'Wrap up', text: 'Give me a recap of the session', scenario: 'wrapup' },
]

const normalize = (s: string) =>
  s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

export function route(text: string): Scenario {
  const t = normalize(text)
  for (const [id, words] of KEYWORDS) {
    if (words.some((w) => t.includes(w))) return SCENARIOS[id]
  }
  return SCENARIOS.fallback
}
