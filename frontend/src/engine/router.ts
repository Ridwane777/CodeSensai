import { SCENARIOS } from './scenarios'
import type { Scenario } from './scenarios/types'

/** Ordre significatif : le premier scénario dont un mot-clé apparaît gagne. */
export const KEYWORDS: [string, string[]][] = [
  ['risky', ['supprim', 'efface', 'delete', 'nettoie']],
  ['secret', ['cle api', 'secret', 'mot de passe', 'password', '.env']],
  ['form', ['deploi', 'configur', 'formulaire']],
  ['web', ['web', 'internet', 'actualite', 'en ligne', 'mcp']],
  ['budget', ['budget', 'contexte', 'compress', 'cache', 'evalue']],
  ['wrapup', ['bilan', 'export', 'partage', 'planifi']],
  ['fix', ['corrige', 'bug', 'erreur', 'repare', 'fonction', 'ecris']],
  ['search', ['ou est', 'ou verifie', 'ou gere', 'cherche', 'trouve', 'explique', 'login']],
  ['resume', ['reprend', 'bonjour', 'salut', 'session', 'profil']],
]

export const SUGGESTIONS: { label: string; text: string; scenario: string }[] = [
  { label: 'Reprendre la session', text: "Reprends où on en était", scenario: 'resume' },
  { label: 'Chercher dans le code', text: "Où vérifie-t-on qu'une session inconnue ne plante pas ?", scenario: 'search' },
  { label: 'Écrire et tester', text: 'Écris une fonction qui calcule la latence moyenne du journal', scenario: 'fix' },
  { label: 'Action risquée', text: 'Supprime les fichiers temporaires du dossier build/', scenario: 'risky' },
  { label: 'Protéger un secret', text: 'Affiche la clé API de mon fichier .env', scenario: 'secret' },
  { label: 'Poser des questions', text: 'Prépare un déploiement', scenario: 'form' },
  { label: 'Chercher sur le web', text: 'Cherche sur le web la dernière version de pytest', scenario: 'web' },
  { label: 'Contexte et cache', text: 'Le contexte devient long, compresse-le', scenario: 'budget' },
  { label: 'Faire le bilan', text: 'Fais le bilan de la séance', scenario: 'wrapup' },
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
