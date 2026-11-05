import { act, end, obs, say, start, think } from './helpers'
import type { Scenario } from './types'

const T = 't'

export const web: Scenario = {
  id: 'web',
  steps: [
    start(T),
    think(T, 's1', "Tu veux une information récente : je lance une recherche sur le web."),
    act(T, 's1', 'web.search', { query: 'pytest dernière version' }),
    obs(T, 's1', '2 résultats retenus.', 760),
    {
      delay: 160,
      event: {
        type: 'web_results',
        results: [
          { title: 'pytest : documentation officielle', url: 'https://docs.pytest.org/' },
          { title: 'pytest sur PyPI', url: 'https://pypi.org/project/pytest/' },
        ],
      },
    },
    think(T, 's2', "Je lis la page PyPI avec l'outil externe (MCP) pour confirmer."),
    act(T, 's2', 'mcp.fetch', { url: 'https://pypi.org/project/pytest/' }),
    obs(T, 's2', 'Page lue via le serveur MCP.', 540),
    ...say(
      T,
      "La version à jour est indiquée sur la page PyPI de pytest ; je te mets les deux sources plutôt que de citer un numéro de mémoire, qui pourrait être périmé.",
    ),
    end(T),
  ],
}
