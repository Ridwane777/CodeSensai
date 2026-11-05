import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const search: Scenario = {
  id: 'search',
  steps: [
    start(T),
    think(T, 's1', 'La question porte sur le code du projet : je lance une recherche sémantique.'),
    act(T, 's1', 'rag.search', { query: 'session inconnue CLI', top_k: 5 }),
    obs(T, 's1', '5 passages trouvés (bge-m3), seuil de pertinence 0,50.', 340),
    {
      delay: 160,
      event: {
        type: 'rag_sources',
        sources: [
          { path: 'src/sensai/cli.py', lines: '112-116', score: 0.83 },
          { path: 'tests/test_cli_persistence.py', lines: '1-40', score: 0.71 },
          { path: 'docs/decisions/0007-persistance-des-sessions.md', lines: '20-44', score: 0.62 },
        ],
      },
    },
    think(T, 's2', 'Je vérifie le passage le mieux classé avant de répondre.'),
    ...say(
      T,
      "Dans `src/sensai/cli.py`, lignes 112-116, une clause `except KeyError` attrape l'identifiant de session inconnu : le CLI affiche un message clair et repart sur une session vierge au lieu de planter. Le comportement est couvert par `tests/test_cli_persistence.py`.",
    ),
    { delay: 120, event: { type: 'usage', used: 2310, budget: 8192, contextPct: 28 } },
    end(T),
  ],
}
