import { end, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const budget: Scenario = {
  id: 'budget',
  steps: [
    start(T),
    { delay: 150, event: { type: 'usage', used: 6900, budget: 8192, contextPct: 84 } },
    think(T, 's1', 'Le contexte approche de la limite (84 %) : je résume les plus anciens tours pour libérer de la place.'),
    { delay: 300, event: { type: 'compression', savedTokens: 1840 } },
    { delay: 150, event: { type: 'usage', used: 5060, budget: 8192, contextPct: 62 } },
    { delay: 300, event: { type: 'cache_hit', similarity: 0.94 } },
    ...say(
      T,
      "J'ai condensé les anciens échanges en un bloc de synthèse (1 840 tokens libérés) en gardant les faits importants. Cette question ressemblait à une précédente à 94 % : j'ai répondu depuis le cache, sans solliciter le modèle.",
    ),
    { delay: 200, event: { type: 'eval_score', relevance: 0.91, faithfulness: 0.88 } },
    end(T),
  ],
}
